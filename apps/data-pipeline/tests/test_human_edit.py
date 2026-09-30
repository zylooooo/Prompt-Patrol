import csv
import json
import random

import pytest

from harness.clients import GenerationResult
from human_edit import assign, build, collect, compare, simulate
from human_edit.common import load_answers, stratified_sample, word_edit_distance

EDIT_TYPES = ["reorder", "delete", "reword", "fact_tweak"]


def make_answer(n, generator="gpt-5.5", tier="weak", text=None):
    return {
        "answer_id": f"mohler/E01.Q0{n % 5 + 1}/{generator}/{tier}/{n:02d}",
        "question_id": f"mohler/E01.Q0{n % 5 + 1}",
        "generator": generator, "tier": tier,
        "answer": text or f"a stack is last in first out and answer {n} explains why",
    }


def make_genuine(n, edit_types=("reword",)):
    source = make_answer(n)
    return {
        "edit_id": f"{source['answer_id']}/edit-genuine", "source_answer_id": source["answer_id"],
        "question_id": source["question_id"], "generator": source["generator"], "tier": source["tier"],
        "edit_source": "genuine", "editor": "faheem", "edit_types": list(edit_types),
        "source_answer": source["answer"], "answer": source["answer"].replace("explains", "shows"),
    }


CONFIG = {
    "seed": 42, "edit_types": EDIT_TYPES,
    "genuine": {"editors": ["faheem", "sean"], "per_editor": 2},
    "simulated": {
        "share": 1.0, "examples": 3,
        "editor": {"name": "fake", "provider": "openai", "model": "fake"},
        "decoding": {"temperature": 0.8, "max_tokens": 500},
    },
}


class FakeClient:
    def __init__(self):
        self.prompts = []

    def generate(self, system, user, decoding):
        self.prompts.append(user)
        return GenerationResult(
            text="an edited answer", model_version="fake-1",
            params_honoured=decoding, usage={"prompt_tokens": 10, "completion_tokens": 5},
        )


# a reasoning model that spent the whole budget thinking and returned nothing
class EmptyClient:
    def generate(self, system, user, decoding):
        return GenerationResult(
            text="", model_version="fake-1",
            params_honoured=decoding, usage={"prompt_tokens": 10, "completion_tokens": 500},
        )


# common

def test_word_edit_distance():
    assert word_edit_distance("A stack is LIFO.", "a stack is lifo") == 0.0
    assert word_edit_distance("one two", "three four") == 1.0
    assert word_edit_distance("a b c d", "a b c") == 0.25
    assert word_edit_distance("", "") == 0.0


def test_load_answers_skips_rewrites(tmp_path):
    path = tmp_path / "answers.jsonl"
    path.write_text(
        json.dumps(make_answer(1)) + "\n" + json.dumps(make_answer(2, tier="rewrite")) + "\n",
        encoding="utf-8",
    )
    assert [r["answer_id"] for r in load_answers(path)] == [make_answer(1)["answer_id"]]


def test_stratified_sample_is_stable_and_covers_groups():
    answers = [make_answer(i, generator=g, tier=t) for i in range(4) for g in ("a", "b") for t in ("weak", "wrong")]
    picked = stratified_sample(answers, 0.5, seed=1)
    assert len(picked) == 8
    assert {(r["generator"], r["tier"]) for r in picked} == {("a", "weak"), ("a", "wrong"), ("b", "weak"), ("b", "wrong")}
    assert picked == stratified_sample(answers, 0.5, seed=1)


# assign

def test_pick_for_editors_gives_each_editor_a_mix_and_no_overlap():
    answers = [make_answer(i, generator=g, tier=t) for i in range(5) for g in ("a", "b") for t in ("weak", "wrong")]
    picked = assign.pick_for_editors(answers, ["faheem", "sean"], 4, seed=1)
    assert [len(v) for v in picked.values()] == [4, 4]
    ids = [r["answer_id"] for rows in picked.values() for r in rows]
    assert len(ids) == len(set(ids))
    for rows in picked.values():
        assert len({(r["generator"], r["tier"]) for r in rows}) >= 3


def test_pick_for_editors_fails_when_short():
    with pytest.raises(SystemExit):
        assign.pick_for_editors([make_answer(1)], ["faheem", "sean"], 2, seed=1)


def test_write_sheets_prefills_edited_answer(tmp_path):
    answers = [make_answer(i) for i in range(4)]
    picked = assign.pick_for_editors(answers, ["faheem", "sean"], 2, seed=1)
    questions = {a["question_id"]: "What is a stack?" for a in answers}
    manifest = assign.write_sheets(picked, questions, tmp_path)
    assert len(manifest) == 4
    with open(tmp_path / "faheem.csv", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert rows[0]["edited_answer"] == rows[0]["original_answer"]
    assert rows[0]["question"] == "What is a stack?"
    assert all(m["edit_id"].endswith("/edit-genuine") for m in manifest)


# collect

def manifest_and_rows():
    answers = [make_answer(i) for i in range(4)]
    picked = assign.pick_for_editors(answers, ["faheem", "sean"], 2, seed=1)
    manifest = []
    for editor, rows in picked.items():
        for r in rows:
            manifest.append({
                "edit_id": f"{r['answer_id']}/edit-genuine", "editor": editor,
                "source_answer_id": r["answer_id"], "question_id": r["question_id"],
                "generator": r["generator"], "tier": r["tier"], "source_answer": r["answer"],
            })
    sheet = [
        {"edit_id": m["edit_id"], "edited_answer": m["source_answer"] + " maybe", "edit_types": "reword, delete"}
        for m in manifest if m["editor"] == "faheem"
    ]
    return manifest, sheet


def test_collect_builds_genuine_records():
    manifest, sheet = manifest_and_rows()
    records, report = collect.collect(manifest, {"faheem": sheet}, EDIT_TYPES)
    assert len(records) == 2
    assert records[0]["edit_source"] == "genuine" and records[0]["edit_types"] == ["reword", "delete"]
    assert report["editors_pending"] == ["sean"]
    assert report["edit_type_counts"]["reword"] == 2


def test_collect_drops_unchanged_rows():
    manifest, sheet = manifest_and_rows()
    source = next(m for m in manifest if m["edit_id"] == sheet[0]["edit_id"])
    sheet[0]["edited_answer"] = "  " + source["source_answer"] + " "
    records, report = collect.collect(manifest, {"faheem": sheet}, EDIT_TYPES)
    assert len(records) == 1 and report["unchanged_dropped"] == 1


@pytest.mark.parametrize("change", [
    {"edit_types": "rewrite"},
    {"edit_types": ""},
    {"edit_id": "not-in-manifest"},
])
def test_collect_stops_on_bad_rows(change):
    manifest, sheet = manifest_and_rows()
    sheet[0].update(change)
    with pytest.raises(SystemExit):
        collect.collect(manifest, {"faheem": sheet}, EDIT_TYPES)


def test_collect_stops_on_row_from_another_editor():
    manifest, sheet = manifest_and_rows()
    with pytest.raises(SystemExit):
        collect.collect(manifest, {"sean": sheet}, EDIT_TYPES)


def test_read_sheet_strips_excel_bom(tmp_path):
    path = tmp_path / "faheem.csv"
    path.write_bytes("﻿edit_id,edited_answer\nx,y\n".encode())
    assert collect.read_sheet(path)[0]["edit_id"] == "x"


# simulate

def test_prompt_spec_follows_genuine_edits():
    genuine = [make_genuine(i, types) for i, types in enumerate(
        [("reword",), ("reword",), ("reword", "delete"), ("delete",), ("reword",), ("reorder", "reword")]
    )]
    spec = simulate.build_prompt_spec(genuine, EDIT_TYPES, examples=3, seed=1)
    assert spec["type_weights"] == {"reorder": 1, "delete": 2, "reword": 5, "fact_tweak": 0}
    assert spec["types_per_answer"] == {"1": 4, "2": 2}
    assert len(spec["examples"]) == 3
    rng = random.Random(0)
    drawn = [simulate.draw_edit_types(spec, rng) for _ in range(200)]
    assert all("fact_tweak" not in d for d in drawn)
    assert {len(d) for d in drawn} == {1, 2}


def test_prompt_spec_needs_enough_genuine():
    with pytest.raises(SystemExit):
        simulate.build_prompt_spec([make_genuine(1)], EDIT_TYPES, examples=3, seed=1)


def test_render_prompt_has_examples_types_and_answer():
    spec = simulate.build_prompt_spec([make_genuine(i) for i in range(5)], EDIT_TYPES, examples=2, seed=1)
    prompt = simulate.render_prompt(spec, "the answer to edit", ["delete", "reword"])
    assert "the answer to edit" in prompt
    assert "cut a sentence" in prompt and "your own" in prompt
    assert prompt.count("Original:") == 2


def test_dry_run_calls_nothing(tmp_path, monkeypatch):
    def fail(config):
        raise AssertionError("dry run must not build clients")

    monkeypatch.setattr(simulate, "build_clients", fail)
    simulate.run(CONFIG, [make_answer(i) for i in range(20, 25)], [make_genuine(i) for i in range(5)],
                 tmp_path / "out", go=False)
    assert not (tmp_path / "out").exists()


def test_run_skips_genuine_sources_and_labels_simulated(tmp_path, monkeypatch):
    client = FakeClient()
    monkeypatch.setattr(simulate, "build_clients", lambda config: {"fake": client})
    genuine = [make_genuine(i) for i in range(5)]
    answers = [make_answer(i) for i in range(8)]
    simulate.run(CONFIG, answers, genuine, tmp_path, go=True)
    records = [json.loads(line) for line in (tmp_path / "simulated.jsonl").read_text().splitlines()]
    assert len(records) == 3
    assert {r["source_answer_id"] for r in records}.isdisjoint({g["source_answer_id"] for g in genuine})
    assert all(r["edit_source"] == "simulated" and r["edit_id"].endswith("/edit-simulated") for r in records)
    assert json.loads((tmp_path / "prompt_spec.json").read_text())["genuine_count"] == 5
    report = json.loads((tmp_path / "run_report.json").read_text())
    assert report["prompt_tokens"] == 30 and report["completion_tokens"] == 15

    simulate.run(CONFIG, answers, genuine, tmp_path, go=True)
    assert len(client.prompts) == 3
    assert json.loads((tmp_path / "run_report.json").read_text())["skipped_existing"] == 3


def test_a_good_edit_resets_the_failure_streak(tmp_path, monkeypatch):
    texts = iter(["", "", "ok", "", "", "ok"])

    class FlakyClient:
        def generate(self, system, user, decoding):
            return GenerationResult(
                text=next(texts), model_version="fake-1",
                params_honoured=decoding, usage={"prompt_tokens": 10, "completion_tokens": 5},
            )

    monkeypatch.setattr(simulate, "build_clients", lambda config: {"fake": FlakyClient()})
    genuine = [make_genuine(i) for i in range(5)]
    # six answers in one generator and tier group, so share 1.0 takes all six
    answers = [make_answer(i) for i in range(20, 26)]
    simulate.run(CONFIG, answers, genuine, tmp_path, go=True)
    report = json.loads((tmp_path / "run_report.json").read_text())
    assert report["requested"] == 6
    assert report["succeeded"] == 2 and report["failed"] == 4


def test_run_stops_after_three_empty_edits(tmp_path, monkeypatch):
    monkeypatch.setattr(simulate, "build_clients", lambda config: {"fake": EmptyClient()})
    genuine = [make_genuine(i) for i in range(5)]
    answers = [make_answer(i) for i in range(20, 30)]
    simulate.run(CONFIG, answers, genuine, tmp_path, go=True)
    report = json.loads((tmp_path / "run_report.json").read_text())
    assert report["failed"] == 3 and report["requested"] == 3
    assert report["completion_tokens"] == 1500
    assert (tmp_path / "simulated.jsonl").read_text() == ""


# compare

def test_compare_and_markdown():
    genuine = [make_genuine(i) for i in range(5)]
    simulated = [{**make_genuine(i), "answer": "totally different words here"} for i in range(5, 10)]
    result = compare.compare(genuine, simulated)
    assert result["genuine"]["n"] == 5 and result["simulated"]["median"] == 1.0
    assert result["ks_statistic"] == 1.0
    assert sum(b["share"] for b in result["genuine"]["histogram"]) == pytest.approx(1.0)
    assert "| genuine | 5 |" in compare.to_markdown(result)


def test_ks_statistic_identical_is_zero():
    assert compare.ks_statistic([0.1, 0.2, 0.3], [0.1, 0.2, 0.3]) == 0.0


# build

def test_build_labels_and_drops_unchanged():
    genuine = [make_genuine(i) for i in range(3)]
    simulated = [{**make_genuine(i), "edit_id": f"s{i}", "edit_source": "simulated"} for i in range(10, 13)]
    simulated[0]["answer"] = simulated[0]["source_answer"]
    records, report = build.build(genuine, simulated)
    assert report == {"total": 5, "genuine": 3, "simulated": 2, "unchanged_dropped": 1}
    assert all(r["label"] == "human_edited" and r["edit_distance"] > 0 for r in records)


def test_build_refuses_simulated_labelled_genuine():
    genuine = [make_genuine(0)]
    fake = {**make_genuine(5), "edit_id": "s5"}  # carries edit_source genuine
    with pytest.raises(SystemExit):
        build.build(genuine, [fake])


def test_build_refuses_source_with_both_kinds():
    genuine = [make_genuine(0)]
    simulated = [{**make_genuine(0), "edit_id": "s0", "edit_source": "simulated"}]
    with pytest.raises(SystemExit):
        build.build(genuine, simulated)

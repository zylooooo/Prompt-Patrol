import csv
import json

import pytest

from harness.clients import GenerationResult
from paraphrase import filter as para_filter
from paraphrase import generate


def make_answer(answer_id, generator="gpt-5.5", tier="weak", text="a stack is last in first out"):
    return {
        "answer_id": answer_id, "question_id": answer_id.rsplit("/", 3)[0],
        "generator": generator, "tier": tier, "answer": text,
    }


class FakeClient:
    def __init__(self):
        self.prompts = []

    def generate(self, system, user, decoding):
        self.prompts.append(user)
        return GenerationResult(
            text="a stack works last in, first out", model_version="fake-1",
            params_honoured=decoding, usage={"prompt_tokens": 10, "completion_tokens": 5},
        )


class BrokenClient:
    def generate(self, system, user, decoding):
        raise RuntimeError("endpoint down")


# a reasoning model that spent the whole budget thinking and returned nothing
class EmptyClient:
    def generate(self, system, user, decoding):
        return GenerationResult(
            text="", model_version="fake-1",
            params_honoured=decoding, usage={"prompt_tokens": 10, "completion_tokens": 500},
        )


class FakeEmbedder:
    """Same text gets the same vector, texts sharing a first word point the
    same way, so similarity is predictable without an API."""

    def embed(self, texts):
        return [[1.0, 0.0] if t.split()[0] == "a" else [0.0, 1.0] for t in texts]


CONFIG = {
    "share": 1.0, "seed": 42, "strengths": ["light", "heavy"],
    "paraphraser": {"name": "fake", "provider": "openai", "model": "fake"},
    "decoding": {"temperature": 0.7, "max_tokens": 500},
    "filters": {"embedding_model": "fake", "similarity_floor": None, "min_surface_change": None},
}


def test_load_answers_drops_empty(tmp_path):
    path = tmp_path / "answers.jsonl"
    path.write_text(
        json.dumps(make_answer("mohler/E01.Q01/gpt-5.5/weak/01")) + "\n"
        + json.dumps(make_answer("mohler/E01.Q01/gpt-5.5/weak/02", text="  ")) + "\n",
        encoding="utf-8",
    )
    assert [r["answer_id"] for r in generate.load_answers(path)] == ["mohler/E01.Q01/gpt-5.5/weak/01"]


def test_load_answers_skips_rewrites(tmp_path):
    path = tmp_path / "answers.jsonl"
    path.write_text(
        json.dumps(make_answer("mohler/E01.Q01/gpt-5.5/weak/01")) + "\n"
        + json.dumps(make_answer("mohler/E01.Q01/gpt-5.5/rewrite/01", tier="rewrite")) + "\n",
        encoding="utf-8",
    )
    assert [r["answer_id"] for r in generate.load_answers(path)] == ["mohler/E01.Q01/gpt-5.5/weak/01"]


def test_select_answers_covers_every_generator_and_tier():
    answers = [
        make_answer(f"mohler/E01.Q0{i}/{g}/{t}/01", generator=g, tier=t)
        for g in ("gpt-5.5", "claude-sonnet-5") for t in ("weak", "wrong") for i in range(1, 5)
    ]
    picked = generate.select_answers(answers, 0.5, seed=1)
    assert len(picked) == 8
    assert {(r["generator"], r["tier"]) for r in picked} == {
        ("gpt-5.5", "weak"), ("gpt-5.5", "wrong"), ("claude-sonnet-5", "weak"), ("claude-sonnet-5", "wrong"),
    }
    assert picked == generate.select_answers(answers, 0.5, seed=1)


def test_select_answers_rejects_bad_share():
    with pytest.raises(SystemExit):
        generate.select_answers([make_answer("mohler/E01.Q01/gpt-5.5/weak/01")], 0, seed=1)


def test_dry_run_calls_nothing(tmp_path, monkeypatch):
    def fail(config):
        raise AssertionError("dry run must not build clients")

    monkeypatch.setattr(generate, "build_clients", fail)
    generate.run(CONFIG, [make_answer("mohler/E01.Q01/gpt-5.5/weak/01")], tmp_path / "out", go=False)
    assert not (tmp_path / "out").exists()


def test_run_writes_linked_records_per_strength(tmp_path, monkeypatch):
    client = FakeClient()
    monkeypatch.setattr(generate, "build_clients", lambda config: {"fake": client})
    source = make_answer("mohler/E01.Q01/gpt-5.5/weak/01")
    generate.run(CONFIG, [source], tmp_path, go=True)

    records = [json.loads(line) for line in (tmp_path / "candidates.jsonl").read_text().splitlines()]
    assert [r["paraphrase_id"] for r in records] == [
        "mohler/E01.Q01/gpt-5.5/weak/01/para-light", "mohler/E01.Q01/gpt-5.5/weak/01/para-heavy",
    ]
    first = records[0]
    assert first["source_answer_id"] == "mohler/E01.Q01/gpt-5.5/weak/01"
    assert first["generator"] == "gpt-5.5"
    assert first["paraphraser"] == "fake"
    assert first["paraphraser_model_version"] == "fake-1"
    assert first["prompt_template"] == "light_v2"
    assert source["answer"] in client.prompts[0]
    report = json.loads((tmp_path / "run_report.json").read_text())
    assert report["succeeded"] == 2 and report["failed"] == 0
    assert report["prompt_tokens"] == 20 and report["completion_tokens"] == 10


def test_rerun_skips_existing(tmp_path, monkeypatch):
    client = FakeClient()
    monkeypatch.setattr(generate, "build_clients", lambda config: {"fake": client})
    answers = [make_answer("mohler/E01.Q01/gpt-5.5/weak/01")]
    generate.run(CONFIG, answers, tmp_path, go=True)
    generate.run(CONFIG, answers, tmp_path, go=True)
    assert len(client.prompts) == 2
    assert len((tmp_path / "candidates.jsonl").read_text().splitlines()) == 2
    assert json.loads((tmp_path / "run_report.json").read_text())["skipped_existing"] == 2


def test_run_stops_after_three_failures(tmp_path, monkeypatch):
    monkeypatch.setattr(generate, "build_clients", lambda config: {"fake": BrokenClient()})
    answers = [make_answer(f"mohler/E01.Q0{i}/gpt-5.5/weak/01") for i in range(1, 6)]
    generate.run(CONFIG, answers, tmp_path, go=True)
    report = json.loads((tmp_path / "run_report.json").read_text())
    assert report["failed"] == 3 and report["requested"] == 3


def test_a_good_paraphrase_resets_the_failure_streak(tmp_path, monkeypatch):
    texts = iter(["", "", "ok", "", "", "ok"])

    class FlakyClient:
        def generate(self, system, user, decoding):
            return GenerationResult(
                text=next(texts), model_version="fake-1",
                params_honoured=decoding, usage={"prompt_tokens": 10, "completion_tokens": 5},
            )

    monkeypatch.setattr(generate, "build_clients", lambda config: {"fake": FlakyClient()})
    answers = [make_answer(f"mohler/E01.Q0{i}/gpt-5.5/weak/01") for i in range(1, 4)]
    generate.run(CONFIG, answers, tmp_path, go=True)
    report = json.loads((tmp_path / "run_report.json").read_text())
    assert report["requested"] == 6
    assert report["succeeded"] == 2 and report["failed"] == 4


def test_run_stops_after_three_empty_paraphrases(tmp_path, monkeypatch):
    monkeypatch.setattr(generate, "build_clients", lambda config: {"fake": EmptyClient()})
    answers = [make_answer(f"mohler/E01.Q0{i}/gpt-5.5/weak/01") for i in range(1, 6)]
    generate.run(CONFIG, answers, tmp_path, go=True)
    report = json.loads((tmp_path / "run_report.json").read_text())
    assert report["failed"] == 3 and report["requested"] == 3
    assert report["completion_tokens"] == 1500
    assert (tmp_path / "candidates.jsonl").read_text() == ""


def test_unknown_strength_fails_at_plan_time(tmp_path):
    config = {**CONFIG, "strengths": ["medium"]}
    with pytest.raises(SystemExit):
        generate.run(config, [make_answer("mohler/E01.Q01/gpt-5.5/weak/01")], tmp_path, go=False)


def test_surface_change():
    assert para_filter.surface_change("A stack is LIFO.", "a stack is lifo") == 0.0
    assert para_filter.surface_change("one two", "three four") == 1.0
    assert 0 < para_filter.surface_change("a stack is lifo", "a stack is last in first out") < 1


def test_cosine():
    assert para_filter.cosine([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)
    assert para_filter.cosine([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)
    assert para_filter.cosine([0.0, 0.0], [1.0, 0.0]) == 0.0


def test_exclusion_reason_thresholds():
    candidate = {"strength": "heavy", "similarity": 0.8, "surface_change": 0.2}
    assert para_filter.exclusion_reason(candidate, {"similarity_floor": None, "min_surface_change": None}) is None
    assert para_filter.exclusion_reason(candidate, {"similarity_floor": 0.9}) == "meaning_lost"
    assert para_filter.exclusion_reason(candidate, {"min_surface_change": 0.3}) == "trivial_rewrite"
    per_strength = {"min_surface_change": {"light": 0.1, "heavy": 0.3}}
    assert para_filter.exclusion_reason(candidate, per_strength) == "trivial_rewrite"
    assert para_filter.exclusion_reason({**candidate, "strength": "light"}, per_strength) is None


def candidate(pid, strength, source, answer):
    return {"paraphrase_id": pid, "strength": strength, "source_answer": source, "answer": answer}


def test_run_filter_splits_counts_and_spot_checks(tmp_path):
    candidates = [
        candidate("x/para-light", "light", "a stack is lifo", "a stack is last in first out"),
        candidate("y/para-heavy", "heavy", "a queue is fifo", "the queue is first in first out"),
        candidate("z/para-light", "light", "a heap is a tree", "a heap is a tree"),
    ]
    config = {**CONFIG, "filters": {"similarity_floor": 0.5, "min_surface_change": 0.05}}
    report = para_filter.run_filter(config, candidates, FakeEmbedder(), tmp_path, spot_check=2)

    assert report["kept"] == 1
    assert report["excluded_by_reason"] == {"meaning_lost": 1, "trivial_rewrite": 1}
    kept = [json.loads(line) for line in (tmp_path / "paraphrased.jsonl").read_text().splitlines()]
    assert kept[0]["paraphrase_id"] == "x/para-light" and kept[0]["label"] == "paraphrased"
    excluded = [json.loads(line) for line in (tmp_path / "excluded.jsonl").read_text().splitlines()]
    assert {r["exclusion_reason"] for r in excluded} == {"meaning_lost", "trivial_rewrite"}
    with open(tmp_path / "spot_check.csv", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 2 and rows[0]["meaning_kept"] == ""


def test_pilot_keeps_everything(tmp_path):
    candidates = [candidate("y/para-heavy", "heavy", "a queue is fifo", "the queue is first in first out")]
    report = para_filter.run_filter(CONFIG, candidates, FakeEmbedder(), tmp_path)
    assert report["kept"] == 1 and report["excluded"] == 0
    assert not (tmp_path / "spot_check.csv").exists()

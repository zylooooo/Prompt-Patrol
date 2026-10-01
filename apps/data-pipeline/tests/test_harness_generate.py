import json
import logging
import re
from pathlib import Path

import pandas as pd
import pytest

from harness import generate
from harness.clients import GenerationResult

COURSE = "a test course"
# every tier needs a pool, rewrites polish one answer and the rest take its length
POOL = [("mohler/E01.Q01.A00", "a stack is last in first out")]


class FakeClient:
    def generate(self, system, user, decoding):
        return GenerationResult(
            text="an answer", model_version="fake-1",
            params_honoured=decoding, usage={"prompt_tokens": 10, "completion_tokens": 5},
        )


# a reasoning model that spent the whole budget thinking and returned nothing
class EmptyClient:
    def generate(self, system, user, decoding):
        return GenerationResult(
            text="", model_version="fake-1",
            params_honoured=decoding, usage={"prompt_tokens": 10, "completion_tokens": 400},
        )


def test_load_questions_collapses_answer_ids(tmp_path):
    df = pd.DataFrame({
        "id": ["E01.Q01.A00", "E01.Q01.A01", "E02.Q03.A00"],
        "question": ["q1", "q1", "q2"],
    })
    path = tmp_path / "corpus.parquet"
    df.to_parquet(path)
    questions = generate.load_questions(path, "mohler")
    assert list(questions["question_id"]) == ["mohler/E01.Q01", "mohler/E02.Q03"]


def test_load_questions_normalises_other_dataset_columns(tmp_path):
    df = pd.DataFrame({
        "id": ["PythonQ057.A0", "PythonQ057.A1"],
        "QuestionID": ["PythonQ057", "PythonQ057"],
        "QuestionText": ["q", "q"],
        "StudentAnswer": ["s1", "s2"],
    })
    path = tmp_path / "sprag.parquet"
    df.to_parquet(path)
    questions = generate.load_questions(path, "sprag")
    assert list(questions["question_id"]) == ["sprag/PythonQ057"]
    assert list(questions.columns) == ["question_id", "question", "student_answers"]
    assert sorted(questions["student_answers"][0]) == [("sprag/PythonQ057.A0", "s1"), ("sprag/PythonQ057.A1", "s2")]


def test_run_writes_records_and_report(tmp_path, monkeypatch):
    monkeypatch.setattr(generate, "build_clients", lambda config: {"fake": FakeClient()})
    questions = pd.DataFrame([
        {"question_id": "mohler/E01.Q01", "question": "What is a stack?", "student_answers": POOL},
    ])
    config = {
        "course": COURSE,
        "samples_per_question": {"weak": 2},
        "decoding": {"temperature": 0.8, "max_tokens": 400},
        "generators": [],
    }
    generate.run(config, questions, tmp_path, go=True)

    records = [json.loads(line) for line in (tmp_path / "answers.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [r["answer_id"] for r in records] == ["mohler/E01.Q01/fake/weak/01", "mohler/E01.Q01/fake/weak/02"]
    report = json.loads((tmp_path / "run_report.json").read_text(encoding="utf-8"))
    assert report["fake"] == {"requested": 2, "succeeded": 2, "failed": 0, "prompt_tokens": 20, "completion_tokens": 10}


def test_empty_answer_counts_as_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(generate, "build_clients", lambda config: {"fake": EmptyClient()})
    questions = pd.DataFrame([
        {"question_id": "mohler/E01.Q01", "question": "What is a stack?", "student_answers": POOL},
    ])
    config = {
        "course": COURSE,
        "samples_per_question": {"wrong": 1},
        "decoding": {"temperature": 0.8, "max_tokens": 400},
        "generators": [],
    }
    generate.run(config, questions, tmp_path, go=True)

    assert (tmp_path / "answers.jsonl").read_text(encoding="utf-8") == ""
    report = json.loads((tmp_path / "run_report.json").read_text(encoding="utf-8"))
    assert report["fake"] == {"requested": 1, "succeeded": 0, "failed": 1, "prompt_tokens": 10, "completion_tokens": 400}


def test_repeated_empty_answers_abandon_the_generator(tmp_path, monkeypatch):
    calls = {"n": 0}

    class CountingEmptyClient:
        def generate(self, system, user, decoding):
            calls["n"] += 1
            return GenerationResult(
                text="", model_version="fake-1",
                params_honoured=decoding, usage={"prompt_tokens": 10, "completion_tokens": 400},
            )

    monkeypatch.setattr(generate, "build_clients", lambda config: {"fake": CountingEmptyClient()})
    questions = pd.DataFrame([
        {"question_id": f"mohler/E01.Q{i:02d}", "question": "q", "student_answers": POOL} for i in range(10)
    ])
    config = {
        "course": COURSE,
        "samples_per_question": {"correct": 2},
        "decoding": {"temperature": 0.8, "max_tokens": 400},
        "generators": [],
    }
    generate.run(config, questions, tmp_path, go=True)
    assert calls["n"] == 3


def test_raising_client_is_abandoned_after_three_calls(tmp_path, monkeypatch):
    calls = {"n": 0}

    class BrokenClient:
        def generate(self, system, user, decoding):
            calls["n"] += 1
            raise RuntimeError("endpoint down")

    monkeypatch.setattr(generate, "build_clients", lambda config: {"fake": BrokenClient()})
    questions = pd.DataFrame([{"question_id": f"mohler/E01.Q{i:02d}", "question": "q", "student_answers": POOL} for i in range(10)])
    config = {"course": COURSE, "samples_per_question": {"correct": 2}, "decoding": {}, "generators": []}
    generate.run(config, questions, tmp_path, go=True)

    assert calls["n"] == 3
    report = json.loads((tmp_path / "run_report.json").read_text(encoding="utf-8"))
    assert report["fake"]["requested"] == 3 and report["fake"]["failed"] == 3


def test_errors_and_empty_answers_share_one_streak(tmp_path, monkeypatch):
    replies = iter([RuntimeError("timeout"), "", RuntimeError("timeout"), "an answer"])
    calls = {"n": 0}

    class MixedClient:
        def generate(self, system, user, decoding):
            calls["n"] += 1
            reply = next(replies)
            if isinstance(reply, Exception):
                raise reply
            return GenerationResult(
                text=reply, model_version="fake-1",
                params_honoured=decoding, usage={"prompt_tokens": 10, "completion_tokens": 5},
            )

    monkeypatch.setattr(generate, "build_clients", lambda config: {"fake": MixedClient()})
    questions = pd.DataFrame([{"question_id": f"mohler/E01.Q{i:02d}", "question": "q", "student_answers": POOL} for i in range(4)])
    config = {"course": COURSE, "samples_per_question": {"correct": 1}, "decoding": {}, "generators": []}
    generate.run(config, questions, tmp_path, go=True)
    assert calls["n"] == 3


def test_every_record_is_on_disk_before_the_next_call(tmp_path, monkeypatch):
    lines_seen = []

    class PeekingClient:
        def generate(self, system, user, decoding):
            lines_seen.append(len((tmp_path / "answers.jsonl").read_text(encoding="utf-8").splitlines()))
            return GenerationResult(
                text="an answer", model_version="fake-1",
                params_honoured=decoding, usage={"prompt_tokens": 10, "completion_tokens": 5},
            )

    monkeypatch.setattr(generate, "build_clients", lambda config: {"fake": PeekingClient()})
    questions = pd.DataFrame([{"question_id": "mohler/E01.Q01", "question": "q", "student_answers": POOL}])
    config = {"course": COURSE, "samples_per_question": {"correct": 2}, "decoding": {}, "generators": []}
    generate.run(config, questions, tmp_path, go=True)
    assert lines_seen == [0, 1]


def test_rerunning_a_folder_skips_paid_calls_and_reports_the_folder(tmp_path, monkeypatch):
    calls = {"n": 0}

    class CountingClient:
        def generate(self, system, user, decoding):
            calls["n"] += 1
            return GenerationResult(
                text="an answer", model_version="fake-1",
                params_honoured=decoding, usage={"prompt_tokens": 10, "completion_tokens": 5},
            )

    monkeypatch.setattr(generate, "build_clients", lambda config: {"fake": CountingClient()})
    questions = pd.DataFrame([
        {"question_id": "mohler/E01.Q01", "question": "q", "student_answers": POOL},
    ])
    config = {
        "course": COURSE,
        "samples_per_question": {"correct": 2},
        "decoding": {"temperature": 0.8, "max_tokens": 400},
        "generators": [],
    }
    generate.run(config, questions, tmp_path, go=True)
    generate.run(config, questions, tmp_path, go=True)

    records = [json.loads(line) for line in (tmp_path / "answers.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len({r["answer_id"] for r in records}) == len(records) == 2
    assert calls["n"] == 2
    report = json.loads((tmp_path / "run_report.json").read_text(encoding="utf-8"))
    assert report["fake"] == {"requested": 2, "succeeded": 2, "failed": 0, "prompt_tokens": 20, "completion_tokens": 10}


def test_a_good_answer_resets_the_failure_streak(tmp_path, monkeypatch):
    texts = iter(["", "", "an answer", "", "", "an answer"])

    class FlakyClient:
        def generate(self, system, user, decoding):
            return GenerationResult(
                text=next(texts), model_version="fake-1",
                params_honoured=decoding, usage={"prompt_tokens": 10, "completion_tokens": 5},
            )

    monkeypatch.setattr(generate, "build_clients", lambda config: {"fake": FlakyClient()})
    questions = pd.DataFrame([
        {"question_id": "mohler/E01.Q01", "question": "q", "student_answers": POOL},
    ])
    config = {
        "course": COURSE,
        "samples_per_question": {"correct": 6},
        "decoding": {"temperature": 0.8, "max_tokens": 400},
        "generators": [],
    }
    generate.run(config, questions, tmp_path, go=True)

    report = json.loads((tmp_path / "run_report.json").read_text(encoding="utf-8"))
    assert report["fake"]["requested"] == 6
    assert report["fake"]["succeeded"] == 2 and report["fake"]["failed"] == 4


def test_resume_fills_gaps_and_keeps_billed_failures(tmp_path, monkeypatch):
    texts = iter(["an answer", ""])

    class HalfEmptyClient:
        def generate(self, system, user, decoding):
            return GenerationResult(
                text=next(texts), model_version="fake-1",
                params_honoured=decoding, usage={"prompt_tokens": 10, "completion_tokens": 400},
            )

    questions = pd.DataFrame([
        {"question_id": "mohler/E01.Q01", "question": "q", "student_answers": POOL},
    ])
    config = {
        "course": COURSE,
        "samples_per_question": {"correct": 2},
        "decoding": {"temperature": 0.8, "max_tokens": 400},
        "generators": [],
    }
    monkeypatch.setattr(generate, "build_clients", lambda config: {"fake": HalfEmptyClient()})
    generate.run(config, questions, tmp_path, go=True)
    monkeypatch.setattr(generate, "build_clients", lambda config: {"fake": FakeClient()})
    generate.run(config, questions, tmp_path, go=True)

    records = [json.loads(line) for line in (tmp_path / "answers.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [r["answer_id"] for r in records] == ["mohler/E01.Q01/fake/correct/01", "mohler/E01.Q01/fake/correct/02"]
    report = json.loads((tmp_path / "run_report.json").read_text(encoding="utf-8"))
    # the empty answer from the first run left no record but was still billed
    assert report["fake"] == {"requested": 3, "succeeded": 2, "failed": 1, "prompt_tokens": 30, "completion_tokens": 805}


def test_resume_after_a_killed_run_counts_the_records(tmp_path, monkeypatch):
    monkeypatch.setattr(generate, "build_clients", lambda config: {"fake": FakeClient()})
    questions = pd.DataFrame([
        {"question_id": "mohler/E01.Q01", "question": "q", "student_answers": POOL},
    ])
    config = {
        "course": COURSE,
        "samples_per_question": {"correct": 1},
        "decoding": {"temperature": 0.8, "max_tokens": 400},
        "generators": [],
    }
    generate.run(config, questions, tmp_path, go=True)
    # a hard kill skips the finally block, so the folder holds records but no report
    (tmp_path / "run_report.json").unlink()
    config["samples_per_question"] = {"correct": 2}
    generate.run(config, questions, tmp_path, go=True)

    report = json.loads((tmp_path / "run_report.json").read_text(encoding="utf-8"))
    assert report["fake"] == {"requested": 2, "succeeded": 2, "failed": 0, "prompt_tokens": 20, "completion_tokens": 10}


def test_resume_after_a_killed_resume_recounts_a_stale_report(tmp_path, monkeypatch):
    monkeypatch.setattr(generate, "build_clients", lambda config: {"fake": FakeClient()})
    questions = pd.DataFrame([{"question_id": "mohler/E01.Q01", "question": "q", "student_answers": POOL}])
    config = {"course": COURSE, "samples_per_question": {"correct": 1}, "decoding": {}, "generators": []}
    generate.run(config, questions, tmp_path, go=True)
    # a resume killed after writing a record leaves the older report behind
    answers = tmp_path / "answers.jsonl"
    first = json.loads(answers.read_text(encoding="utf-8").splitlines()[0])
    with open(answers, "a", encoding="utf-8") as f:
        f.write(json.dumps({**first, "answer_id": "mohler/E01.Q01/fake/correct/02"}) + "\n")
    config["samples_per_question"] = {"correct": 2}
    generate.run(config, questions, tmp_path, go=True)

    report = json.loads((tmp_path / "run_report.json").read_text(encoding="utf-8"))
    assert report["fake"] == {"requested": 2, "succeeded": 2, "failed": 0, "prompt_tokens": 20, "completion_tokens": 10}


def test_resume_keeps_the_report_of_generators_left_out(tmp_path, monkeypatch):
    questions = pd.DataFrame([{"question_id": "mohler/E01.Q01", "question": "q", "student_answers": POOL}])
    config = {"course": COURSE, "samples_per_question": {"correct": 1}, "decoding": {}, "generators": []}
    monkeypatch.setattr(generate, "build_clients", lambda config: {"g1": FakeClient(), "g2": EmptyClient()})
    generate.run(config, questions, tmp_path, go=True)
    monkeypatch.setattr(generate, "build_clients", lambda config: {"g1": FakeClient()})
    generate.run(config, questions, tmp_path, go=True)

    report = json.loads((tmp_path / "run_report.json").read_text(encoding="utf-8"))
    assert report["g2"] == {"requested": 1, "succeeded": 0, "failed": 1, "prompt_tokens": 10, "completion_tokens": 400}


def test_dry_run_counts_only_answers_the_plan_would_skip(tmp_path, caplog):
    from harness.prompts import TIER_TO_TEMPLATE

    # made with this run's prompts for this dataset, by a generator the plan leaves out
    record = {"answer_id": "sprag/PythonQ057/g2/correct/01", "question_id": "sprag/PythonQ057", "generator": "g2",
              "tier": "correct", "prompt_template": TIER_TO_TEMPLATE["correct"], "course": COURSE}
    (tmp_path / "answers.jsonl").write_text(json.dumps(record) + "\n", encoding="utf-8")
    questions = pd.DataFrame([{"question_id": "sprag/PythonQ057", "question": "q", "student_answers": POOL}])
    config = {"course": COURSE, "samples_per_question": {"correct": 1}, "decoding": {}, "generators": [{"name": "g1"}]}
    with caplog.at_level(logging.INFO, logger="harness.generate"):
        generate.run(config, questions, tmp_path, go=False)
    assert "0 answers already in" in caplog.text and "1 calls still to make" in caplog.text
    assert "1 answers in the folder are outside this plan" in caplog.text


def fake_main_inputs(tmp_path, monkeypatch, argv):
    """Point main() at tmp_path and capture the folder it would write to."""
    calls = []
    monkeypatch.setattr(generate, "PIPELINE_DIR", tmp_path)
    # the fake config names its dataset after the file, as the real ones do
    monkeypatch.setattr(generate, "load_config", lambda path: {"questions_file": "q.parquet", "dataset": Path(path).stem})
    monkeypatch.setattr(generate, "load_questions", lambda path, namespace: pd.DataFrame(
        [{"question_id": "mohler/E01.Q01", "question": "q", "student_answers": POOL}]
    ))
    monkeypatch.setattr(generate, "run", lambda config, questions, out_dir, go: calls.append(out_dir))
    monkeypatch.setattr("sys.argv", ["generate", *argv])
    return calls


def test_resume_writes_into_the_named_run(tmp_path, monkeypatch):
    run_dir = tmp_path / "data" / "generated" / "20260930T120000Z-mohler-pilot"
    run_dir.mkdir(parents=True)
    calls = fake_main_inputs(tmp_path, monkeypatch, ["--dataset", "mohler", "--resume", "20260930T120000Z-mohler-pilot"])
    generate.main()
    assert calls == [run_dir]


def test_resume_refuses_a_missing_run(tmp_path, monkeypatch):
    calls = fake_main_inputs(tmp_path, monkeypatch, ["--dataset", "mohler", "--resume", "20260930T120000Z-mohler-pilt"])
    with pytest.raises(SystemExit, match="no run folder"):
        generate.main()
    assert calls == []


def test_new_run_folder_names_its_dataset_and_tag(tmp_path, monkeypatch):
    calls = fake_main_inputs(tmp_path, monkeypatch, ["--dataset", "sprag", "--tag", "pilot"])
    generate.main()
    assert re.fullmatch(r"\d{8}T\d{6}Z-sprag-pilot", calls[0].name)


def test_a_run_needs_a_dataset_or_a_config(tmp_path, monkeypatch):
    calls = fake_main_inputs(tmp_path, monkeypatch, ["--tag", "pilot"])
    with pytest.raises(SystemExit):
        generate.main()
    assert calls == []


def test_dataset_configs_differ_only_in_their_corpus():
    configs = {path.stem: generate.load_config(path) for path in generate.CONFIG_DIR.glob("*.yaml")}
    assert set(configs) == {"mohler", "sprag", "engsaf"}
    for name, config in configs.items():
        assert config["dataset"] == name
        assert config["questions_file"] == f"data/cleaned/{name}_cleaned.parquet"
    # a generator or decoding change has to reach all three files
    assert all(config["course"] for config in configs.values())
    shared = [{k: v for k, v in c.items() if k not in ("dataset", "questions_file", "course")} for c in configs.values()]
    assert all(s == shared[0] for s in shared)


def test_dry_run_writes_nothing(tmp_path):
    questions = pd.DataFrame([
        {"question_id": "mohler/E01.Q01", "question": "q", "student_answers": POOL},
    ])
    config = {"course": COURSE, "samples_per_question": {"weak": 1}, "decoding": {}, "generators": []}
    generate.run(config, questions, tmp_path / "out", go=False)
    assert not (tmp_path / "out").exists()


def test_every_tier_maps_to_a_real_template():
    from harness.prompts import SYSTEM_OVERRIDES, TEMPLATES, TIER_TO_TEMPLATE

    assert set(TIER_TO_TEMPLATE.values()) <= set(TEMPLATES)
    assert set(SYSTEM_OVERRIDES) <= set(TEMPLATES)


def test_only_the_rewrite_template_swaps_the_system_prompt(tmp_path, monkeypatch):
    from harness.prompts import REWRITE_SYSTEM, SYSTEM

    systems = {}

    class CapturingClient:
        def generate(self, system, user, decoding):
            systems[user] = system
            return GenerationResult(
                text="an answer", model_version="fake-1",
                params_honoured=decoding, usage={"prompt_tokens": 1, "completion_tokens": 1},
            )

    monkeypatch.setattr(generate, "build_clients", lambda config: {"fake": CapturingClient()})
    questions = pd.DataFrame([
        {"question_id": "mohler/E01.Q01", "question": "What is a stack?",
         "student_answers": [("mohler/E01.Q01.A00", "a stack is last in first out")]},
    ])
    config = {
        "course": COURSE,
        "samples_per_question": {"correct": 1, "weak": 1, "partial": 1, "wrong": 1, "rewrite": 1},
        "decoding": {"temperature": 0.8, "max_tokens": 400},
        "generators": [],
    }
    generate.run(config, questions, tmp_path, go=True)

    assert systems.pop("a stack is last in first out") == REWRITE_SYSTEM
    assert len(systems) == 4
    assert set(systems.values()) == {SYSTEM.format(course=COURSE)}


def test_is_rewrite_follows_the_tier():
    from harness.prompts import REWRITE_TIERS, is_rewrite

    assert REWRITE_TIERS == {"rewrite"}
    assert is_rewrite({"answer_id": "mohler/E01.Q01/fake/rewrite/01", "tier": "rewrite"})
    # paraphrase and human-edit records keep their source's tier
    assert is_rewrite({"paraphrase_id": "mohler/E01.Q01/fake/rewrite/01/para-light", "tier": "rewrite"})
    assert not is_rewrite({"paraphrase_id": "mohler/E01.Q01/fake/weak/01/para-light", "tier": "weak",
                           "source_answer_id": "mohler/E01.Q01/fake/weak/01"})


def test_word_target_comes_from_the_question_students(tmp_path, monkeypatch):
    prompts = []

    class CapturingClient:
        def generate(self, system, user, decoding):
            prompts.append(user)
            return GenerationResult(
                text="an answer", model_version="fake-1",
                params_honoured=decoding, usage={"prompt_tokens": 1, "completion_tokens": 1},
            )

    monkeypatch.setattr(generate, "build_clients", lambda config: {"fake": CapturingClient()})
    pool = [(f"mohler/E01.Q01.A{i:02d}", " ".join(["word"] * n)) for i, n in enumerate((5, 12, 30))]
    questions = pd.DataFrame([{"question_id": "mohler/E01.Q01", "question": "q", "student_answers": pool}])
    config = {"course": COURSE, "samples_per_question": {"correct": 1, "weak": 1, "partial": 1, "wrong": 1},
              "decoding": {}, "generators": []}
    generate.run(config, questions, tmp_path, go=True)

    records = [json.loads(line) for line in (tmp_path / "answers.jsonl").read_text(encoding="utf-8").splitlines()]
    assert {r["target_words"] for r in records} <= {5, 12, 30}
    assert {r["course"] for r in records} == {COURSE}
    for record, prompt in zip(records, prompts, strict=True):
        assert f"about {record['target_words']} words" in prompt
        assert "Question: q" in prompt
        # fixed by the answer id, so a resumed call asks for the same length
        assert record["target_words"] == generate.pick_target_words(questions.iloc[0], record["answer_id"])


def test_every_quality_tier_has_its_own_template():
    from harness.prompts import TIER_TO_TEMPLATE

    for tier, template in TIER_TO_TEMPLATE.items():
        assert template.startswith(tier + "_")


def test_count_words_splits_on_commas_too():
    assert generate.count_words("min(),max(),len()") == 3
    assert generate.count_words("a stack  is\nLIFO") == 4
    assert generate.count_words("a;b;c") == 3
    assert generate.count_words("vector<int>") == 2


def test_word_targets_spread_over_the_students_lengths():
    pool = [(f"mohler/E01.Q01.A{i:02d}", " ".join(["w"] * n)) for i, n in enumerate(range(3, 33))]
    row = {"student_answers": pool}
    targets = [generate.pick_target_words(row, f"mohler/E01.Q01/g{g}/{t}/01")
               for g in range(20) for t in ("correct", "weak", "partial", "wrong")]
    assert len(set(targets)) > 15
    assert min(targets) < 10 and max(targets) > 25


def test_word_target_never_drops_below_the_floor():
    row = {"student_answers": [("mohler/E01.Q01.A00", "LIFO")]}
    assert generate.pick_target_words(row, "mohler/E01.Q01/fake/correct/01") == generate.MIN_TARGET_WORDS == 3


def test_system_prompt_names_the_course(tmp_path, monkeypatch):
    systems = []

    class CapturingClient:
        def generate(self, system, user, decoding):
            systems.append(system)
            return GenerationResult(
                text="an answer", model_version="fake-1",
                params_honoured=decoding, usage={"prompt_tokens": 1, "completion_tokens": 1},
            )

    monkeypatch.setattr(generate, "build_clients", lambda config: {"fake": CapturingClient()})
    questions = pd.DataFrame([{"question_id": "mohler/E01.Q01", "question": "q", "student_answers": POOL}])
    config = {"course": "a Python programming course", "samples_per_question": {"correct": 1},
              "decoding": {}, "generators": []}
    generate.run(config, questions, tmp_path, go=True)
    assert "in a Python programming course." in systems[0]
    assert "{course}" not in systems[0]


def test_every_template_formats_with_the_run_keys():
    from harness.prompts import TEMPLATES

    for template in TEMPLATES.values():
        template.format(question="q", student_answer="s", target_words=10)


def test_questions_flag_rejects_zero_and_negatives():
    import argparse

    assert generate.positive_int("2") == 2
    for value in ("0", "-3"):
        with pytest.raises(argparse.ArgumentTypeError):
            generate.positive_int(value)


def test_load_questions_pools_every_written_answer_in_a_fixed_order(tmp_path):
    df = pd.DataFrame({
        "id": [f"E01.Q01.A{i:02d}" for i in range(6)],
        "question": ["q1"] * 6,
        "student_answer": ["a0", "a1", "  ", None, "a4", "a5"],
    })
    path = tmp_path / "corpus.parquet"
    df.to_parquet(path)
    pool = generate.load_questions(path, "mohler")["student_answers"][0]
    assert sorted(pool) == [(f"mohler/E01.Q01.A{i:02d}", f"a{i}") for i in (0, 1, 4, 5)]

    # the seeded shuffle gives this order on every machine and in every process
    assert pool == [("mohler/E01.Q01.A01", "a1"), ("mohler/E01.Q01.A04", "a4"),
                    ("mohler/E01.Q01.A00", "a0"), ("mohler/E01.Q01.A05", "a5")]
    # and it does not depend on the order the file lists answers in
    df.iloc[::-1].to_parquet(path)
    assert generate.load_questions(path, "mohler")["student_answers"][0] == pool


def test_each_generator_polishes_a_different_student(tmp_path, monkeypatch):
    prompts = {}

    def capturing(name):
        class CapturingClient:
            def generate(self, system, user, decoding):
                prompts.setdefault(name, []).append(user)
                return GenerationResult(
                    text="rewritten", model_version="fake-1",
                    params_honoured=decoding, usage={"prompt_tokens": 1, "completion_tokens": 1},
                )
        return CapturingClient()

    monkeypatch.setattr(generate, "build_clients", lambda config: {"g1": capturing("g1"), "g2": capturing("g2")})
    pool = [(f"mohler/E01.Q01.A{i:02d}", f"student answer {i}") for i in range(5)]
    questions = pd.DataFrame([{"question_id": "mohler/E01.Q01", "question": "q", "student_answers": pool}])
    config = {"course": COURSE, "samples_per_question": {"rewrite": 2}, "decoding": {}, "generators": []}
    generate.run(config, questions, tmp_path, go=True)

    records = [json.loads(line) for line in (tmp_path / "answers.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [r["source_answer_id"] for r in records] == [pool[i][0] for i in range(4)]
    assert prompts == {"g1": [pool[0][1], pool[1][1]], "g2": [pool[2][1], pool[3][1]]}


def test_plan_warns_when_a_question_is_short_of_answers(tmp_path, caplog):
    config = {
        "course": COURSE,
        "samples_per_question": {"rewrite": 2}, "decoding": {},
        "generators": [{"name": "g1"}, {"name": "g2"}],
    }

    def plan(pool_size):
        pool = [(f"mohler/E01.Q01.A{i:02d}", f"answer {i}") for i in range(pool_size)]
        questions = pd.DataFrame([{"question_id": "mohler/E01.Q01", "question": "q", "student_answers": pool}])
        caplog.clear()
        with caplog.at_level(logging.WARNING, logger="harness.generate"):
            generate.run(config, questions, tmp_path / "out", go=False)
        return caplog.text

    # two generators with two rewrites each need four answers
    assert "1 questions have fewer student answers than rewrite calls" in plan(3)
    assert "fewer student answers" not in plan(4)


def test_slots_wrap_when_a_question_is_short_of_answers():
    row = {"student_answers": [("a", "1"), ("b", "2"), ("c", "3")]}
    assert generate.pick_student_answer(row, position=1, count=2, seq=2) == ("a", "1")


@pytest.mark.parametrize("tiers", [{"correct": 1}, {"rewrite": 1}])
def test_question_with_no_student_answer_fails_at_plan_time(tmp_path, tiers):
    questions = pd.DataFrame([
        {"question_id": "mohler/E01.Q01", "question": "q", "student_answers": POOL},
        {"question_id": "mohler/E01.Q02", "question": "q", "student_answers": []},
    ])
    config = {"course": COURSE, "samples_per_question": tiers, "decoding": {}, "generators": []}
    with pytest.raises(SystemExit, match="no student answers"):
        generate.run(config, questions, tmp_path / "out", go=False)


def test_rewrite_tier_feeds_student_answer_into_prompt(tmp_path, monkeypatch):
    prompts = []
    systems = []

    class CapturingClient:
        def generate(self, system, user, decoding):
            prompts.append(user)
            systems.append(system)
            return GenerationResult(
                text="rewritten", model_version="fake-1",
                params_honoured=decoding, usage={"prompt_tokens": 1, "completion_tokens": 1},
            )

    monkeypatch.setattr(generate, "build_clients", lambda config: {"fake": CapturingClient()})
    questions = pd.DataFrame([
        {"question_id": "mohler/E01.Q01", "question": "What is a stack?",
         "student_answers": [("mohler/E01.Q01.A00", "a stack is last in first out")]},
    ])
    config = {
        "course": COURSE,
        "samples_per_question": {"rewrite": 1},
        "decoding": {"temperature": 0.8, "max_tokens": 400},
        "generators": [],
    }
    generate.run(config, questions, tmp_path, go=True)

    assert prompts[0] == "a stack is last in first out"
    # the editor persona replaces the student one for this template
    assert systems[0].startswith("You are a helpful writing assistant")
    record = json.loads((tmp_path / "answers.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert record["tier"] == "rewrite"
    assert record["prompt_template"] == "rewrite_human_v1"
    assert record["source_answer_id"] == "mohler/E01.Q01.A00"


def test_question_file_without_student_answers_fails_at_plan_time(tmp_path):
    questions = pd.DataFrame([
        {"question_id": "mohler/E01.Q01", "question": "q"},
    ])
    config = {"course": COURSE, "samples_per_question": {"correct": 1}, "decoding": {}, "generators": []}
    with pytest.raises(SystemExit, match="needs student answers"):
        generate.run(config, questions, tmp_path / "out", go=False)


@pytest.mark.parametrize("course", ["absent", None, ""])
def test_missing_course_fails_at_plan_time(tmp_path, course):
    questions = pd.DataFrame([{"question_id": "mohler/E01.Q01", "question": "q", "student_answers": POOL}])
    config = {"samples_per_question": {"correct": 1}, "decoding": {}, "generators": []}
    if course != "absent":
        config["course"] = course
    with pytest.raises(SystemExit, match="course"):
        generate.run(config, questions, tmp_path / "out", go=False)
    assert not (tmp_path / "out").exists()


def test_unknown_tier_fails_at_plan_time(tmp_path):
    questions = pd.DataFrame([
        {"question_id": "mohler/E01.Q01", "question": "q", "student_answers": POOL},
    ])
    config = {
        "course": COURSE,
        "samples_per_question": {"weak": 1, "sarcastic": 1},
        "decoding": {},
        "generators": [],
    }
    with pytest.raises(SystemExit, match="sarcastic"):
        generate.run(config, questions, tmp_path / "out", go=False)
    assert not (tmp_path / "out").exists()
    


@pytest.mark.parametrize("stale", [{"prompt_template": "weak_v1"}, {"course": "another course"}])
def test_resume_refuses_answers_from_other_prompts(tmp_path, stale):
    record = {"answer_id": "mohler/E01.Q01/g1/weak/01", "question_id": "mohler/E01.Q01", "generator": "g1",
              "tier": "weak", "prompt_template": "weak_v3", "course": COURSE, "answer": "an answer",
              "usage": {"prompt_tokens": 1, "completion_tokens": 1}, **stale}
    (tmp_path / "answers.jsonl").write_text(json.dumps(record) + "\n", encoding="utf-8")
    questions = pd.DataFrame([{"question_id": "mohler/E01.Q01", "question": "q", "student_answers": POOL}])
    config = {"course": COURSE, "samples_per_question": {"weak": 1}, "decoding": {}, "generators": [{"name": "g1"}]}
    with pytest.raises(SystemExit, match="came from other prompts"):
        generate.run(config, questions, tmp_path, go=False)


def test_word_target_counts_the_cleaned_text():
    # four words, but <br> tags would add three "br" words to a raw count
    row = {"student_answers": [("mohler/E01.Q01.A00", "one<br>two<br>three<br>four")]}
    assert generate.pick_target_words(row, "mohler/E01.Q01/fake/correct/01") == 4


def test_resume_refuses_other_prompts_even_outside_the_plan(tmp_path):
    record = {"answer_id": "sprag/PythonQ057/g1/weak/01", "question_id": "sprag/PythonQ057", "generator": "g1",
              "tier": "weak", "prompt_template": "weak_v1", "course": COURSE, "answer": "an answer",
              "usage": {"prompt_tokens": 1, "completion_tokens": 1}}
    (tmp_path / "answers.jsonl").write_text(json.dumps(record) + "\n", encoding="utf-8")
    questions = pd.DataFrame([{"question_id": "mohler/E01.Q01", "question": "q", "student_answers": POOL}])
    config = {"course": COURSE, "samples_per_question": {"weak": 1}, "decoding": {}, "generators": [{"name": "g1"}]}
    with pytest.raises(SystemExit, match="came from other prompts"):
        generate.run(config, questions, tmp_path, go=False)


def test_resume_refuses_a_folder_from_another_dataset(tmp_path):
    from harness.prompts import TIER_TO_TEMPLATE

    record = {"answer_id": "mohler/E01.Q01/g1/weak/01", "question_id": "mohler/E01.Q01", "generator": "g1",
              "tier": "weak", "prompt_template": TIER_TO_TEMPLATE["weak"], "course": COURSE, "answer": "an answer",
              "usage": {"prompt_tokens": 1, "completion_tokens": 1}}
    (tmp_path / "answers.jsonl").write_text(json.dumps(record) + "\n", encoding="utf-8")
    questions = pd.DataFrame([{"question_id": "sprag/PythonQ057", "question": "q", "student_answers": POOL}])
    config = {"course": COURSE, "samples_per_question": {"weak": 1}, "decoding": {}, "generators": [{"name": "g1"}]}
    with pytest.raises(SystemExit, match="another dataset"):
        generate.run(config, questions, tmp_path, go=False)


def test_resume_accepts_rewrite_records_without_a_course(tmp_path):
    record = {"answer_id": "mohler/E01.Q01/g1/rewrite/01", "question_id": "mohler/E01.Q01", "generator": "g1",
              "tier": "rewrite", "prompt_template": "rewrite_human_v1", "source_answer_id": "mohler/E01.Q01.A00",
              "answer": "a polished answer", "usage": {"prompt_tokens": 1, "completion_tokens": 1}}
    (tmp_path / "answers.jsonl").write_text(json.dumps(record) + "\n", encoding="utf-8")
    questions = pd.DataFrame([{"question_id": "mohler/E01.Q01", "question": "q", "student_answers": POOL}])
    config = {"course": COURSE, "samples_per_question": {"rewrite": 1}, "decoding": {}, "generators": [{"name": "g1"}]}
    generate.run(config, questions, tmp_path, go=False)


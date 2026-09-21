import json

import pandas as pd
import pytest

from harness import generate
from harness.clients import GenerationResult


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
        "instructor_answer": ["a", "a", "b"],
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
        "Reference Answer": ["a", "a"],
        "StudentAnswer": ["s1", "s2"],
    })
    path = tmp_path / "sprag.parquet"
    df.to_parquet(path)
    questions = generate.load_questions(path, "sprag")
    assert list(questions["question_id"]) == ["sprag/PythonQ057"]
    assert list(questions.columns) == [
        "question_id", "question", "instructor_answer", "student_answer", "source_answer_id",
    ]
    assert list(questions["source_answer_id"]) == ["sprag/PythonQ057.A0"]


def test_run_writes_records_and_report(tmp_path, monkeypatch):
    monkeypatch.setattr(generate, "build_clients", lambda config: {"fake": FakeClient()})
    questions = pd.DataFrame([
        {"question_id": "mohler/E01.Q01", "question": "What is a stack?", "instructor_answer": "LIFO"},
    ])
    config = {
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
        {"question_id": "mohler/E01.Q01", "question": "What is a stack?", "instructor_answer": "LIFO"},
    ])
    config = {
        "samples_per_question": {"wrong": 1},
        "decoding": {"temperature": 0.8, "max_tokens": 400},
        "generators": [],
    }
    generate.run(config, questions, tmp_path, go=True)

    assert (tmp_path / "answers.jsonl").read_text(encoding="utf-8") == ""
    report = json.loads((tmp_path / "run_report.json").read_text(encoding="utf-8"))
    assert report["fake"] == {"requested": 1, "succeeded": 0, "failed": 1, "prompt_tokens": 10, "completion_tokens": 400}


def test_dry_run_writes_nothing(tmp_path):
    questions = pd.DataFrame([
        {"question_id": "mohler/E01.Q01", "question": "q", "instructor_answer": "a"},
    ])
    config = {"samples_per_question": {"weak": 1}, "decoding": {}, "generators": []}
    generate.run(config, questions, tmp_path / "out", go=False)
    assert not (tmp_path / "out").exists()


def test_every_tier_maps_to_a_real_template():
    from harness.prompts import TEMPLATES, TIER_TO_TEMPLATE

    assert set(TIER_TO_TEMPLATE.values()) <= set(TEMPLATES)


def test_every_template_formats_with_the_run_keys():
    from harness.prompts import TEMPLATES

    for template in TEMPLATES.values():
        template.format(question="q", instructor_answer="a", student_answer="s")


def test_questions_flag_rejects_zero_and_negatives():
    import argparse

    assert generate.positive_int("2") == 2
    for value in ("0", "-3"):
        with pytest.raises(argparse.ArgumentTypeError):
            generate.positive_int(value)


def test_load_questions_keeps_first_student_answer(tmp_path):
    df = pd.DataFrame({
        "id": ["E01.Q01.A00", "E01.Q01.A01"],
        "question": ["q1", "q1"],
        "instructor_answer": ["a", "a"],
        "student_answer": ["first answer", "second answer"],
    })
    path = tmp_path / "corpus.parquet"
    df.to_parquet(path)
    questions = generate.load_questions(path, "mohler")
    assert list(questions["student_answer"]) == ["first answer"]
    assert list(questions["source_answer_id"]) == ["mohler/E01.Q01.A00"]


def test_rewrite_tier_feeds_student_answer_into_prompt(tmp_path, monkeypatch):
    prompts = []

    class CapturingClient:
        def generate(self, system, user, decoding):
            prompts.append(user)
            return GenerationResult(
                text="rewritten", model_version="fake-1",
                params_honoured=decoding, usage={"prompt_tokens": 1, "completion_tokens": 1},
            )

    monkeypatch.setattr(generate, "build_clients", lambda config: {"fake": CapturingClient()})
    questions = pd.DataFrame([
        {"question_id": "mohler/E01.Q01", "question": "What is a stack?",
         "instructor_answer": "LIFO", "student_answer": "a stack is last in first out",
         "source_answer_id": "mohler/E01.Q01.A00"},
    ])
    config = {
        "samples_per_question": {"rewrite": 1},
        "decoding": {"temperature": 0.8, "max_tokens": 400},
        "generators": [],
    }
    generate.run(config, questions, tmp_path, go=True)

    assert "a stack is last in first out" in prompts[0]
    record = json.loads((tmp_path / "answers.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert record["tier"] == "rewrite"
    assert record["prompt_template"] == "rewrite_human_v1"
    assert record["source_answer_id"] == "mohler/E01.Q01.A00"


def test_rewrite_tier_without_student_answers_fails_at_plan_time(tmp_path):
    questions = pd.DataFrame([
        {"question_id": "mohler/E01.Q01", "question": "q", "instructor_answer": "a"},
    ])
    config = {"samples_per_question": {"rewrite": 1}, "decoding": {}, "generators": []}
    with pytest.raises(SystemExit, match="student_answer"):
        generate.run(config, questions, tmp_path / "out", go=False)


def test_student_answer_guard_follows_template_overrides(tmp_path):
    questions = pd.DataFrame([
        {"question_id": "mohler/E01.Q01", "question": "q", "instructor_answer": "a"},
    ])
    config = {
        "samples_per_question": {"weak": 1},
        "template_overrides": {"weak": "rewrite_human_v1"},
        "decoding": {},
        "generators": [],
    }
    with pytest.raises(SystemExit, match="student_answer"):
        generate.run(config, questions, tmp_path / "out", go=False)


def test_bad_tier_config_fails_at_plan_time(tmp_path):
    questions = pd.DataFrame([
        {"question_id": "mohler/E01.Q01", "question": "q", "instructor_answer": "a"},
    ])
    config = {
        "samples_per_question": {"weak": 1, "sarcastic": 1},
        "template_overrides": {"weak": "missing_v9"},
        "decoding": {},
        "generators": [],
    }
    with pytest.raises(SystemExit, match="sarcastic.*missing_v9"):
        generate.run(config, questions, tmp_path / "out", go=False)
    assert not (tmp_path / "out").exists()
    
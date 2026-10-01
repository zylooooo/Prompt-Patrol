import json

import pytest

from splicer.splice import is_eligible, make_rng, splice_pair

HUMAN = [
    "A stack stores elements in last in first out order.",
    "Push adds an element to the top.",
    "Pop removes the element at the top.",
    "Peek returns the top without removing it.",
]
AI = [
    "A stack is a linear data structure following the LIFO principle.",
    "Insertion and removal both happen at the top of the stack.",
    "This makes access to older elements impossible without removal.",
]


def test_splice_labels_and_fraction():
    labelled, fraction = splice_pair(HUMAN, AI, 0.5, make_rng(1))
    assert len(labelled) == 4
    assert sum(1 for s in labelled if s["label"] == "ai") == 2
    assert fraction == 0.5
    assert all(s["label"] in ("human", "ai") for s in labelled)
    assert [s["text"] for s in labelled if s["label"] == "ai"] == AI[:2]
    assert all(labelled[i]["text"] == HUMAN[i] for i in range(4) if labelled[i]["label"] == "human")


def test_splice_is_deterministic():
    first = splice_pair(HUMAN, AI, 0.25, make_rng(7))
    second = splice_pair(HUMAN, AI, 0.25, make_rng(7))
    assert first == second


def test_always_mixed_even_at_extreme_fractions():
    labelled, fraction = splice_pair(HUMAN, AI, 0.9, make_rng(1))
    labels = {s["label"] for s in labelled}
    assert labels == {"human", "ai"}
    assert 0 < fraction < 1


def test_too_short_ai_answer_is_rejected():
    assert splice_pair(HUMAN, AI[:1], 0.75, make_rng(1)) is None


def test_single_sentence_human_is_rejected():
    assert splice_pair(HUMAN[:1], AI, 0.5, make_rng(1)) is None


def test_eligibility_rejects_benchmark_failures():
    pytest.importorskip("en_core_web_sm")  # only the segmentation cases need the spacy model
    from splicer.segment import segment

    code_answer = segment("1. Declare the length of the array (int array[10];)")
    notation_list = segment("log(logn)<br>2^(logn)<br>n!<br>n^3<br>n^2")
    assert not is_eligible(code_answer, 2)
    assert not is_eligible(notation_list, 2)
    assert is_eligible(HUMAN, 2)


def test_build_corpus_records_both_sources():
    from splicer.build_spliced import build_corpus

    humans = {"mohler/E01.Q01": [{"question_id": "mohler/E01.Q01", "answer_id": "mohler/E01.Q01.A00", "sentences": HUMAN}]}
    ais = {"mohler/E01.Q01": [{"answer_id": "mohler/E01.Q01/fake/weak/01", "sentences": AI}]}
    config = {"dataset": "mohler", "target_fractions": [0.5], "docs_per_fraction": 5}
    records = build_corpus(humans, ais, config, make_rng(3))

    assert len(records) == 1
    record = records[0]
    assert record["doc_id"] == "spliced/mohler/f50/0000"
    assert record["human_answer_id"] == "mohler/E01.Q01.A00"
    assert record["ai_answer_id"] == "mohler/E01.Q01/fake/weak/01"
    assert record["ai_fraction"] == 0.5
    assert {s["label"] for s in record["sentences"]} == {"human", "ai"}


def test_load_ai_answers_skips_every_rewrite(tmp_path):
    pytest.importorskip("en_core_web_sm")
    from splicer.build_spliced import load_ai_answers

    own = {
        "answer_id": "mohler/E01.Q01/fake/weak/01", "question_id": "mohler/E01.Q01",
        "tier": "weak", "answer": " ".join(AI),
    }
    rewrite = {
        "answer_id": "mohler/E01.Q01/fake/rewrite/01", "question_id": "mohler/E01.Q01",
        "tier": "rewrite", "answer": " ".join(HUMAN), "source_answer_id": "mohler/E01.Q01.A00",
    }
    path = tmp_path / "answers.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in [own, rewrite]), encoding="utf-8")

    grouped = load_ai_answers(path)
    assert [a["answer_id"] for a in grouped["mohler/E01.Q01"]] == ["mohler/E01.Q01/fake/weak/01"]


def test_a_run_of_only_rewrites_stops_before_writing(tmp_path, monkeypatch):
    from splicer import build_spliced

    run = tmp_path / "answers.jsonl"
    run.write_text(json.dumps({
        "answer_id": "mohler/E01.Q01/fake/rewrite/01", "question_id": "mohler/E01.Q01",
        "tier": "rewrite", "answer": " ".join(HUMAN), "source_answer_id": "mohler/E01.Q01.A00",
    }) + "\n", encoding="utf-8")
    config = tmp_path / "config.yaml"
    config.write_text(
        "human_corpus: human.parquet\ndataset: mohler\nai_answers: answers.jsonl\nout_dir: spliced\n"
        "seed: 1\ntarget_fractions: [0.5]\ndocs_per_fraction: 5\nmin_sentences: 2\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(build_spliced, "PIPELINE_DIR", tmp_path)
    monkeypatch.setattr(build_spliced, "DEFAULT_CONFIG", config)
    monkeypatch.setattr("sys.argv", ["build_spliced"])
    with pytest.raises(SystemExit, match="nothing to splice"):
        build_spliced.main()
    assert not (tmp_path / "spliced").exists()


def test_a_build_with_no_documents_keeps_the_previous_file(tmp_path, monkeypatch):
    pytest.importorskip("en_core_web_sm")
    from splicer import build_spliced

    (tmp_path / "answers.jsonl").write_text(json.dumps({
        "answer_id": "mohler/E01.Q01/fake/weak/01", "question_id": "mohler/E01.Q01",
        "tier": "weak", "answer": " ".join(AI),
    }) + "\n", encoding="utf-8")
    config = tmp_path / "config.yaml"
    config.write_text(
        "human_corpus: human.parquet\ndataset: mohler\nai_answers: answers.jsonl\nout_dir: spliced\n"
        "seed: 1\ntarget_fractions: [0.5]\ndocs_per_fraction: 5\nmin_sentences: 2\n",
        encoding="utf-8",
    )
    previous = tmp_path / "spliced" / "spliced_mohler.jsonl"
    previous.parent.mkdir()
    previous.write_text("earlier build\n", encoding="utf-8")
    # human answers to a different question, so no pair can be built
    humans = {"mohler/E09.Q09": [{"question_id": "mohler/E09.Q09", "answer_id": "mohler/E09.Q09.A00", "sentences": HUMAN}]}
    monkeypatch.setattr(build_spliced, "load_human_answers", lambda path, min_sentences, namespace: humans)
    monkeypatch.setattr(build_spliced, "PIPELINE_DIR", tmp_path)
    monkeypatch.setattr(build_spliced, "DEFAULT_CONFIG", config)
    monkeypatch.setattr("sys.argv", ["build_spliced"])
    with pytest.raises(SystemExit, match="no documents built"):
        build_spliced.main()
    assert previous.read_text(encoding="utf-8") == "earlier build\n"

import pytest

pytest.importorskip("en_core_web_sm")

from splicer.segment import segment
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


def test_eligibility_rejects_benchmark_failures():
    code_answer = segment("1. Declare the length of the array (int array[10];)")
    notation_list = segment("log(logn)<br>2^(logn)<br>n!<br>n^3<br>n^2")
    assert not is_eligible(code_answer, 2)
    assert not is_eligible(notation_list, 2)
    assert is_eligible(HUMAN, 2)


def test_build_corpus_records_both_sources():
    from splicer.build_spliced import build_corpus

    humans = {"mohler/E01.Q01": [{"question_id": "mohler/E01.Q01", "answer_id": "mohler/E01.Q01.A00", "sentences": HUMAN}]}
    ais = {"mohler/E01.Q01": [{"answer_id": "mohler/E01.Q01/fake/weak/01", "sentences": AI}]}
    config = {"target_fractions": [0.5], "docs_per_fraction": 5}
    records = build_corpus(humans, ais, config, make_rng(3))

    assert len(records) == 1
    record = records[0]
    assert record["human_answer_id"] == "mohler/E01.Q01.A00"
    assert record["ai_answer_id"] == "mohler/E01.Q01/fake/weak/01"
    assert record["ai_fraction"] == 0.5
    assert {s["label"] for s in record["sentences"]} == {"human", "ai"}
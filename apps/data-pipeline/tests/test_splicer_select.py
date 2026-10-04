import random

from splicer.select import select


def pool(spec):
    """Candidates from (model, base_id, donor_id) triples."""
    return [{"model": m, "base_id": b, "donor_id": d} for m, b, d in spec]


def test_select_fills_every_model_to_its_count():
    candidates = pool([(m, f"b{i}", f"{m}d{i}") for m in ("m1", "m2") for i in range(10)])
    chosen, counts = select(candidates, ["m1", "m2"], 4, 2, random.Random(1))
    assert counts == {"m1": 4, "m2": 4} and len(chosen) == 8


def test_select_never_uses_a_base_more_than_the_cap():
    candidates = pool([(m, "b0", f"{m}d{i}") for m in ("m1", "m2") for i in range(5)] + [("m1", "b1", "x")])
    chosen, _ = select(candidates, ["m1", "m2"], 3, 2, random.Random(1))
    assert sum(c["base_id"] == "b0" for c in chosen) <= 2


def test_select_finds_a_selection_a_greedy_pick_could_miss():
    # taking b0 for m1 first would starve m2, which can only use b0
    candidates = pool([("m1", "b0", "d1"), ("m1", "b1", "d2"), ("m2", "b0", "d3")])
    for seed in range(20):
        _, counts = select(candidates, ["m1", "m2"], 1, 1, random.Random(seed))
        assert counts == {"m1": 1, "m2": 1}


def test_select_reports_a_model_it_cannot_fill():
    candidates = pool([("m1", "b0", "d1"), ("m2", "b0", "d2")])
    _, counts = select(candidates, ["m1", "m2"], 1, 1, random.Random(1))
    assert sorted(counts.values()) == [0, 1]


def test_select_counts_a_model_without_candidates_as_zero():
    _, counts = select(pool([("m1", "b0", "d")]), ["m1", "m2"], 1, 1, random.Random(1))
    assert counts == {"m1": 1, "m2": 0}


def test_select_is_seeded():
    candidates = pool([(m, f"b{i}", f"{m}d{i}") for m in ("m1", "m2") for i in range(30)])

    def picked(seed):
        chosen, _ = select(candidates, ["m1", "m2"], 5, 2, random.Random(seed))
        return sorted((c["model"], c["base_id"]) for c in chosen)

    assert picked(3) == picked(3)
    assert picked(3) != picked(4)

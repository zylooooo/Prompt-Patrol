import hashlib
import json
from datetime import datetime, timedelta

import pandas as pd
import pytest
import spacy
import yaml

from harness.generate import count_words
from splicer import build_spliced
from splicer.splice import ai_share, band_candidates, band_of, is_eligible, make_rng, position_sets, splice_at

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
BANDS = {25: (0.15, 0.35), 50: (0.40, 0.60), 75: (0.65, 0.85)}
# a 7-word and a 13-word sentence, so a 3, 9 or 26-word donor sentence
# lands in band 25, 50 or 75 whichever student sentence it replaces
BASE = ["Student one wrote the first part here.", "Then the student added a longer second part with more words in it."]
SHORT = ["Stacks are LIFO."]
MID = ["A stack removes the most recently added item first."]
LONG = ["A stack is a last in first out structure where push adds an item to the top and pop "
        "removes the item from the top again."]
REQUIRED = {"answer", "label", "partition", "question_id", "answer_id", "generator", "n_words"}
CONFIG = {"partitions": ["test"], "seed": 1, "bands": {25: [0.15, 0.35], 50: [0.40, 0.60], 75: [0.65, 0.85]},
          "answers_per_band": 8, "max_base_uses": 2, "min_sentences": 2}


def test_splice_at_replaces_positions_in_order_with_the_donor_prefix():
    labelled = splice_at(HUMAN, AI, (1, 3))
    assert [s["label"] for s in labelled] == ["human", "ai", "human", "ai"]
    assert [s["text"] for s in labelled] == [HUMAN[0], AI[0], HUMAN[2], AI[1]]


def test_ai_share_counts_words_by_the_corpus_rule():
    # count_words reads "min(),max(),len()" as three words
    labelled = [{"text": "one two three", "label": "ai"}, {"text": "min(),max(),len()", "label": "human"}]
    assert ai_share(labelled) == 0.5


@pytest.mark.parametrize("share, band", [
    (0.15, 25), (0.35, 25), (0.36, None), (0.40, 50), (0.5, 50), (0.85, 75), (0.86, None), (0.1, None),
])
def test_band_of_uses_closed_ranges(share, band):
    assert band_of(share, BANDS) == band


def test_position_sets_lists_every_set_when_few():
    assert position_sets(4, 2, make_rng(1), 200) == [(0, 1), (0, 2), (0, 3), (1, 2), (1, 3), (2, 3)]


def test_position_sets_draws_a_seeded_capped_sample_when_many():
    first = position_sets(32, 3, make_rng(5), 200)
    assert len(first) == 200 and len(set(first)) == 200
    assert all(len(p) == 3 and list(p) == sorted(p) for p in first)
    assert first == position_sets(32, 3, make_rng(5), 200)


def test_band_candidates_reach_the_band_the_word_share_falls_in():
    assert set(band_candidates("b", BASE, "d", SHORT, BANDS, 1, 200)) == {25}
    assert set(band_candidates("b", BASE, "d", MID, BANDS, 1, 200)) == {50}
    assert set(band_candidates("b", BASE, "d", LONG, BANDS, 1, 200)) == {75}


def test_band_candidates_record_the_splice_and_its_share():
    positions, labelled, share = band_candidates("b", BASE, "d", MID, BANDS, 1, 200)[50]
    assert share == ai_share(labelled)
    assert [i for i, s in enumerate(labelled) if s["label"] == "ai"] == list(positions)


def test_band_candidates_do_not_depend_on_the_order_pairs_are_visited():
    first = band_candidates("b", BASE, "d", MID, BANDS, 7, 200)
    band_candidates("x", BASE, "y", LONG, BANDS, 7, 200)
    assert band_candidates("b", BASE, "d", MID, BANDS, 7, 200) == first


def test_band_candidates_always_keep_a_student_sentence():
    for _, labelled, _ in band_candidates("b", BASE, "d", MID + LONG, BANDS, 1, 200).values():
        assert {s["label"] for s in labelled} == {"human", "ai"}


def test_band_candidates_leave_a_band_reaching_one_empty_for_two_sentence_answers():
    # a full replacement would share 1.0, so only the n - 1 limit keeps it out of this band
    assert band_candidates("b", BASE, "d", MID + SHORT, {100: (0.9, 1.0)}, 1, 200) == {}


def test_band_candidates_reach_two_replaced_sentences_with_a_two_sentence_donor():
    base = BASE + ["That is everything the student knew."]
    donor = ["Stacks are LIFO.", "Push adds an item to the top and pop removes the item from it."]
    positions, labelled, share = band_candidates("b", base, "d", donor, BANDS, 1, 200)[75]
    assert len(positions) == 2
    assert share == ai_share(labelled)
    assert [s["label"] for s in labelled].count("ai") == 2


def test_eligibility_rejects_benchmark_failures():
    pytest.importorskip("en_core_web_sm")  # only the segmentation cases need the spacy model
    from splicer.segment import segment

    code_answer = segment("1. Declare the length of the array (int array[10];)")
    notation_list = segment("log(logn)<br>2^(logn)<br>n!<br>n^3<br>n^2")
    assert not is_eligible(code_answer, 2)
    assert not is_eligible(notation_list, 2)
    assert is_eligible(HUMAN, 2)


def tiny_corpus(models=("m1", "m2"), questions=3, students=6):
    """Three partitions of a made-up dataset d. Every student answer is a
    7-word and a 13-word sentence, and each model answers every question
    with one short, one mid and one long sentence, which land in band 25,
    50 and 75 whichever student sentence they replace."""
    donors = {"short": SHORT[0], "mid": MID[0], "long": LONG[0]}
    rows, partitions = [], {}
    for partition in ("train", "val", "test"):
        for q in range(questions):
            qid = f"d/{partition}{q}"
            partitions[qid] = partition
            for s in range(students):
                rows.append({"answer": f"Student {partition}{q}s{s} wrote the first part here. {BASE[1]}",
                             "label": 0, "partition": partition, "question_id": qid, "answer_id": f"{qid}.A{s}",
                             "generator": "human", "dataset": "d", "tier": None})
            for model in models:
                for tier, text in donors.items():
                    rows.append({"answer": text, "label": 1, "partition": partition, "question_id": qid,
                                 "answer_id": f"{qid}/{model}/{tier}/01", "generator": model, "dataset": "d",
                                 "tier": tier})
    corpus = pd.DataFrame(rows)
    corpus["n_words"] = corpus["answer"].map(count_words)
    return corpus, {"version": "v9", "text_cleaning": "clean_v2", "question_partitions": partitions}


def split_sentences(text):
    """A stand-in for spaCy: every full stop followed by a space ends a sentence."""
    return [part if part.endswith(".") else part + "." for part in text.split(". ")]


@pytest.fixture
def plain_segment(monkeypatch):
    monkeypatch.setattr(build_spliced, "segment", split_sentences)


def test_build_gives_every_model_its_count_in_every_band(plain_segment):
    corpus, manifest = tiny_corpus()
    spliced, stats = build_spliced.build(corpus, manifest, CONFIG)
    counts = spliced.groupby(["style", "generator"]).size().to_dict()
    assert counts == {(f"spliced-{b}", m): 4 for b in (25, 50, 75) for m in ("m1", "m2")}
    assert stats["answers_per_model"] == {"test": {"d": 4}}


def two_datasets():
    """tiny_corpus with a second dataset e, a copy of d under its own ids."""
    corpus, manifest = tiny_corpus()
    copy = corpus.assign(dataset="e")
    for column in ("question_id", "answer_id"):
        copy[column] = copy[column].str.replace(r"^d/", "e/", regex=True)
    partitions = manifest["question_partitions"]
    partitions = partitions | {"e/" + q.removeprefix("d/"): p for q, p in partitions.items()}
    return pd.concat([corpus, copy], ignore_index=True), manifest | {"question_partitions": partitions}


def test_counts_can_differ_by_partition(plain_segment):
    corpus, manifest = tiny_corpus()
    config = CONFIG | {"partitions": ["train", "test"], "answers_per_band": {"train": 4, "test": 8}}
    spliced, stats = build_spliced.build(corpus, manifest, config)
    counts = spliced.groupby(["partition", "style", "generator"]).size()
    assert set(counts["train"]) == {2} and set(counts["test"]) == {4}
    assert stats["answers_per_model"] == {"train": {"d": 2}, "test": {"d": 4}}


def test_counts_can_differ_by_dataset(plain_segment):
    corpus, manifest = two_datasets()
    config = CONFIG | {"answers_per_band": {"test": {"d": 8, "e": 4}}}
    spliced, stats = build_spliced.build(corpus, manifest, config)
    counts = spliced.groupby(["dataset", "style", "generator"]).size()
    assert set(counts["d"]) == {4} and set(counts["e"]) == {2}
    assert stats["answers_per_model"] == {"test": {"d": 4, "e": 2}}
    assert set(stats["eligible"]["test"]) == set(stats["candidates"]["test"]) == {"d", "e"}
    assert spliced["answer_id"].str.startswith("spliced/test/e/").sum() == 12


def test_a_dataset_missing_from_a_partition_is_skipped(plain_segment):
    corpus, manifest = two_datasets()
    corpus = corpus[~((corpus["dataset"] == "e") & (corpus["partition"] == "train"))]
    config = CONFIG | {"partitions": ["train", "test"], "answers_per_band": 8}
    spliced, stats = build_spliced.build(corpus, manifest, config)
    assert stats["answers_per_model"] == {"train": {"d": 4}, "test": {"d": 4, "e": 4}}
    assert set(spliced.loc[spliced["partition"] == "train", "dataset"]) == {"d"}


def test_the_selection_is_pinned(plain_segment):
    # a change to how answers are drawn changes this hash, and with it the published test rows
    corpus, manifest = tiny_corpus()
    spliced, _ = build_spliced.build(corpus, manifest, CONFIG)
    # a fixed line ending, since to_csv defaults to the platform's
    key = spliced[["answer_id", "human_answer_id", "ai_answer_id", "ai_fraction"]].to_csv(index=False, lineterminator="\n")
    pinned = "a59b0de5818e63568473d6d4806a4ee5666107075cc70220957c14f941dd828f"
    assert hashlib.sha256(key.encode()).hexdigest() == pinned


def test_adding_partitions_leaves_the_test_rows_unchanged(plain_segment):
    corpus, manifest = tiny_corpus()
    alone, _ = build_spliced.build(corpus, manifest, CONFIG)
    config = CONFIG | {"partitions": ["train", "val", "test"], "answers_per_band": {"train": 4, "val": 2, "test": 8}}
    every, _ = build_spliced.build(corpus, manifest, config)
    assert set(every["partition"]) == {"train", "val", "test"}
    pd.testing.assert_frame_equal(every[every["partition"] == "test"].reset_index(drop=True), alone)


def test_listing_test_splices_test_only_from_test_rows(plain_segment):
    corpus, manifest = tiny_corpus()
    spliced, _ = build_spliced.build(corpus, manifest, CONFIG)
    assert set(spliced["partition"]) == {"test"}
    for column in ("question_id", "human_answer_id", "ai_answer_id"):
        assert spliced[column].str.startswith("d/test").all()


def test_listing_train_splices_train_only_from_train_rows(plain_segment):
    corpus, manifest = tiny_corpus()
    spliced, _ = build_spliced.build(corpus, manifest, CONFIG | {"partitions": ["train"]})
    for column in ("question_id", "human_answer_id", "ai_answer_id"):
        assert spliced[column].str.startswith("d/train").all()
    assert spliced["answer_id"].str.startswith("spliced/train/d/").all()


def test_build_output_has_the_corpus_columns_and_extras(plain_segment):
    corpus, manifest = tiny_corpus()
    spliced, _ = build_spliced.build(corpus, manifest, CONFIG)
    assert list(spliced.columns) == build_spliced.COLUMNS
    assert REQUIRED <= set(spliced.columns)
    assert (spliced["label"] == 1).all()
    assert spliced["answer_id"].is_unique
    assert not spliced["answer_id"].isin(corpus["answer_id"]).any()
    assert spliced["answer_id"].str.match(r"^spliced/test/d/b(25|50|75)/\d{4}$").all()
    for positions, n in zip(spliced["ai_positions"], spliced["n_sentences"], strict=True):
        assert 0 < len(positions) < n and all(0 <= p < n for p in positions)


def test_build_counts_the_words_and_sentences_of_each_answer(plain_segment):
    corpus, manifest = tiny_corpus()
    spliced, _ = build_spliced.build(corpus, manifest, CONFIG)
    assert list(spliced["n_words"]) == [count_words(text) for text in spliced["answer"]]
    assert list(spliced["n_sentences"]) == [len(split_sentences(text)) for text in spliced["answer"]]


def test_build_copies_the_donor_model_and_tier(plain_segment):
    corpus, manifest = tiny_corpus()
    spliced, _ = build_spliced.build(corpus, manifest, CONFIG)
    donors = corpus.set_index("answer_id").loc[spliced["ai_answer_id"]]
    assert list(spliced["generator"]) == list(donors["generator"])
    assert list(spliced["tier"]) == list(donors["tier"])
    assert spliced["tier"].notna().all()


def test_build_puts_the_donor_prefix_at_the_ai_positions_and_keeps_the_rest(plain_segment):
    corpus, manifest = tiny_corpus()
    spliced, _ = build_spliced.build(corpus, manifest, CONFIG)
    text = dict(zip(corpus["answer_id"], corpus["answer"], strict=True))
    for row in spliced.itertuples():
        base, donor = split_sentences(text[row.human_answer_id]), split_sentences(text[row.ai_answer_id])
        sentences, taken = split_sentences(row.answer), list(row.ai_positions)
        assert row.n_sentences == len(base) == len(sentences)
        assert [sentences[i] for i in taken] == donor[:len(taken)]
        kept = [i for i in range(len(base)) if i not in taken]
        assert [sentences[i] for i in kept] == [base[i] for i in kept]


def test_every_share_lies_in_its_band(plain_segment):
    corpus, manifest = tiny_corpus()
    spliced, _ = build_spliced.build(corpus, manifest, CONFIG)
    for style, share in zip(spliced["style"], spliced["ai_fraction"], strict=True):
        low, high = CONFIG["bands"][int(style.removeprefix("spliced-"))]
        assert low <= share <= high


def test_build_caps_base_reuse_and_never_repeats_a_pair(plain_segment):
    corpus, manifest = tiny_corpus()
    spliced, stats = build_spliced.build(corpus, manifest, CONFIG)
    assert spliced.groupby(["style", "human_answer_id"]).size().max() <= 2
    assert not spliced.duplicated(["style", "human_answer_id", "ai_answer_id"]).any()
    assert stats["most_base_uses"] <= 2


def test_build_is_seeded(plain_segment):
    corpus, manifest = tiny_corpus()
    first, _ = build_spliced.build(corpus, manifest, CONFIG)
    again, _ = build_spliced.build(corpus, manifest, CONFIG)
    other, _ = build_spliced.build(corpus, manifest, CONFIG | {"seed": 2})
    pd.testing.assert_frame_equal(first, again)
    pairs = set(zip(first["human_answer_id"], first["ai_answer_id"], strict=True))
    assert pairs != set(zip(other["human_answer_id"], other["ai_answer_id"], strict=True))


def test_a_base_cap_that_binds_is_filled_by_reusing_bases_up_to_it(plain_segment):
    # two students per question leave six bases for eight answers in a band
    corpus, manifest = tiny_corpus(students=2)
    spliced, stats = build_spliced.build(corpus, manifest, CONFIG)
    assert spliced.groupby(["style", "human_answer_id"]).size().max() == 2
    assert stats["most_base_uses"] == 2


def test_a_base_cap_below_what_the_band_needs_stops_the_build_naming_the_group(plain_segment):
    corpus, manifest = tiny_corpus(students=2)
    with pytest.raises(SystemExit, match=r"test d band 25 cannot reach 4 per model"):
        build_spliced.build(corpus, manifest, CONFIG | {"max_base_uses": 1})


def test_a_base_cap_of_one_gives_each_base_one_answer_per_band(plain_segment):
    corpus, manifest = tiny_corpus()
    spliced, stats = build_spliced.build(corpus, manifest, CONFIG | {"max_base_uses": 1})
    assert spliced.groupby(["style", "human_answer_id"]).size().max() == 1
    assert stats["most_base_uses"] == 1 and stats["max_base_uses"] == 1


def test_build_numbers_answers_by_model_then_base_then_donor(plain_segment):
    corpus, manifest = tiny_corpus()
    spliced, _ = build_spliced.build(corpus, manifest, CONFIG)
    for _, group in spliced.groupby(["partition", "dataset", "style"]):
        ordered = group.sort_values("answer_id")
        keys = list(zip(ordered["generator"], ordered["human_answer_id"], ordered["ai_answer_id"], strict=True))
        assert keys == sorted(keys)
        assert list(ordered["answer_id"].str[-4:].astype(int)) == list(range(len(group)))


def with_longer_students(corpus):
    """Four of every question's six students write a third sentence."""
    corpus = corpus.copy()
    longer = (corpus["label"] == 0) & corpus["answer_id"].str.contains(r"\.A[0-3]$")
    corpus.loc[longer, "answer"] += " That is everything the student knew."
    corpus["n_words"] = corpus["answer"].map(count_words)
    return corpus


def test_min_sentences_keeps_shorter_answers_from_being_bases(plain_segment):
    corpus, manifest = tiny_corpus()
    corpus = with_longer_students(corpus)
    spliced, stats = build_spliced.build(corpus, manifest, CONFIG | {"min_sentences": 3})
    assert (spliced["n_sentences"] == 3).all()
    assert stats["eligible"]["test"]["d"]["bases"] == 12 and stats["min_sentences"] == 3
    _, loose = build_spliced.build(corpus, manifest, CONFIG)
    assert loose["eligible"]["test"]["d"]["bases"] == 18


def test_build_draws_position_sets_with_the_cap_and_seed(monkeypatch, plain_segment):
    drawn = []
    real = build_spliced.band_candidates

    def spy(*args):
        drawn.append(args[-2:])
        return real(*args)

    monkeypatch.setattr(build_spliced, "band_candidates", spy)
    corpus, manifest = tiny_corpus()
    build_spliced.build(corpus, manifest, CONFIG)
    assert drawn and set(drawn) == {(CONFIG["seed"], 200)}


def test_a_group_that_cannot_be_filled_stops_the_build_naming_it(plain_segment):
    corpus, manifest = tiny_corpus()
    with pytest.raises(SystemExit, match=r"test d band 25 cannot reach 30 per model"):
        build_spliced.build(corpus, manifest, CONFIG | {"answers_per_band": 60})


@pytest.mark.parametrize("change, message", [
    ({"bands": {25: [0.15, 0.45], 50: [0.40, 0.60]}}, "overlap"),
    ({"bands": {25: [0.35, 0.15]}}, "inside 0 to 1"),
    ({"bands": {25: [0.5, 1.2]}}, "inside 0 to 1"),
    ({"answers_per_band": 7}, "does not divide"),
    ({"answers_per_band": {"test": 0}}, "0 for test d does not divide"),
    ({"answers_per_band": {"test": {"d": 7}}}, "7 for test d does not divide"),
    ({"answers_per_band": {"test": {"d": -8}}}, "-8 for test d does not divide"),
    ({"answers_per_band": 8.0}, "8.0 for test d does not divide"),
    ({"answers_per_band": True}, "True for test d does not divide"),
    ({"answers_per_band": {"train": 8}}, r"missing \['test'\], not configured \['train'\]"),
    ({"answers_per_band": {"test": 8, "train": 8}}, r"missing \[\], not configured \['train'\]"),
    ({"partitions": ["train", "test"], "answers_per_band": {"test": 8}}, r"missing \['train'\]"),
    ({"answers_per_band": {"test": {"x": 8}}}, r"for test names \['x'\], the corpus has \['d'\]"),
    ({"answers_per_band": {"test": {"d": 8, "x": 8}}}, r"for test names \['d', 'x'\], the corpus has \['d'\]"),
    ({"partitions": ["holdout"]}, r"no \['holdout'\] partition"),
])
def test_settings_the_build_cannot_honour_stop_it(change, message, plain_segment):
    corpus, manifest = tiny_corpus()
    with pytest.raises(SystemExit, match=message):
        build_spliced.build(corpus, manifest, CONFIG | change)


def built():
    corpus, manifest = tiny_corpus()
    spliced, _ = build_spliced.build(corpus, manifest, CONFIG)
    bands = build_spliced.check_config(CONFIG, corpus)[0]
    return spliced, corpus, manifest, bands


def test_the_leak_guard_stops_a_question_from_another_partition(plain_segment):
    spliced, corpus, manifest, bands = built()
    moved = manifest | {"question_partitions": manifest["question_partitions"] | {spliced["question_id"][0]: "train"}}
    with pytest.raises(SystemExit, match="outside the configured partitions"):
        build_spliced.check(spliced, corpus, moved, CONFIG, bands)


def test_check_stops_a_base_and_donor_from_different_questions(plain_segment):
    spliced, corpus, manifest, bands = built()
    other = "d/test1" if spliced.loc[0, "question_id"] != "d/test1" else "d/test0"
    spliced.loc[0, "ai_answer_id"] = f"{other}/m1/short/01"
    with pytest.raises(SystemExit, match="different questions"):
        build_spliced.check(spliced, corpus, manifest, CONFIG, bands)


def test_check_stops_text_that_cleanup_would_change(plain_segment):
    spliced, corpus, manifest, bands = built()
    spliced.loc[0, "answer"] = "It is **bold**. " + spliced.loc[0, "answer"]
    with pytest.raises(SystemExit, match="change under clean_text"):
        build_spliced.check(spliced, corpus, manifest, CONFIG, bands)


def test_the_leak_guard_stops_a_partition_that_is_not_configured_even_when_row_and_manifest_agree(plain_segment):
    spliced, corpus, manifest, bands = built()
    question = spliced.loc[0, "question_id"]
    spliced.loc[spliced["question_id"] == question, "partition"] = "train"
    moved = manifest | {"question_partitions": manifest["question_partitions"] | {question: "train"}}
    with pytest.raises(SystemExit, match="outside the configured partitions"):
        build_spliced.check(spliced, corpus, moved, CONFIG, bands)


def test_the_leak_guard_stops_a_row_filed_under_another_partition(plain_segment):
    corpus, manifest = tiny_corpus()
    config = CONFIG | {"partitions": ["test", "val"]}
    spliced, _ = build_spliced.build(corpus, manifest, config)
    bands = build_spliced.check_config(config, corpus)[0]
    assert spliced.loc[0, "partition"] == "test"
    spliced.loc[0, "partition"] = "val"  # the manifest still files its question under test
    with pytest.raises(SystemExit, match="outside the configured partitions"):
        build_spliced.check(spliced, corpus, manifest, config, bands)


@pytest.mark.parametrize("share", [0.01, 0.99])
def test_check_stops_a_share_outside_its_band(share, plain_segment):
    spliced, corpus, manifest, bands = built()
    spliced.loc[0, "ai_fraction"] = share
    with pytest.raises(SystemExit, match="ai shares outside their band"):
        build_spliced.check(spliced, corpus, manifest, CONFIG, bands)


def test_check_stops_a_base_used_more_than_the_cap_in_a_band(plain_segment):
    # six bases for eight answers in a band, so some base starts two of them
    corpus, manifest = tiny_corpus(students=2)
    spliced, _ = build_spliced.build(corpus, manifest, CONFIG)
    bands = build_spliced.check_config(CONFIG, corpus)[0]
    with pytest.raises(SystemExit, match="bases used more than 1 times in a band"):
        build_spliced.check(spliced, corpus, manifest, CONFIG | {"max_base_uses": 1}, bands)


def test_check_stops_a_base_and_donor_pair_repeated_in_a_band(plain_segment):
    spliced, corpus, manifest, bands = built()
    pair = ["question_id", "human_answer_id", "ai_answer_id"]
    assert spliced.loc[0, "style"] == spliced.loc[1, "style"]
    spliced.loc[1, pair] = spliced.loc[0, pair].to_numpy()
    with pytest.raises(SystemExit, match="pair repeats within a band"):
        build_spliced.check(spliced, corpus, manifest, CONFIG, bands)


def test_check_stops_a_spliced_id_that_repeats(plain_segment):
    spliced, corpus, manifest, bands = built()
    spliced.loc[1, "answer_id"] = spliced.loc[0, "answer_id"]
    with pytest.raises(SystemExit, match="repeat or collide"):
        build_spliced.check(spliced, corpus, manifest, CONFIG, bands)


def test_check_stops_a_spliced_id_that_collides_with_a_corpus_id(plain_segment):
    spliced, corpus, manifest, bands = built()
    spliced.loc[0, "answer_id"] = corpus.loc[0, "answer_id"]
    with pytest.raises(SystemExit, match="repeat or collide"):
        build_spliced.check(spliced, corpus, manifest, CONFIG, bands)


def test_the_shipped_config_passes_its_own_checks():
    with open(build_spliced.DEFAULT_CONFIG, encoding="utf-8") as f:
        config = yaml.safe_load(f)
    corpus = pd.DataFrame([{"partition": p, "dataset": d, "generator": g}
                           for p in ("train", "val", "test") for d in ("engsaf", "mohler", "sprag")
                           for g in ["human"] + [f"m{i}" for i in range(6)]])
    bands, _, per_model = build_spliced.check_config(config, corpus)
    assert sorted(bands) == [25, 50, 75] and config["partitions"] == ["train", "val", "test"]
    assert per_model == {("train", "engsaf"): 5, ("train", "mohler"): 23, ("train", "sprag"): 17,
                         ("val", "engsaf"): 1, ("val", "mohler"): 4, ("val", "sprag"): 3,
                         ("test", "engsaf"): 15, ("test", "mohler"): 15, ("test", "sprag"): 15}


def write_corpus(tmp_path, corpus, manifest):
    folder = tmp_path / "data" / "corpus"
    folder.mkdir(parents=True)
    corpus.to_parquet(folder / "v9.parquet", index=False)
    (folder / "v9_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return folder


def write_config(tmp_path, **changes):
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(CONFIG | {"corpus": "data/corpus/v9.parquet"} | changes), encoding="utf-8")
    return path


def test_main_writes_the_pair_next_to_the_corpus(tmp_path, monkeypatch, plain_segment):
    corpus, manifest = tiny_corpus()
    folder = write_corpus(tmp_path, corpus, manifest)
    monkeypatch.setattr(build_spliced, "PIPELINE_DIR", tmp_path)
    monkeypatch.setattr("sys.argv", ["build_spliced", "--config", str(write_config(tmp_path))])
    build_spliced.main()

    written = pd.read_parquet(folder / "v9-spliced.parquet")
    saved = json.loads((folder / "v9-spliced_manifest.json").read_text(encoding="utf-8"))
    assert len(written) == 24
    assert saved["version"] == "v9-spliced"
    assert saved["source"]["sha256"] == hashlib.sha256((folder / "v9.parquet").read_bytes()).hexdigest()
    assert saved["rows"]["test"]["d"]["25"] == {"m1": 4, "m2": 4}
    assert saved["text_cleaning"] == "clean_v2" and saved["answers_per_model"] == {"test": {"d": 4}}


def test_the_manifest_records_the_settings_and_the_statistics(tmp_path, monkeypatch, plain_segment):
    # four students per question, so the bases (12) and donors (18) of test d differ
    corpus, manifest = tiny_corpus(students=4)
    folder = write_corpus(tmp_path, corpus, manifest)
    monkeypatch.setattr(build_spliced, "PIPELINE_DIR", tmp_path)
    monkeypatch.setattr("sys.argv", ["build_spliced", "--config", str(write_config(tmp_path))])
    build_spliced.main()

    written = pd.read_parquet(folder / "v9-spliced.parquet")
    saved = json.loads((folder / "v9-spliced_manifest.json").read_text(encoding="utf-8"))
    assert saved["version"] == "v9-spliced"
    assert datetime.fromisoformat(saved["built_at"]).utcoffset() == timedelta(0)
    assert saved["source"]["path"].endswith("data/corpus/v9.parquet")
    assert saved["text_cleaning"] == "clean_v2" and saved["seed"] == 1 and saved["partitions"] == ["test"]
    assert saved["segmenter"] == {"spacy": spacy.__version__, "model": "en_core_web_sm",
                                  "model_version": spacy.util.get_package_version("en_core_web_sm")}
    assert saved["bands"] == {"25": [0.15, 0.35], "50": [0.4, 0.6], "75": [0.65, 0.85]}
    assert (saved["answers_per_band"], saved["answers_per_model"]) == (8, {"test": {"d": 4}})
    assert (saved["max_base_uses"], saved["min_sentences"]) == (2, 2)
    assert saved["eligible"] == {"test": {"d": {"bases": 12, "donors": 18}}}
    # every base meets every donor of the band's tier: 12 bases and 2 models
    assert saved["candidates"] == {"test": {"d": {"25": 24, "50": 24, "75": 24}}}
    assert saved["rows"] == {"test": {"d": {band: {"m1": 4, "m2": 4} for band in ("25", "50", "75")}}}
    for band, (low, high) in CONFIG["bands"].items():
        in_band = written[written["style"] == f"spliced-{band}"]["ai_fraction"]
        mean = saved["mean_ai_fraction"]["test"]["d"][str(band)]
        assert low <= mean <= high
        assert mean == pytest.approx(in_band.mean(), abs=1e-4)
    uses = written.groupby(["style", "human_answer_id"]).size()
    assert saved["most_base_uses"] == uses.max() and saved["most_base_uses"] <= 2
    assert saved["answers_per_question"] == written.groupby("question_id").size().to_dict()
    assert sum(saved["answers_per_question"].values()) == len(written) == 24


def test_a_failed_build_leaves_the_previous_pair_untouched(tmp_path, monkeypatch, plain_segment):
    corpus, manifest = tiny_corpus()
    folder = write_corpus(tmp_path, corpus, manifest)
    monkeypatch.setattr(build_spliced, "PIPELINE_DIR", tmp_path)
    monkeypatch.setattr("sys.argv", ["build_spliced", "--config", str(write_config(tmp_path))])
    build_spliced.main()
    before = {p.name: p.read_bytes() for p in folder.glob("v9-spliced*")}

    monkeypatch.setattr("sys.argv", ["build_spliced", "--config", str(write_config(tmp_path, answers_per_band=60))])
    with pytest.raises(SystemExit, match="cannot reach"):
        build_spliced.main()
    assert {p.name: p.read_bytes() for p in folder.glob("v9-spliced*")} == before


def test_a_missing_corpus_stops_main(tmp_path, monkeypatch):
    monkeypatch.setattr(build_spliced, "PIPELINE_DIR", tmp_path)
    monkeypatch.setattr("sys.argv", ["build_spliced", "--config", str(write_config(tmp_path))])
    with pytest.raises(SystemExit, match="no file at"):
        build_spliced.main()

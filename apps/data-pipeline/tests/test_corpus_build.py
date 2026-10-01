import hashlib
import json
import os
import subprocess
import sys

import pandas as pd
import pytest

from config import SPLIT_RATIOS
from corpus import build as corpus_build

REQUIRED = {"answer", "label", "partition", "question_id", "answer_id", "generator", "n_words"}


def write_sources(tmp_path, dataset="mohler", questions=20, humans=30, ai=4, shared_text=(), extra_records=(),
                  texts=None):
    """A cleaned corpus and a harness run for one dataset. Questions listed
    in shared_text reuse question 0's text, like Mohler's repeated pairs.
    Texts carry the dataset name unless texts gives another prefix."""
    prefix = texts or dataset
    rows = [
        {"id": f"E01.Q{q:02d}.A{a:02d}", "question": f"{prefix} question {0 if q in shared_text else q}",
         "student_answer": f"student {q} {a} wrote this"}
        for q in range(questions) for a in range(humans)
    ]
    human_path = tmp_path / f"{dataset}_cleaned.parquet"
    pd.DataFrame(rows).to_parquet(human_path)
    records = [
        {"answer_id": f"{dataset}/E01.Q{q:02d}/fake/correct/{s:02d}", "question_id": f"{dataset}/E01.Q{q:02d}",
         "generator": "fake", "tier": "correct", "answer": f"model answer {q} {s}"}
        for q in range(questions) for s in range(1, ai + 1)
    ]
    ai_path = tmp_path / f"{dataset}_answers.jsonl"
    ai_path.write_text("".join(json.dumps(r) + "\n" for r in [*records, *extra_records]), encoding="utf-8")
    return human_path, ai_path


def test_a_question_text_in_two_datasets_stops_the_build(tmp_path):
    # split separately, the same question could land in train for one
    # dataset and test for the other
    sources = {name: write_sources(tmp_path, dataset=name, texts="shared") for name in ("mohler", "sprag")}
    with pytest.raises(SystemExit, match="question_text in more than one partition"):
        corpus_build.build(sources)


def test_rows_have_the_trainer_columns_and_labels(tmp_path):
    corpus, _ = corpus_build.build({"mohler": write_sources(tmp_path)})
    assert REQUIRED <= set(corpus.columns)
    assert set(corpus["partition"]) == {"train", "val", "test"}
    humans, ais = corpus[corpus["label"] == 0], corpus[corpus["label"] == 1]
    assert set(humans["generator"]) == {"human"} and set(ais["generator"]) == {"fake"}
    assert humans["answer_id"].str.startswith("mohler/E01.Q").all()
    assert set(humans["n_words"]) == {5} and set(ais["n_words"]) == {4}
    assert corpus["answer_id"].is_unique


def test_questions_sharing_a_text_land_in_one_partition(tmp_path):
    corpus, manifest = corpus_build.build({"mohler": write_sources(tmp_path, shared_text=(5, 9))})
    partitions = manifest["question_partitions"]
    assert partitions["mohler/E01.Q00"] == partitions["mohler/E01.Q05"] == partitions["mohler/E01.Q09"]
    assert corpus.groupby("question_id")["partition"].nunique().max() == 1


def test_every_dataset_reaches_every_partition(tmp_path):
    sources = {name: write_sources(tmp_path, dataset=name) for name in ("mohler", "sprag")}
    corpus, _ = corpus_build.build(sources)
    for partition in ("train", "val", "test"):
        assert set(corpus[corpus["partition"] == partition]["dataset"]) == {"mohler", "sprag"}


def test_train_keeps_as_many_humans_as_ai_answers_and_val_test_keep_all(tmp_path):
    corpus, manifest = corpus_build.build({"mohler": write_sources(tmp_path, humans=30, ai=4)})
    humans_per_question = corpus[corpus["label"] == 0].groupby(["partition", "question_id"]).size()
    assert set(humans_per_question["train"]) == {4}
    assert set(humans_per_question["val"]) == set(humans_per_question["test"]) == {30}
    train_questions = len(humans_per_question["train"])
    assert manifest["train_human_answers_dropped_by_cap"] == train_questions * 26


def test_cap_leaves_train_questions_without_ai_answers_out():
    corpus = pd.DataFrame([
        {"answer_id": "h1", "question_id": "q1", "label": 0, "partition": "train"},
        {"answer_id": "h2", "question_id": "q1", "label": 0, "partition": "train"},
        {"answer_id": "a1", "question_id": "q1", "label": 1, "partition": "train"},
        {"answer_id": "h3", "question_id": "q2", "label": 0, "partition": "train"},
        {"answer_id": "h4", "question_id": "q3", "label": 0, "partition": "test"},
    ])
    capped, dropped = corpus_build.cap_train_humans(corpus, seed=1)
    assert sorted(capped["answer_id"]) in (["a1", "h1", "h4"], ["a1", "h2", "h4"])
    assert dropped == 2


def test_rewrites_are_skipped(tmp_path):
    rewrite = {"answer_id": "mohler/E01.Q00/fake/rewrite/01", "question_id": "mohler/E01.Q00",
               "generator": "fake", "tier": "rewrite", "answer": "polished student text",
               "source_answer_id": "mohler/E01.Q00.A00"}
    corpus, manifest = corpus_build.build({"mohler": write_sources(tmp_path, extra_records=[rewrite])})
    assert "mohler/E01.Q00/fake/rewrite/01" not in set(corpus["answer_id"])
    assert manifest["rewrite_records_skipped"] == 1


def test_answers_from_another_dataset_stop_the_build(tmp_path):
    human_path, _ = write_sources(tmp_path, dataset="mohler")
    _, sprag_run = write_sources(tmp_path, dataset="sprag")
    with pytest.raises(SystemExit, match="outside mohler"):
        corpus_build.build({"mohler": (human_path, sprag_run)})


def test_same_inputs_give_the_same_corpus(tmp_path):
    sources = {"mohler": write_sources(tmp_path, shared_text=(3,))}
    first, first_manifest = corpus_build.build(sources)
    second, second_manifest = corpus_build.build(sources)
    pd.testing.assert_frame_equal(first, second)
    assert first_manifest == second_manifest


def test_check_rejects_a_question_in_two_partitions():
    corpus = pd.DataFrame([
        {"question_id": "q1", "question_text": "a", "question_group": "a", "answer": "text", "answer_id": f"x{i}",
         "label": label,
         "partition": partition, "dataset": "mohler"}
        for i, (label, partition) in enumerate([(0, "train"), (1, "train"), (0, "val"), (1, "val"),
                                                (0, "test"), (1, "test")])
    ])
    with pytest.raises(SystemExit, match="question_id in more than one partition"):
        corpus_build.check(corpus)


def test_both_sides_are_cleaned_the_same_way(tmp_path):
    human_path, ai_path = write_sources(tmp_path)
    df = pd.read_parquet(human_path)
    df.loc[0, "student_answer"] = "first line<br>second line\nthird"
    df.to_parquet(human_path)
    styled = {"answer_id": "mohler/E01.Q00/fake/weak/09", "question_id": "mohler/E01.Q00", "generator": "fake",
              "tier": "weak", "answer": "it\u2019s `*args` \u2014 **mostly**"}
    with open(ai_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(styled) + "\n")
    corpus, manifest = corpus_build.build({"mohler": (human_path, ai_path)})

    answers = dict(zip(corpus["answer_id"], corpus["answer"], strict=True))
    if "mohler/E01.Q00.A00" in answers:
        assert answers["mohler/E01.Q00.A00"] == "first line second line third"
    assert answers["mohler/E01.Q00/fake/weak/09"] == "it's *args - mostly"
    assert manifest["text_cleaning"] == "clean_v2"


def test_answers_under_three_words_are_dropped_on_both_sides(tmp_path):
    human_path, ai_path = write_sources(tmp_path)
    df = pd.read_parquet(human_path)
    df.loc[0, "student_answer"] = "LIFO"
    df.loc[1, "student_answer"] = "last in"
    df.to_parquet(human_path)
    terse = {"answer_id": "mohler/E01.Q00/fake/correct/09", "question_id": "mohler/E01.Q00", "generator": "fake",
             "tier": "correct", "answer": "a stack"}
    with open(ai_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(terse) + "\n")
    corpus, manifest = corpus_build.build({"mohler": (human_path, ai_path)})

    assert corpus["n_words"].min() >= corpus_build.MIN_WORDS
    assert manifest["answers_under_min_words_dropped"] == {"human": 2, "ai": 1}


def test_main_writes_the_corpus_and_a_manifest_without_local_paths(tmp_path, monkeypatch):
    write_sources(tmp_path)
    config = tmp_path / "config.yaml"
    config.write_text(
        "version: v0.1\nout_dir: corpus\ndatasets:\n  mohler:\n"
        "    human_corpus: mohler_cleaned.parquet\n    ai_answers: mohler_answers.jsonl\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(corpus_build, "PIPELINE_DIR", tmp_path)
    monkeypatch.setattr("sys.argv", ["build", "--config", str(config)])
    corpus_build.main()

    written = pd.read_parquet(tmp_path / "corpus" / "v0.1.parquet")
    assert REQUIRED <= set(written.columns)
    manifest = json.loads((tmp_path / "corpus" / "v0.1_manifest.json").read_text(encoding="utf-8"))
    assert manifest["version"] == "v0.1"
    assert manifest["sources"]["mohler"]["human_corpus"]["path"] == "mohler_cleaned.parquet"


def test_main_refuses_a_placeholder_run(tmp_path, monkeypatch):
    write_sources(tmp_path)
    config = tmp_path / "config.yaml"
    config.write_text(
        "version: v0.1\nout_dir: corpus\ndatasets:\n  mohler:\n"
        "    human_corpus: mohler_cleaned.parquet\n    ai_answers: REPLACE-WITH-RUN-ID/answers.jsonl\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(corpus_build, "PIPELINE_DIR", tmp_path)
    monkeypatch.setattr("sys.argv", ["build", "--config", str(config)])
    with pytest.raises(SystemExit, match="no file at"):
        corpus_build.main()
    assert not (tmp_path / "corpus").exists()


def split_frame(rows):
    """A minimal corpus frame for check(), one dict per row."""
    base = {"answer": "text", "dataset": "mohler"}
    return pd.DataFrame([{**base, **row} for row in rows])


def full_rows(**overrides):
    rows = []
    for i, partition in enumerate(corpus_build.PARTITIONS):
        for label in (0, 1):
            rows.append({"question_id": f"q{i}", "question_text": f"t{i}", "question_group": f"t{i}",
                         "answer_id": f"{partition}-{label}", "label": label, "partition": partition})
    return [{**row, **overrides.get(row["answer_id"], {})} for row in rows]


def test_check_accepts_a_complete_corpus():
    corpus_build.check(split_frame(full_rows()))


@pytest.mark.parametrize("change, message", [
    ({"val-1": {"answer_id": "val-0"}}, "duplicate answer_id"),
    ({"test-0": {"answer": ""}}, "empty answers"),
    ({"val-1": {"label": 0}}, "val mohler does not have both human and ai answers"),
    ({"val-0": {"question_group": "t0"}, "val-1": {"question_group": "t0"}},
     "question_group in more than one partition"),
])
def test_check_stops_each_kind_of_fault(change, message):
    with pytest.raises(SystemExit, match=message):
        corpus_build.check(split_frame(full_rows(**change)))


def test_check_wants_every_dataset_in_every_partition():
    sprag = {"question_id": "s1", "question_text": "s", "question_group": "s", "partition": "train", "dataset": "sprag"}
    rows = full_rows() + [{**sprag, "answer_id": "s-0", "label": 0}, {**sprag, "answer_id": "s-1", "label": 1}]
    with pytest.raises(SystemExit, match="val has no answers from sprag"):
        corpus_build.check(split_frame(rows))


def test_a_pilot_run_for_one_dataset_stops_the_build(tmp_path):
    mohler = write_sources(tmp_path)
    human_path, ai_path = write_sources(tmp_path, dataset="sprag")
    # keep only the answers to one question, as a smoke or pilot run leaves
    lines = ai_path.read_text(encoding="utf-8").splitlines()
    ai_path.write_text("\n".join(line for line in lines if '"sprag/E01.Q00"' in line) + "\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="sprag does not have both human and ai answers"):
        corpus_build.build({"mohler": mohler, "sprag": (human_path, ai_path)})


def test_three_groups_split_one_each_and_two_are_too_few():
    texts = {"d/q1": "a", "d/q2": "b", "d/q3": "c"}
    assert sorted(corpus_build.assign_partitions(texts, "d", 1, SPLIT_RATIOS).values()) == ["test", "train", "val"]
    with pytest.raises(SystemExit, match="too few"):
        corpus_build.assign_partitions({"d/q1": "a", "d/q2": "b"}, "d", 1, SPLIT_RATIOS)


def test_shared_text_groups_hold_at_every_seed():
    texts = {f"mohler/E01.Q{q:02d}": f"question {0 if q in (5, 9) else q}" for q in range(20)}
    for seed in range(50):
        partitions = corpus_build.assign_partitions(texts, "mohler", seed, SPLIT_RATIOS)
        assert len({partitions[f"mohler/E01.Q{q:02d}"] for q in (0, 5, 9)}) == 1


def test_listed_twins_land_together_at_every_seed():
    texts = {f"mohler/E01.Q{q:02d}": f"question {q}" for q in range(20)}
    twins = [["mohler/E01.Q03", "mohler/E01.Q17"], ["mohler/E01.Q17", "mohler/E01.Q08"]]
    for seed in range(50):
        partitions = corpus_build.assign_partitions(texts, "mohler", seed, SPLIT_RATIOS, twins)
        assert len({partitions[f"mohler/E01.Q{q:02d}"] for q in (3, 8, 17)}) == 1


def test_an_unknown_twin_stops_the_build(tmp_path):
    with pytest.raises(SystemExit, match="same_question lists ids"):
        corpus_build.build({"mohler": write_sources(tmp_path)}, same_question={"mohler": [["E01.Q01", "E99.Q99"]]})


def test_the_split_is_the_same_in_every_process():
    code = ("import json, sys; sys.path.insert(0, 'app'); from corpus.build import assign_partitions;"
            "texts = {f'd/q{i}': f'text {i % 17}' for i in range(40)};"
            "print(json.dumps(assign_partitions(texts, 'd', 42, {'train': 0.7, 'val': 0.15, 'test': 0.15})))")
    outputs = {
        subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True,
                       env={**os.environ, "PYTHONHASHSEED": hash_seed}).stdout
        for hash_seed in ("0", "1", "2")
    }
    assert len(outputs) == 1


def test_the_seed_changes_the_split_and_the_cap(tmp_path):
    sources = {"mohler": write_sources(tmp_path)}
    corpus_42, manifest_42 = corpus_build.build(sources, seed=42)
    corpus_7, manifest_7 = corpus_build.build(sources, seed=7)
    assert manifest_42["question_partitions"] != manifest_7["question_partitions"]

    def train_humans(corpus):
        return set(corpus[(corpus["label"] == 0) & (corpus["partition"] == "train")]["answer_id"])

    assert train_humans(corpus_42) != train_humans(corpus_7)


def test_load_human_reads_sprag_headers_and_drops_blank_answers(tmp_path):
    path = tmp_path / "sprag.parquet"
    pd.DataFrame({
        "id": ["PythonQ057.A0", "PythonQ057.A1", "PythonQ057.A2", "PythonQ058.A0"],
        "QuestionID": ["PythonQ057", "PythonQ057", "PythonQ057", "PythonQ058"],
        "QuestionText": ["q57", "q57", "q57", "q58"],
        "StudentAnswer": ["an answer", "  ", None, "<br>"],
    }).to_parquet(path)
    humans = corpus_build.load_human(path, "sprag")
    assert list(humans["answer_id"]) == ["sprag/PythonQ057.A0"]
    assert list(humans["question_id"]) == ["sprag/PythonQ057"]


def test_a_question_without_text_stops_the_build(tmp_path):
    path = tmp_path / "mohler.parquet"
    pd.DataFrame({"id": ["E01.Q01.A00", "E01.Q02.A00"], "question": ["q1", None],
                  "student_answer": ["a", "b"]}).to_parquet(path)
    with pytest.raises(SystemExit, match="questions without text"):
        corpus_build.load_human(path, "mohler")


def test_questions_without_ai_answers_are_listed(tmp_path):
    human_path, ai_path = write_sources(tmp_path)
    lines = ai_path.read_text(encoding="utf-8").splitlines()
    ai_path.write_text("\n".join(line for line in lines if '"mohler/E01.Q19"' not in line) + "\n", encoding="utf-8")
    _, manifest = corpus_build.build({"mohler": (human_path, ai_path)})
    assert manifest["questions_without_ai_answers"] == {"mohler": ["mohler/E01.Q19"]}


def write_config(tmp_path, datasets, ai_file="{name}_answers.jsonl"):
    lines = ["version: v0.1", "out_dir: corpus", "datasets:"]
    for name in datasets:
        lines += [f"  {name}:", f"    human_corpus: {name}_cleaned.parquet", f"    ai_answers: {ai_file.format(name=name)}"]
    config = tmp_path / "config.yaml"
    config.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return config


def test_manifest_counts_generators_and_hashes_match_the_files(tmp_path, monkeypatch):
    human_path, ai_path = write_sources(tmp_path)
    config = write_config(tmp_path, ["mohler"])
    monkeypatch.setattr(corpus_build, "PIPELINE_DIR", tmp_path)
    monkeypatch.setattr("sys.argv", ["build", "--config", str(config)])
    corpus_build.main()

    written = pd.read_parquet(tmp_path / "corpus" / "v0.1.parquet")
    manifest = json.loads((tmp_path / "corpus" / "v0.1_manifest.json").read_text(encoding="utf-8"))
    counts = written.groupby(["partition", "label"]).size()
    for partition in corpus_build.PARTITIONS:
        assert manifest["rows"][partition]["mohler"] == {"human": int(counts[(partition, 0)]),
                                                          "ai": int(counts[(partition, 1)])}
    assert manifest["generators"] == ["fake"]
    sources = manifest["sources"]["mohler"]
    assert sources["human_corpus"]["sha256"] == hashlib.sha256(human_path.read_bytes()).hexdigest()
    assert sources["ai_answers"]["sha256"] == hashlib.sha256(ai_path.read_bytes()).hexdigest()


def test_a_partial_build_never_replaces_the_full_corpus(tmp_path, monkeypatch):
    write_sources(tmp_path)
    write_sources(tmp_path, dataset="sprag")
    config = write_config(tmp_path, ["mohler", "sprag"])
    # twins listed for a dataset the partial build leaves out are not an error
    with open(config, "a", encoding="utf-8") as f:
        f.write("same_question:\n  sprag:\n    - [E01.Q01, E01.Q02]\n")
    monkeypatch.setattr(corpus_build, "PIPELINE_DIR", tmp_path)
    monkeypatch.setattr("sys.argv", ["build", "--config", str(config), "--datasets", "mohler"])
    corpus_build.main()

    assert not (tmp_path / "corpus" / "v0.1.parquet").exists()
    written = pd.read_parquet(tmp_path / "corpus" / "v0.1-only-mohler.parquet")
    assert set(written["dataset"]) == {"mohler"}
    manifest = json.loads((tmp_path / "corpus" / "v0.1-only-mohler_manifest.json").read_text(encoding="utf-8"))
    assert manifest["version"] == "v0.1-only-mohler" and list(manifest["sources"]) == ["mohler"]


def test_a_missing_file_names_the_config_it_came_from(tmp_path, monkeypatch):
    write_sources(tmp_path)
    config = write_config(tmp_path, ["mohler"], ai_file="REPLACE-WITH-RUN-ID/answers.jsonl")
    monkeypatch.setattr(corpus_build, "PIPELINE_DIR", tmp_path)
    monkeypatch.setattr("sys.argv", ["build", "--config", str(config)])
    with pytest.raises(SystemExit, match="paths in config.yaml"):
        corpus_build.main()


def test_a_run_mixing_prompt_versions_stops_the_build(tmp_path):
    other = {"answer_id": "mohler/E01.Q00/fake/correct/09", "question_id": "mohler/E01.Q00", "generator": "fake",
             "tier": "correct", "prompt_template": "correct_v1", "answer": "an older answer"}
    with pytest.raises(SystemExit, match="mixes prompt versions"):
        corpus_build.build({"mohler": write_sources(tmp_path, extra_records=[other])})


def test_the_manifest_records_the_prompt_templates(tmp_path):
    _, manifest = corpus_build.build({"mohler": write_sources(tmp_path)})
    assert manifest["prompt_templates"] == {"mohler": {"correct": None}}


def test_twins_from_the_config_land_together(tmp_path):
    sources = {"mohler": write_sources(tmp_path)}
    twins = {"mohler": [["E01.Q03", "E01.Q17"], ["E01.Q11", "E01.Q05"]]}
    for seed in range(5):
        _, manifest = corpus_build.build(sources, seed=seed, same_question=twins)
        partitions = manifest["question_partitions"]
        assert partitions["mohler/E01.Q03"] == partitions["mohler/E01.Q17"]
        assert partitions["mohler/E01.Q05"] == partitions["mohler/E01.Q11"]
    assert manifest["same_question"] == {"mohler": [["mohler/E01.Q03", "mohler/E01.Q17"],
                                                    ["mohler/E01.Q11", "mohler/E01.Q05"]]}


def test_the_split_ignores_input_order():
    texts = {f"d/q{i}": f"text {i % 11}" for i in range(30)}
    twins = [["d/q1", "d/q2"], ["d/q5", "d/q9"]]
    for seed in range(50):
        forward = corpus_build.assign_partitions(texts, "d", seed, SPLIT_RATIOS, twins)
        backward = corpus_build.assign_partitions(dict(reversed(texts.items())), "d", seed, SPLIT_RATIOS,
                                                  [list(reversed(pair)) for pair in reversed(twins)])
        assert forward == backward


@pytest.mark.parametrize("groups, sizes", [(13, {"train": 9, "val": 2, "test": 2}),
                                           (40, {"train": 28, "val": 6, "test": 6})])
def test_partition_sizes_follow_the_ratios(groups, sizes):
    import collections

    texts = {f"d/q{i}": f"text {i}" for i in range(groups)}
    assert collections.Counter(corpus_build.assign_partitions(texts, "d", 42, SPLIT_RATIOS).values()) == sizes


def test_the_cap_draws_with_its_seed():
    rows = [{"answer_id": f"h{i:02d}", "question_id": "q1", "label": 0, "partition": "train"} for i in range(30)]
    rows += [{"answer_id": f"a{i}", "question_id": "q1", "label": 1, "partition": "train"} for i in range(4)]
    corpus = pd.DataFrame(rows)
    kept_42 = set(corpus_build.cap_train_humans(corpus, seed=42)[0]["answer_id"])
    kept_7 = set(corpus_build.cap_train_humans(corpus, seed=7)[0]["answer_id"])
    assert kept_42 != kept_7


def test_n_words_counts_comma_joined_lists(tmp_path):
    human_path, ai_path = write_sources(tmp_path)
    df = pd.read_parquet(human_path)
    df.loc[0, "student_answer"] = "min(),max(),len()"
    df.to_parquet(human_path)
    _, manifest = corpus_build.build({"mohler": (human_path, ai_path)})
    # counted by whitespace it would be one word and fall under the floor
    assert manifest["answers_under_min_words_dropped"] == {"human": 0, "ai": 0}


def test_a_misspelt_same_question_dataset_stops_main(tmp_path, monkeypatch):
    write_sources(tmp_path)
    config = write_config(tmp_path, ["mohler"])
    with open(config, "a", encoding="utf-8") as f:
        f.write("same_question:\n  mohlr:\n    - [E01.Q01, E01.Q02]\n")
    monkeypatch.setattr(corpus_build, "PIPELINE_DIR", tmp_path)
    monkeypatch.setattr("sys.argv", ["build", "--config", str(config)])
    with pytest.raises(SystemExit, match="does not have"):
        corpus_build.main()


@pytest.mark.parametrize("chosen", [["mohler", "sprag"], ["sprag", "mohler"]])
def test_a_two_dataset_subset_gets_its_own_name(tmp_path, monkeypatch, chosen):
    for name in ("mohler", "sprag", "engsaf"):
        write_sources(tmp_path, dataset=name)
    config = write_config(tmp_path, ["mohler", "sprag", "engsaf"])
    monkeypatch.setattr(corpus_build, "PIPELINE_DIR", tmp_path)
    monkeypatch.setattr("sys.argv", ["build", "--config", str(config), "--datasets", *chosen])
    corpus_build.main()
    assert not (tmp_path / "corpus" / "v0.1.parquet").exists()
    assert (tmp_path / "corpus" / "v0.1-only-mohler-sprag.parquet").exists()


def test_the_builder_floor_is_the_harness_floor():
    from harness import generate

    assert corpus_build.MIN_WORDS == generate.MIN_TARGET_WORDS == 3


def test_the_floor_keeps_three_words_and_drops_two(tmp_path):
    human_path, ai_path = write_sources(tmp_path)
    df = pd.read_parquet(human_path)
    df.loc[0, "student_answer"] = "last in first"
    df.loc[1, "student_answer"] = "last in"
    df.to_parquet(human_path)
    _, manifest = corpus_build.build({"mohler": (human_path, ai_path)})
    assert manifest["answers_under_min_words_dropped"] == {"human": 1, "ai": 0}


def test_a_run_mixing_courses_stops_the_build(tmp_path):
    other = {"answer_id": "mohler/E01.Q00/fake/correct/09", "question_id": "mohler/E01.Q00", "generator": "fake",
             "tier": "correct", "course": "another course", "answer": "an answer from another course"}
    with pytest.raises(SystemExit, match="mixes prompt versions"):
        corpus_build.build({"mohler": write_sources(tmp_path, extra_records=[other])})


def thinned_sources(tmp_path, dataset="mohler", questions=20, extra_records=()):
    """write_sources plus one wrong-tier answer per question from each of two generators."""
    wrong = [
        {"answer_id": f"{dataset}/E01.Q{q:02d}/{g}/wrong/01", "question_id": f"{dataset}/E01.Q{q:02d}",
         "generator": g, "tier": "wrong", "answer": f"a wrong answer {q} {g}"}
        for q in range(questions) for g in ("alpha", "beta")
    ]
    return write_sources(tmp_path, dataset=dataset, questions=questions, extra_records=[*wrong, *extra_records])


@pytest.mark.parametrize("seed", range(8))
def test_keep_thins_a_tier_by_the_same_share_for_every_generator_in_every_partition(tmp_path, seed):
    corpus, manifest = corpus_build.build({"mohler": thinned_sources(tmp_path)}, seed=seed,
                                          keep={"mohler": {"wrong": 0.5}})
    wrong = corpus[corpus["tier"] == "wrong"]
    # 20 questions split 14/3/3, half of each rounded half to even
    per_partition = {"test": 2, "train": 7, "val": 2}
    assert wrong.groupby(["generator", "partition"]).size().unstack().to_dict("index") == {
        "alpha": per_partition, "beta": per_partition}
    assert (corpus["tier"] == "correct").sum() == 20 * 4
    assert manifest["ai_keep_shares"] == {"mohler": {"wrong": 0.5}}
    assert manifest["ai_answers_dropped_by_keep"] == {"mohler": {"wrong": 18}}


def test_keep_draws_the_same_answers_every_build_and_moves_with_the_seed(tmp_path):
    sources = {"mohler": thinned_sources(tmp_path)}

    def wrong_kept(seed):
        corpus, _ = corpus_build.build(sources, seed=seed, keep={"mohler": {"wrong": 0.5}})
        return set(corpus[corpus["tier"] == "wrong"]["answer_id"])

    assert wrong_kept(42) == wrong_kept(42)
    assert wrong_kept(42) != wrong_kept(7)


def test_keep_draws_each_generator_on_its_own(tmp_path):
    corpus, _ = corpus_build.build({"mohler": thinned_sources(tmp_path)}, keep={"mohler": {"wrong": 0.5}})
    kept = corpus[corpus["tier"] == "wrong"].groupby("generator")["question_id"].apply(set)
    assert kept["alpha"] != kept["beta"]


def test_keep_does_not_depend_on_the_order_of_the_run(tmp_path):
    human_path, ai_path = thinned_sources(tmp_path)
    first, _ = corpus_build.build({"mohler": (human_path, ai_path)}, keep={"mohler": {"wrong": 0.5}})
    lines = ai_path.read_text(encoding="utf-8").splitlines()
    ai_path.write_text("\n".join(reversed(lines)) + "\n", encoding="utf-8")
    second, _ = corpus_build.build({"mohler": (human_path, ai_path)}, keep={"mohler": {"wrong": 0.5}})
    assert set(first["answer_id"]) == set(second["answer_id"])


def test_keep_thins_before_the_train_cap_so_train_stays_balanced(tmp_path):
    corpus, _ = corpus_build.build({"mohler": thinned_sources(tmp_path)}, keep={"mohler": {"wrong": 0.5}})
    train = corpus[corpus["partition"] == "train"].groupby(["question_id", "label"]).size().unstack(fill_value=0)
    assert (train[0] == train[1]).all()


def test_keep_draws_from_answers_the_floor_has_not_yet_cut(tmp_path):
    short = [
        {"answer_id": f"mohler/E01.Q{q:02d}/{g}/wrong/02", "question_id": f"mohler/E01.Q{q:02d}",
         "generator": g, "tier": "wrong", "answer": "too short"}
        for q in range(20) for g in ("alpha", "beta")
    ]
    _, manifest = corpus_build.build({"mohler": thinned_sources(tmp_path, extra_records=short)},
                                     keep={"mohler": {"wrong": 0.5}})
    # pools of 28/6/6 per generator lose 14/3/3, not the 7/1/1 of the 14/3/3 left after the floor
    assert manifest["ai_answers_dropped_by_keep"] == {"mohler": {"wrong": 40}}


def test_keep_counts_the_answers_each_tier_lost_on_its_own(tmp_path):
    _, manifest = corpus_build.build({"mohler": thinned_sources(tmp_path)},
                                     keep={"mohler": {"correct": 0.5, "wrong": 0.5}})
    # the correct tier is one generator with 4 answers per question, pools of 56/12/12
    assert manifest["ai_answers_dropped_by_keep"] == {"mohler": {"correct": 40, "wrong": 18}}


def test_keep_for_one_dataset_leaves_the_others_whole(tmp_path):
    sources = {name: thinned_sources(tmp_path, dataset=name) for name in ("mohler", "sprag")}
    corpus, manifest = corpus_build.build(sources, keep={"mohler": {"wrong": 0.5}})
    assert ((corpus["dataset"] == "sprag") & (corpus["tier"] == "wrong")).sum() == 40
    assert manifest["ai_keep_shares"] == {"mohler": {"wrong": 0.5}, "sprag": {}}
    assert manifest["ai_answers_dropped_by_keep"] == {"mohler": {"wrong": 18}, "sprag": {}}


@pytest.mark.parametrize("share", [1, 1.0])
def test_keep_of_one_keeps_the_whole_tier(tmp_path, share):
    corpus, manifest = corpus_build.build({"mohler": thinned_sources(tmp_path)}, keep={"mohler": {"wrong": share}})
    assert (corpus["tier"] == "wrong").sum() == 40
    assert manifest["ai_answers_dropped_by_keep"] == {"mohler": {"wrong": 0}}


def test_keep_rounds_the_kept_count_rather_than_cutting_it():
    ais = pd.DataFrame({"answer_id": [f"q{i:02d}/g/wrong/01" for i in range(19)],
                        "question_id": [f"q{i:02d}" for i in range(19)], "generator": "g", "tier": "wrong"})
    kept, lost = corpus_build.keep_share(ais, {"wrong": 0.5}, "mohler", 42, {f"q{i:02d}": "train" for i in range(19)})
    assert len(kept) == 10 and lost == {"wrong": 9}


def one_pool(n):
    """n wrong-tier answers from one generator, every question in train."""
    ais = pd.DataFrame({"answer_id": [f"q{i:02d}/g/wrong/01" for i in range(n)],
                        "question_id": [f"q{i:02d}" for i in range(n)], "generator": "g", "tier": "wrong"})
    return ais, {f"q{i:02d}": "train" for i in range(n)}


@pytest.mark.parametrize("n, share, kept_n", [(5, 0.5, 2), (13, 0.5, 6), (4, 0.3, 1)])
def test_keep_rounds_the_kept_count_half_to_even(n, share, kept_n):
    ais, partitions = one_pool(n)
    kept, _ = corpus_build.keep_share(ais, {"wrong": share}, "mohler", 42, partitions)
    assert len(kept) == kept_n


def test_keep_draw_follows_the_seed_with_the_split_held_fixed():
    ais, partitions = one_pool(20)

    def kept(seed):
        return set(corpus_build.keep_share(ais, {"wrong": 0.5}, "mohler", seed, partitions)[0]["answer_id"])

    assert kept(42) == kept(42)
    assert kept(42) != kept(7)


@pytest.mark.parametrize("shares, message", [
    ({"wrong": 0}, "above 0 and at most 1"),
    ({"wrong": 1.5}, "above 0 and at most 1"),
    ({"wrong": "half"}, "above 0 and at most 1"),
    ({"wrong": True}, "above 0 and at most 1"),
    ({"wrng": 0.5}, "tiers its run does not have"),
    (0.5, "must map tiers to shares"),
    (["wrong"], "must map tiers to shares"),
    ("wrong", "must map tiers to shares"),
    (0, "must map tiers to shares"),
    (False, "must map tiers to shares"),
])
def test_keep_refuses_a_setting_it_cannot_apply(tmp_path, shares, message):
    with pytest.raises(SystemExit, match=message):
        corpus_build.build({"mohler": thinned_sources(tmp_path)}, keep={"mohler": shares})


def test_without_keep_every_ai_answer_stays(tmp_path):
    corpus, manifest = corpus_build.build({"mohler": thinned_sources(tmp_path)})
    assert (corpus["tier"] == "wrong").sum() == 40
    assert manifest["ai_keep_shares"] == {"mohler": {}}
    assert manifest["ai_answers_dropped_by_keep"] == {"mohler": {}}


def test_main_applies_the_keep_in_the_config(tmp_path, monkeypatch):
    thinned_sources(tmp_path)
    config = write_config(tmp_path, ["mohler"])
    config.write_text(config.read_text(encoding="utf-8") + "    keep: {wrong: 0.25}\n", encoding="utf-8")
    monkeypatch.setattr(corpus_build, "PIPELINE_DIR", tmp_path)
    monkeypatch.setattr("sys.argv", ["build", "--config", str(config)])
    corpus_build.main()

    manifest = json.loads((tmp_path / "corpus" / "v0.1_manifest.json").read_text(encoding="utf-8"))
    assert manifest["ai_keep_shares"] == {"mohler": {"wrong": 0.25}}
    # a quarter of 14/3/3 rounds to 4/1/1 kept per generator
    assert manifest["ai_answers_dropped_by_keep"] == {"mohler": {"wrong": 28}}


def test_main_stops_on_a_dataset_setting_it_does_not_read(tmp_path, monkeypatch):
    thinned_sources(tmp_path)
    config = write_config(tmp_path, ["mohler"])
    config.write_text(config.read_text(encoding="utf-8") + "    kepp: {wrong: 0.5}\n", encoding="utf-8")
    monkeypatch.setattr(corpus_build, "PIPELINE_DIR", tmp_path)
    monkeypatch.setattr("sys.argv", ["build", "--config", str(config)])
    with pytest.raises(SystemExit, match="settings the builder does not read"):
        corpus_build.main()

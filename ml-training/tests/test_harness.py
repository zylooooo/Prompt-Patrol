"""harness.py: joining the corpus columns, the 10-word filter, runs and seeds, and the evaluation protocol."""

import zlib

import numpy as np
import pandas as pd
import pytest
from scipy.special import expit

import harness
import metrics
import scores


def corpus_split(split, n_humans, n_ai, start=0):
    """Corpus rows for one split. Every 10th answer is short (5 words); the rest have 20."""
    n = n_humans + n_ai
    ids = [f"{split}-{start + i}" for i in range(n)]
    return pd.DataFrame({
        "answer_id": ids,
        "partition": split,
        "label": [0] * n_humans + [1] * n_ai,
        "n_words": [5 if i % 10 == 9 else 20 for i in range(n)],
        "slice": ["human"] * n_humans + ["raw-ai"] * n_ai,
        "dataset": "mohler",
        "generator": ["human"] * n_humans + ["gpt-5.5"] * n_ai,
        "core": True,
        "question_id": [f"q{i % 8}" for i in range(n)],
    })


@pytest.fixture
def corpus(tmp_path):
    for split, n_h, n_a in (("val", 100, 100), ("test", 100, 100)):
        corpus_split(split, n_h, n_a).drop(columns="question_id").to_parquet(
            tmp_path / f"v0.1-extended-{split}.parquet", index=False)
    return tmp_path


def model_scores(model, split, run_id="run1", seed=42, sep=2.5, n_humans=100, n_ai=100):
    """Humans score low, AIs high; `sep` sets how far apart (bigger = a better model)."""
    rng = np.random.default_rng([seed, 0 if split == "val" else 1, zlib.crc32(model.encode())])
    base = corpus_split(split, n_humans, n_ai)
    logit = np.r_[rng.normal(-sep, 1.2, n_humans), rng.normal(sep, 1.2, n_ai)]
    return pd.DataFrame({
        "run_id": run_id, "model": model, "seed": seed, "split": split,
        "answer_id": base["answer_id"], "question_id": base["question_id"],
        "y_true": base["label"], "logit": logit, "y_prob": expit(logit),
    })[scores.COLUMNS]


def build(corpus, specs):
    """specs: (model, run_id, seed, sep) -> a scores table with the corpus columns attached."""
    raw = pd.concat([model_scores(m, s, rid, seed, sep) for m, rid, seed, sep in specs for s in ("val", "test")],
                    ignore_index=True)
    return harness.attach_meta(raw, harness.load_meta(splits_dir=corpus))


@pytest.fixture
def run_df(corpus):
    return build(corpus, [("demo-untouched", "run1", 42, 2.5)])


@pytest.fixture
def two_seed_df(corpus):
    return build(corpus, [("demo-lora", "r1", 1, 2.5), ("demo-lora", "r2", 2, 2.5)])


# --------------------------------------------------------------------------
# joining the corpus columns
# --------------------------------------------------------------------------

def test_load_run_attaches_the_corpus_columns(corpus, tmp_path):
    path = tmp_path / "run_scores.parquet"
    pd.concat([model_scores("demo-untouched", s) for s in ("val", "test")]).to_parquet(path, index=False)
    df = harness.load_run(path, splits_dir=corpus)
    assert {"n_words", "slice", "dataset", "generator", "core"} <= set(df.columns)
    assert len(df) == 400
    assert df["n_words"].isin([5, 20]).all()


def test_scores_for_an_unknown_answer_are_refused(corpus):
    raw = pd.concat([model_scores("demo-untouched", s) for s in ("val", "test")], ignore_index=True)
    raw.loc[0, "answer_id"] = "not-in-the-corpus"
    with pytest.raises(ValueError, match="not in the corpus"):
        harness.attach_meta(raw, harness.load_meta(splits_dir=corpus))


def test_a_label_that_disagrees_with_the_corpus_is_refused(corpus):
    raw = pd.concat([model_scores("demo-untouched", s) for s in ("val", "test")], ignore_index=True)
    raw.loc[0, "y_true"] = 1  # the corpus says this answer is human
    with pytest.raises(ValueError, match="disagrees with the corpus label"):
        harness.attach_meta(raw, harness.load_meta(splits_dir=corpus))


def test_load_runs_reads_several_files_and_refuses_a_run_loaded_twice(corpus, tmp_path):
    paths = []
    for run_id, seed in (("r1", 1), ("r2", 2)):
        path = tmp_path / f"{run_id}_scores.parquet"
        pd.concat([model_scores("demo-lora", s, run_id, seed) for s in ("val", "test")]).to_parquet(path, index=False)
        paths.append(path)

    df = harness.load_runs(paths, splits_dir=corpus)
    assert sorted(df["run_id"].unique()) == ["r1", "r2"] and len(df) == 800
    with pytest.raises(ValueError, match="twice"):
        harness.load_runs([paths[0], paths[0]], splits_dir=corpus)


# --------------------------------------------------------------------------
# the 10-word filter and the protocol
# --------------------------------------------------------------------------

def test_min_words_filters_both_splits_and_reports_what_it_removed(run_df):
    kept = harness.evaluate_model(run_df, "demo-untouched", min_words=10, bootstrap_n=20)
    everything = harness.evaluate_model(run_df, "demo-untouched", min_words=None, bootstrap_n=20)

    # 1 answer in 10 has 5 words, in each class: 10 of 100 humans and 10 of 100 AIs per split
    assert kept["n_test"] == 180 and kept["n_val"] == 180
    assert kept["n_human_val"] == 90 and everything["n_human_val"] == 100
    assert kept["share_test_excluded"] == pytest.approx(0.1)
    assert everything["n_test"] == 200 and everything["share_test_excluded"] == 0.0


def test_the_threshold_is_fitted_on_val_and_frozen_for_test(run_df):
    out = harness.evaluate_model(run_df, "demo-untouched", min_words=None, bootstrap_n=20)
    val = run_df[(run_df["model"] == "demo-untouched") & (run_df["split"] == "val")]
    expected = metrics.threshold_at_fpr(val["y_true"], val["y_prob"], 0.01)
    assert out["threshold"] == pytest.approx(expected)
    # the realised FPR is measured on test with that fixed threshold, so it is reported and may differ
    assert out["deployed_fpr"] == out["fpr"]


def test_strict_levels_report_how_few_human_answers_they_rest_on(run_df):
    out = harness.evaluate_model(run_df, "demo-untouched", min_words=None, bootstrap_n=20)
    # 100 human validation answers: 1% allows 1 error, 0.1% allows 0.1 of an error
    assert out["val_human_errors_allowed_0.01"] == pytest.approx(1.0)
    assert out["val_human_errors_allowed_0.001"] == pytest.approx(0.1)


# --------------------------------------------------------------------------
# runs, seeds and models
# --------------------------------------------------------------------------

def test_two_seeds_of_one_model_are_never_pooled(two_seed_df):
    with pytest.raises(ValueError, match="more than one run"):
        harness.evaluate_model(two_seed_df, "demo-lora", bootstrap_n=20)

    out = harness.evaluate_model(two_seed_df, "demo-lora", run_id="r1", bootstrap_n=20)
    # 180 rows of the one run, not 360 from both
    assert out["n_test"] == 180 and out["run_id"] == "r1" and out["seed"] == 1


def test_compare_models_gives_one_row_per_run_and_filter(corpus, run_df):
    other = build(corpus, [("demo-lora", "r1", 1, 2.5), ("demo-lora", "r2", 2, 2.5)])
    table = harness.compare_models(pd.concat([run_df, other], ignore_index=True), bootstrap_n=20)

    assert list(table.columns) == harness.HEADLINE_COLUMNS
    assert table[["model", "run_id", "min_words"]].values.tolist() == [
        ["demo-lora", "r1", 0], ["demo-lora", "r1", 10],
        ["demo-lora", "r2", 0], ["demo-lora", "r2", 10],
        ["demo-untouched", "run1", 0], ["demo-untouched", "run1", 10]]
    assert (table["deployed_tpr_ci_low"] <= table["deployed_tpr_ci_high"]).all()
    assert table["oracle_tpr_at_fpr_0.01"].between(0, 1).all()


def test_aggregate_seeds_summarises_runs_of_each_model(two_seed_df):
    table = harness.compare_models(two_seed_df, bootstrap_n=20)
    summary = harness.aggregate_seeds(table)

    assert summary["n_runs"].tolist() == [2, 2]  # two filters, two runs each
    row = summary[summary["min_words"] == 10].iloc[0]
    tprs = table.loc[table["min_words"] == 10, "deployed_tpr"]
    assert row["deployed_tpr_mean"] == pytest.approx(tprs.mean())
    assert row["deployed_tpr_min"] == pytest.approx(tprs.min())
    assert row["deployed_tpr_max"] == pytest.approx(tprs.max())
    assert row["deployed_tpr_std"] == pytest.approx(tprs.std())  # sample std over the two seeds


def test_compare_pair_detects_a_clear_gap(corpus):
    df = build(corpus, [("good", "g1", 1, 3.5), ("good", "g2", 2, 3.5),
                        ("weak", "w1", 1, 0.8), ("weak", "w2", 2, 0.8)])
    out = harness.compare_pair(df, "good", "weak", bootstrap_n=200)
    assert out["n_runs_a"] == 2 and out["n_runs_b"] == 2 and out["low_seed_count"]
    assert out["diff"] > 0.2 and out["ci_low"] > 0 and out["gap_is_clear"]
    # swapping the models flips the sign
    flipped = harness.compare_pair(df, "weak", "good", bootstrap_n=200)
    assert flipped["diff"] == pytest.approx(-out["diff"]) and flipped["ci_high"] < 0


def test_compare_pair_of_a_model_with_itself_is_zero(two_seed_df):
    out = harness.compare_pair(two_seed_df, "demo-lora", "demo-lora", bootstrap_n=50)
    assert out["diff"] == 0 and out["ci_low"] == 0 and out["ci_high"] == 0
    assert not out["gap_is_clear"]


def test_compare_pair_uses_all_runs_whatever_the_seed_numbers(corpus):
    df = build(corpus, [("a", "a1", 1, 3.5), ("a", "a2", 2, 3.5), ("a", "a3", 3, 3.5),
                        ("b", "b1", 41, 0.8), ("b", "b2", 42, 0.8), ("b", "b3", 43, 0.8),
                        ("b", "b4", 44, 0.8), ("b", "b5", 45, 0.8)])
    out = harness.compare_pair(df, "a", "b", bootstrap_n=100)
    assert out["n_runs_a"] == 3 and out["n_runs_b"] == 5 and not out["low_seed_count"]
    assert out["diff"] > 0 and out["gap_is_clear"]


def test_compare_pair_flags_few_runs_and_checks_its_inputs(corpus):
    df = build(corpus, [("a", "a1", 1, 2.5), ("b", "b3", 3, 2.5)])
    assert harness.compare_pair(df, "a", "b", bootstrap_n=20)["low_seed_count"]
    with pytest.raises(ValueError, match="no runs of"):
        harness.compare_pair(df, "a", "missing")
    with pytest.raises(ValueError, match="metric must be one of"):
        harness.compare_pair(df, "a", "a", metric="accuracy")


def test_write_results_writes_one_csv_per_table(two_seed_df, tmp_path):
    table = harness.compare_models(two_seed_df, bootstrap_n=20)
    summary = harness.aggregate_seeds(table)
    paths = harness.write_results(tmp_path / "out", runs=table, seeds_summary=summary)

    assert sorted(paths) == ["runs", "seeds_summary"]
    back = pd.read_csv(paths["runs"])
    assert list(back.columns) == list(table.columns) and len(back) == len(table)
    assert back["deployed_tpr"].to_numpy() == pytest.approx(table["deployed_tpr"].to_numpy())
    assert len(pd.read_csv(paths["seeds_summary"])) == len(summary)


# --------------------------------------------------------------------------
# other tables
# --------------------------------------------------------------------------

def test_risk_coverage_uses_validation_by_default(run_df):
    table = harness.risk_coverage(run_df, "demo-untouched")
    assert len(table) == len(metrics.BAND_WIDTHS)
    assert table["coverage"].is_monotonic_decreasing
    # on val, the default split, the widest band holds the most answers
    assert table["n_answered"].iloc[0] <= 180


def test_slice_table_has_one_row_per_group(run_df):
    table = harness.slice_table(run_df, "demo-untouched", by="slice", min_words=None)
    assert sorted(table["slice_value"]) == ["human", "raw-ai"]

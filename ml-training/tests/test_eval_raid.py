"""eval_raid: the sample, resumable scoring, candidate scores and the leaderboard files - everything but the GPU."""

import json

import numpy as np
import pandas as pd
import pytest

import eval_raid


@pytest.fixture(autouse=True)
def isolated_outputs(tmp_path, monkeypatch):
    monkeypatch.setattr(eval_raid, "OUT", tmp_path / "raid")
    monkeypatch.setattr(eval_raid, "SAMPLE_PATH", tmp_path / "raid" / "data" / "train-sample.parquet")


def raid_frame(n_domains=2, n_human=40, n_machine=40, seed=0):
    """A tiny RAID-shaped labelled frame: human and machine texts per domain, a few attacks."""
    rng = np.random.default_rng(seed)
    rows = []
    for d in range(n_domains):
        for attack in ("none", "homoglyph"):
            for i in range(n_human):
                rows.append({"id": f"h-{d}-{attack}-{i}", "model": "human", "decoding": np.nan,
                             "repetition_penalty": np.nan, "attack": attack, "domain": f"dom{d}"})
            for model in ("gpt4", "llama-chat"):
                for i in range(n_machine):
                    rows.append({"id": f"m-{d}-{attack}-{model}-{i}", "model": model, "decoding": "greedy",
                                 "repetition_penalty": "no", "attack": attack, "domain": f"dom{d}"})
    frame = pd.DataFrame(rows)
    frame["generation"] = [f"text {i} {rng.integers(1000)}" for i in range(len(frame))]
    return frame


# ---- names


def test_presets_expand_to_components():
    assert eval_raid.components_of("meld-v0.1") == ["meld-soup:meld-lora-soup-logo-control-s1"]
    assert eval_raid.components_of("ensemble-v0.1-extended") == [
        "desklib:desklib-lora-qkvf-r64-e8-extended-s1", "meld-soup:meld-lora-soup-all-s1"]
    assert eval_raid.components_of("desklib:x+meld:y") == ["desklib:x", "meld:y"]


@pytest.mark.parametrize("bad", ["radar:x", "desklib:", "meld:y+desklib:x", "desklib:a+meld:b+meld:c"])
def test_malformed_candidates_are_refused(bad):
    with pytest.raises(SystemExit):
        eval_raid.components_of(bad)


# ---- sample


def test_sample_caps_each_cell_and_keeps_more_humans(tmp_path):
    frame = raid_frame()
    csv = tmp_path / "train.csv"
    frame.to_csv(csv, index=False)

    sample = eval_raid.build_sample(csv, n=5, n_human=12, chunksize=50)

    sizes = sample.groupby(eval_raid.CELL, dropna=False).size()
    machine = sizes[sizes.index.get_level_values("model") != "human"]
    human = sizes[sizes.index.get_level_values("model") == "human"]
    assert (machine == 5).all() and (human == 12).all()
    assert list(sample["id"]) == sorted(sample["id"])


def test_sample_does_not_depend_on_chunking_or_row_order(tmp_path):
    frame = raid_frame()
    frame.to_csv(tmp_path / "a.csv", index=False)
    frame.sample(frac=1, random_state=1).to_csv(tmp_path / "b.csv", index=False)

    a = eval_raid.build_sample(tmp_path / "a.csv", n=5, n_human=12, chunksize=17)
    b = eval_raid.build_sample(tmp_path / "b.csv", n=5, n_human=12, chunksize=10_000)

    assert list(a["id"]) == list(b["id"])


# ---- scoring


def fake_detector(calls):
    def fn(texts):
        calls.append(len(texts))
        return [float(len(t)) for t in texts]
    return fn


def test_scoring_resumes_from_the_missing_chunks(tmp_path):
    frame = pd.DataFrame({"id": [f"id{i:03d}" for i in range(25)], "generation": ["x" * i for i in range(25)]})
    out = tmp_path / "scores"
    info = {"component": "desklib:r", "run_id": "abc", "temperature": 2.0}
    calls = []

    assert eval_raid.score_chunks(frame, fake_detector(calls), out, info, chunk_rows=10) == 3
    (out / "chunk-00001.parquet").unlink()
    calls.clear()
    assert eval_raid.score_chunks(frame, fake_detector(calls), out, info, chunk_rows=10) == 1
    assert calls == [10]


def test_scores_from_another_run_are_not_mixed_in(tmp_path):
    frame = pd.DataFrame({"id": ["a", "b"], "generation": ["x", "yy"]})
    out = tmp_path / "scores"
    eval_raid.score_chunks(frame, fake_detector([]), out, {"component": "c", "run_id": "one", "temperature": 1.0})
    with pytest.raises(SystemExit, match="run_id"):
        eval_raid.score_chunks(frame, fake_detector([]), out, {"component": "c", "run_id": "two", "temperature": 1.0})


def test_a_detector_returning_nan_stops_the_job(tmp_path):
    frame = pd.DataFrame({"id": ["a"], "generation": ["x"]})
    with pytest.raises(SystemExit, match="non-finite"):
        eval_raid.score_chunks(frame, lambda texts: [float("nan")], tmp_path / "s",
                               {"component": "c", "run_id": "r", "temperature": 1.0})


def write_scores(component, split, ids, logits, temperature, chunk_rows=3):
    frame = pd.DataFrame({"id": ids, "generation": [""] * len(ids)})
    it = iter(logits)
    eval_raid.score_chunks(frame, lambda texts: [next(it) for _ in texts], eval_raid.scores_dir(component, split),
                           {"component": component, "run_id": component, "temperature": temperature}, chunk_rows)


def test_an_unfinished_component_is_refused():
    write_scores("desklib:a", "test", ["x", "y", "z", "w"], [1.0, 2.0, 3.0, 4.0], 1.0)
    (eval_raid.scores_dir("desklib:a", "test") / "chunk-00001.parquet").unlink()
    with pytest.raises(SystemExit, match="unfinished"):
        eval_raid.load_logits("desklib:a", "test")


def test_a_pair_is_the_weighted_sum_of_calibrated_log_odds():
    ids = ["a", "b", "c", "d"]
    write_scores("desklib:d", "test", ids, [2.0, -2.0, 4.0, 0.0], temperature=2.0)
    write_scores("meld:m", "test", ids, [10.0, 0.0, -10.0, 5.0], temperature=5.0)

    single, _ = eval_raid.candidate_scores("desklib:d", "test", weight_meld=0.5)
    pair, metas = eval_raid.candidate_scores("desklib:d+meld:m", "test", weight_meld=0.5)

    assert np.allclose(single.loc[ids], [1.0, -1.0, 2.0, 0.0])
    assert np.allclose(pair.loc[ids], [1.5, -0.5, 0.0, 0.5])
    assert [m["temperature"] for m in metas] == [2.0, 5.0]


# ---- leaderboard files


def test_metadata_holds_only_keys_the_leaderboard_accepts():
    eval_raid.check_metadata({"date_released": "2026-11-09", "detector_name": "x", "contact_info": "c",
                              "github_link": "g", "additional_metadata": {}})
    with pytest.raises(SystemExit, match="rejects"):
        eval_raid.check_metadata({"date_released": "d", "detector_name": "x", "contact_info": "c", "trained_on": "v"})
    with pytest.raises(SystemExit, match="missing"):
        eval_raid.check_metadata({"date_released": "d", "detector_name": "x"})


def test_predictions_must_cover_the_test_set_exactly():
    z = pd.Series([0.1, 0.2], index=["a", "b"])
    eval_raid.check_predictions(z, ["b", "a"])
    with pytest.raises(SystemExit, match="1 test ids missing"):
        eval_raid.check_predictions(z, ["a", "b", "c"])
    with pytest.raises(SystemExit, match="finite"):
        eval_raid.check_predictions(pd.Series([np.inf, 0.0], index=["a", "b"]), ["a", "b"])


def test_submission_files_match_what_the_bot_reads(monkeypatch):
    ids = ["t1", "t2", "t3"]
    write_scores("desklib:d", "test", ids, [3.0, -1.0, 0.5], temperature=1.0)
    monkeypatch.setattr(eval_raid, "raid_csv", lambda name: None)
    monkeypatch.setattr(eval_raid.pd, "read_csv", lambda *a, **k: pd.DataFrame({"id": ids}))
    args = type("Args", (), dict(candidate="desklib:d", name="PP-desklib_v0.1", contact="me", date="2026-11-09",
                                 detector_name=None, website=None, paper_link=None, huggingface_link=None,
                                 github_link=None, weight_meld=0.5))()

    folder = eval_raid.submit(args)

    predictions = json.loads((folder / "predictions.json").read_text())
    assert predictions == [{"id": "t1", "score": 3.0}, {"id": "t2", "score": -1.0}, {"id": "t3", "score": 0.5}]
    metadata = json.loads((folder / "metadata.json").read_text())
    assert metadata["detector_name"] == "PP-desklib_v0.1" and metadata["additional_metadata"]["trained_on_raid"] is False


# ---- evaluate, with RAID's own code


def test_evaluate_runs_raids_metric_on_the_sample():
    pytest.importorskip("raid")
    frame = raid_frame(n_human=200, n_machine=50)
    eval_raid.SAMPLE_PATH.parent.mkdir(parents=True)
    frame.to_parquet(eval_raid.SAMPLE_PATH, index=False)
    rng = np.random.default_rng(0)
    # a good detector: machine texts score well above humans, except on the homoglyph attack
    machine = frame["model"].ne("human").to_numpy()
    attacked = frame["attack"].eq("homoglyph").to_numpy()
    logits = rng.normal(0, 1, len(frame)) + np.where(machine & ~attacked, 6.0, 0.0)
    write_scores("desklib:good", "train-sample", frame["id"].tolist(), logits.tolist(), temperature=1.0,
                 chunk_rows=100)

    table = eval_raid.evaluate(["desklib:good"], weight_meld=0.5).set_index("view")

    assert {"overall", "overall, no attacks", "domain: dom0", "attack: homoglyph"} <= set(table.index)
    assert table.loc["overall, no attacks", "tpr@0.05"] > 0.95
    assert table.loc["attack: homoglyph", "tpr@0.05"] < 0.3
    assert (eval_raid.OUT / "eval" / "summary.csv").exists()

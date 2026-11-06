"""render.py's pure logic: breaking-point detection, per-step stats, hand blocks, main().

Run (stdlib only, matplotlib not needed):
  docker run --rm -v "$PWD:/repo" -w /repo/apps/loadtest python:3.13-slim python -m unittest test_render -v
"""
import json
import tempfile
import unittest
from pathlib import Path

from render import find_points, main, merge_hand_blocks, step_stats


def s(rate, p95, err=0.0, n504=0, dropped=0):
    return {"rate_per_min": rate, "p95_ms": p95, "error_rate": err, "n504": n504, "dropped": dropped}


def row(metric, ts, value, step=None, scenario="checks", status="", kind="check"):
    return {"metric": metric, "ts": ts, "value": value, "scenario": scenario,
            "status": status, "kind": kind, "step": step}


class FindPoints(unittest.TestCase):
    def test_onset_is_first_step_with_doubled_p95(self):
        steps = [s(6, 800), s(15, 900), s(30, 1700)]
        self.assertEqual(find_points(steps)["onset"], 30)

    def test_breaking_on_any_504_even_if_p95_ok(self):
        self.assertEqual(find_points([s(6, 800), s(15, 900, n504=1)])["breaking"], 15)

    def test_breaking_on_dropped_or_errors_or_p95(self):
        self.assertEqual(find_points([s(6, 800), s(15, 900, dropped=3)])["breaking"], 15)
        self.assertEqual(find_points([s(6, 800), s(15, 900, err=0.02)])["breaking"], 15)
        self.assertEqual(find_points([s(6, 800), s(15, 10001)])["breaking"], 15)

    def test_never_breaks_returns_none(self):
        self.assertEqual(find_points([s(6, 800), s(15, 900)]), {"onset": None, "breaking": None})

    def test_first_step_already_broken(self):
        self.assertEqual(find_points([s(6, 12000)])["breaking"], 6)

    def test_step_without_successful_checks_is_broken(self):
        self.assertEqual(find_points([s(6, 800), s(15, None, err=1.0)])["breaking"], 15)


class StepStats(unittest.TestCase):
    def test_percentiles_errors_504_dropped_and_achieved_rate(self):
        rows = [
            # warm-up is never measured
            row("check_ok_duration", 0, 99999, scenario="warmup"),
            # step 0: two good checks over a 60 s window
            row("check_ok", 1000, 1, 0), row("check_ok_duration", 1000, 100, 0),
            row("http_reqs", 1000, 1, 0, status="201"),
            row("check_ok", 61000, 1, 0), row("check_ok_duration", 61000, 300, 0),
            row("http_reqs", 61000, 1, 0, status="201"),
            # step 1: one good, one fast 504 (must not count as latency)
            row("check_ok", 70000, 1, 1), row("check_ok_duration", 70000, 500, 1),
            row("http_reqs", 70000, 1, 1, status="201"),
            row("check_ok", 100000, 0, 1),
            row("http_reqs", 100000, 1, 1, status="504"),
            # dropped iterations carry no step tag: assigned by time
            row("dropped_iterations", 65000, 1, kind=""),
            row("dropped_iterations", 90000, 2, kind=""),
        ]
        st = step_stats(rows, [6, 15])
        self.assertEqual([x["step"] for x in st], [0, 1])
        a, b = st
        self.assertEqual(a["rate_per_min"], 6)
        self.assertEqual(a["p50_ms"], 200)
        self.assertEqual(a["error_rate"], 0)
        self.assertEqual(a["dropped"], 1)  # 65 s falls after step 0's window, before step 1's
        self.assertAlmostEqual(a["achieved_per_min"], 1.0)  # 2 completions = 1 interval in 60 s
        self.assertAlmostEqual(b["achieved_per_min"], 2.0)  # 1 interval in 30 s
        self.assertEqual(b["p95_ms"], 500)
        self.assertEqual(b["error_rate"], 0.5)
        self.assertEqual(b["n504"], 1)
        self.assertEqual(b["dropped"], 2)


class HandBlocks(unittest.TestCase):
    def test_hand_blocks_survive_regeneration(self):
        old = "x<!-- hand:verdict -->PASS, because…<!-- /hand:verdict -->y"
        new = "a<!-- hand:verdict -->TODO<!-- /hand:verdict -->b"
        self.assertEqual(merge_hand_blocks(old, new),
                         "a<!-- hand:verdict -->PASS, because…<!-- /hand:verdict -->b")

    def test_new_block_keeps_its_seed_when_old_lacks_it(self):
        new = "<!-- hand:discussion -->TODO<!-- /hand:discussion -->"
        self.assertEqual(merge_hand_blocks("nothing here", new), new)

    def test_orphaned_block_is_kept_and_survives_the_next_render(self):
        old = "<!-- hand:verdict -->v<!-- /hand:verdict --><!-- hand:gone -->my notes<!-- /hand:gone -->"
        new = "<!-- hand:verdict -->TODO<!-- /hand:verdict -->"
        once = merge_hand_blocks(old, new)
        self.assertIn("## Orphaned hand blocks", once)
        self.assertIn("<!-- hand:gone -->my notes<!-- /hand:gone -->", once)
        self.assertTrue(once.startswith("<!-- hand:verdict -->v<!-- /hand:verdict -->"))
        twice = merge_hand_blocks(once, new)
        self.assertEqual(twice, once)


class Main(unittest.TestCase):
    def test_main_tolerates_aborted_run_without_csv(self):
        with tempfile.TemporaryDirectory() as tmp:
            results = Path(tmp, "results")
            run = results / "20261022-120000_desklib_ramp-idle"
            run.mkdir(parents=True)
            (run / "meta.json").write_text(json.dumps({
                "run_id": run.name, "phase": "ramp-idle", "model": "desklib", "detector": "real",
                "status": "aborted", "status_reason": "stack failed to start", "quick": False,
            }))
            (results / "_scratch").mkdir()  # underscore dirs are ignored
            main(results_dir=results, out_dir=Path(tmp))
            text = Path(tmp, "RESULTS.md").read_text(encoding="utf-8")
            self.assertIn("## Excluded runs", text)
            self.assertIn(run.name, text)
            self.assertIn("stack failed to start", text)
            self.assertNotIn("_scratch", text)


class MainAws(unittest.TestCase):
    def render_aws(self, limits):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        run = Path(tmp.name, "results", "20261024-120000_desklib_headline-idle")
        run.mkdir(parents=True)
        (run / "meta.json").write_text(json.dumps({
            "run_id": run.name, "phase": "headline-idle", "model": "desklib", "detector": "real",
            "status": "ok", "quick": False, "target": "aws", "limits": limits,
            "host": {"os": "Linux", "instance_type": "t3.small", "region": "ap-southeast-1"},
        }))
        main(results_dir=run.parent, out_dir=Path(tmp.name))
        return Path(tmp.name, "RESULTS.md").read_text(encoding="utf-8")

    def test_method_aws(self):
        text = self.render_aws({"api_cpus": 0.5, "api_mem_mib": 1024, "detector_cpus": 2, "detector_mem_mib": 8192})
        self.assertIn("CloudFront", text)
        self.assertIn("t3.small", text)
        self.assertIn("api 0.5 vCPU / 1024 MiB", text)
        self.assertNotIn("Docker Compose", text)

    def test_limitations_aws(self):
        text = self.render_aws(None)  # failed limits collection must not crash
        self.assertIn("last-mile", text)
        self.assertIn("rate-writes", text)
        self.assertNotIn("tmpfs", text)


if __name__ == "__main__":
    unittest.main()

"""aws_collect.py's pure logic and main() (no real AWS: the CLI runner is patched).

Run (stdlib only):
  docker run --rm -v "$PWD:/repo" -w /repo/apps/loadtest python:3.13-slim python -m unittest test_aws_collect -v
"""
import contextlib
import io
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

import aws_collect
from aws_collect import detector_restarted, max_or_none, metric_rows

START = 1_800_000_000_000  # ms


def iso(ms):
    return datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat()


def ev(ms, msg="(service detector) has stopped 1 running tasks: (task abc)."):
    return {"createdAt": iso(ms), "message": msg}


class MetricRows(unittest.TestCase):
    def test_metric_rows_merges_by_timestamp(self):
        ts = [iso(START), iso(START + 60_000)]
        results = [{"Id": "api_cpu", "Timestamps": ts, "Values": [10.0, 20.0]},
                   {"Id": "api_mem", "Timestamps": ts, "Values": [30.0, 40.0]}]
        rows = metric_rows(results, {"api_cpu": ("api", "cpu_pct"), "api_mem": ("api", "mem_pct")})
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["name"], "api")
        self.assertEqual((rows[0]["cpu_pct"], rows[0]["mem_pct"]), (10.0, 30.0))
        self.assertEqual((rows[1]["cpu_pct"], rows[1]["mem_pct"]), (20.0, 40.0))

    def test_metric_rows_empty_results(self):
        self.assertEqual(metric_rows([], {}), [])


class Restart(unittest.TestCase):
    def test_restart_inside_window(self):
        self.assertTrue(detector_restarted([ev(START + 1000)], START, START + 60_000))

    def test_restart_before_window(self):
        self.assertFalse(detector_restarted([ev(START - 1000)], START, START + 60_000))


class MaxOrNone(unittest.TestCase):
    def test_max_or_none_no_rows(self):
        self.assertIsNone(max_or_none([], "loadgen", "cpu_pct"))


class Main(unittest.TestCase):
    def run_main(self, run_aws, tmp):
        out = io.StringIO()
        with mock.patch.object(aws_collect, "run_aws", side_effect=run_aws), \
                mock.patch.object(aws_collect, "wait_until"), \
                mock.patch.object(aws_collect, "instance_id", return_value="i-123"), \
                contextlib.redirect_stdout(out):
            aws_collect.main(["--run-dir", tmp, "--start-ms", str(START), "--end-ms", str(START + 1000)])
        return out.getvalue()

    def test_main_writes_header_only_on_no_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = self.run_main(lambda args: {}, tmp)
            self.assertEqual(Path(tmp, "stats.csv").read_text(encoding="utf-8").strip(),
                             "epoch_s,name,cpu_pct,mem_pct,mem_usage")
            self.assertEqual(sorted(p.name for p in Path(tmp).iterdir()), ["alb.csv", "stats.csv"])
        self.assertIn("LOADGEN_CPU_MAX,\n", out)
        self.assertIn("DETECTOR_RESTARTED,\n", out)  # no detector service read: unknown, not 0

    def test_failing_describe_services_leaves_restart_empty(self):
        def run_aws(args):
            return None if args[:2] == ["ecs", "describe-services"] else {}
        with tempfile.TemporaryDirectory() as tmp:
            out = self.run_main(run_aws, tmp)
        self.assertIn("DETECTOR_RESTARTED,\n", out)

    def test_detector_events_read_and_quiet_gives_zero(self):
        def run_aws(args):
            if args[:2] == ["ecs", "describe-services"]:
                return {"services": [{"taskDefinition": "td", "events": []}]}
            return {}
        with tempfile.TemporaryDirectory() as tmp:
            out = self.run_main(run_aws, tmp)
        self.assertIn("DETECTOR_RESTARTED,0\n", out)

    def test_main_with_data(self):
        sizes = {"td-api": ("512", "1024"), "td-worker": ("256", "512"), "td-detector": ("2048", "8192")}
        ts = [iso(START)]

        def run_aws(args):
            if args[:2] == ["cloudwatch", "get-metric-data"]:
                return {"MetricDataResults": [
                    {"Id": "loadgen_cpu_pct", "Timestamps": ts, "Values": [42.5]},
                    {"Id": "detector_cpu_pct", "Timestamps": ts, "Values": [180.0]},
                    {"Id": "alb_p95", "Timestamps": ts, "Values": [0.25]},  # seconds
                ]}
            if args[:2] == ["ecs", "describe-services"]:
                svc = args[args.index("--services") + 1]
                return {"services": [{"taskDefinition": f"td-{svc}", "events": [ev(START + 500)]}]}
            if args[:2] == ["ecs", "describe-task-definition"]:
                cpu, mem = sizes[args[args.index("--task-definition") + 1]]
                return {"taskDefinition": {"cpu": cpu, "memory": mem}}
            if args[:2] == ["logs", "filter-log-events"]:
                return {"events": [{}, {}]}
            return {}

        with tempfile.TemporaryDirectory() as tmp:
            out = self.run_main(run_aws, tmp)
            stats = Path(tmp, "stats.csv").read_text(encoding="utf-8")
            alb = Path(tmp, "alb.csv").read_text(encoding="utf-8")
        self.assertIn("WORKER_ROW_FAILURES,2\n", out)
        self.assertIn("LOADGEN_CPU_MAX,42.5\n", out)
        self.assertIn("DETECTOR_RESTARTED,1\n", out)
        limits = json.loads(out.split("LIMITS,", 1)[1])
        self.assertEqual(limits, {"api_cpus": 0.5, "api_mem_mib": 1024, "worker_cpus": 0.25, "worker_mem_mib": 512,
                                  "detector_cpus": 2, "detector_mem_mib": 8192})
        self.assertIn(f"{START // 1000},loadgen,42.5", stats)
        self.assertIn(f"{START // 1000},detector,180.0", stats)
        self.assertIn(f"{START // 1000},250.0,,", alb)  # p95 converted to ms


if __name__ == "__main__":
    unittest.main()

"""Collect CloudWatch/ECS/log data for one AWS load-test run (stdlib + `aws` CLI only).

Runs on the load-generator EC2 host after k6 finishes (env from /etc/loadtest.env):
  python3 aws_collect.py --run-dir DIR --start-ms N --end-ms N
Writes DIR/stats.csv and DIR/alb.csv; prints WORKER_ROW_FAILURES / LOADGEN_CPU_MAX /
DETECTOR_RESTARTED / LIMITS lines for run.sh to grep. Never exits non-zero on AWS errors.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

SETTLE_S = 180  # CloudWatch metrics land late
SERVICES = ("api", "worker", "detector")


def warn(msg: str) -> None:
    print(f"aws_collect: {msg}", file=sys.stderr)


def run_aws(args: list) -> Optional[dict]:
    """Run `aws ... --output json`; None (plus a warning) on any failure."""
    try:
        p = subprocess.run(["aws", *args, "--output", "json"], capture_output=True, text=True, timeout=300)
        if p.returncode != 0:
            warn(f"aws {' '.join(args[:2])} failed: {p.stderr.strip()[:300]}")
            return None
        return json.loads(p.stdout or "{}")
    except (OSError, subprocess.SubprocessError, ValueError) as e:
        warn(f"aws {' '.join(args[:2])} failed: {e}")
        return None


def instance_id() -> Optional[str]:
    """IMDSv2 (hop limit 1, so this must run on the host, not in a container)."""
    try:
        base = "http://169.254.169.254/latest"
        tok = urllib.request.urlopen(urllib.request.Request(
            base + "/api/token", method="PUT",
            headers={"X-aws-ec2-metadata-token-ttl-seconds": "60"}), timeout=3).read().decode()
        return urllib.request.urlopen(urllib.request.Request(
            base + "/meta-data/instance-id", headers={"X-aws-ec2-metadata-token": tok}),
            timeout=3).read().decode()
    except OSError as e:
        warn(f"IMDS lookup failed: {e}")
        return None


def wait_until(ms: int) -> None:
    time.sleep(max(0.0, ms / 1000 - time.time()))


def to_epoch_s(ts) -> float:
    """CLI timestamps are ISO strings (or epoch numbers)."""
    if isinstance(ts, (int, float)):
        return float(ts)
    return datetime.fromisoformat(str(ts).replace("Z", "+00:00")).timestamp()


def metric_rows(results: list, names: dict) -> list:
    """Merge MetricDataResults into one row per (timestamp, name); names: id -> (name, column)."""
    merged: dict = {}
    for r in results:
        if r.get("Id") not in names:
            continue
        name, col = names[r["Id"]]
        for ts, v in zip(r.get("Timestamps", []), r.get("Values", [])):
            t = int(to_epoch_s(ts))
            merged.setdefault((t, name), {"epoch_s": t, "name": name})[col] = v
    return [merged[k] for k in sorted(merged)]


def detector_restarted(events: list, start_ms: int, end_ms: int) -> bool:
    for e in events:
        ms = to_epoch_s(e.get("createdAt", 0)) * 1000
        msg = e.get("message", "")
        if start_ms <= ms <= end_ms and ("has stopped" in msg or "has started" in msg):
            return True
    return False


def max_or_none(rows: list, name: str, col: str) -> Optional[float]:
    vals = [r[col] for r in rows if r["name"] == name and r.get(col) is not None]
    return max(vals) if vals else None


def query(qid, ns, metric, dims, stat):
    return {"Id": qid, "ReturnData": True, "MetricStat": {
        "Metric": {"Namespace": ns, "MetricName": metric,
                   "Dimensions": [{"Name": k, "Value": v} for k, v in dims.items()]},
        "Period": 60, "Stat": stat}}


def fetch_metrics(start_ms: int, end_ms: int, cluster: str, alb: str, inst: Optional[str]):
    """One get-metric-data call -> (stats id map, alb id map, results), or None on failure."""
    queries, stats_names, alb_names = [], {}, {}
    for svc in SERVICES:
        dims = {"ClusterName": cluster, "ServiceName": svc}
        for metric, col in (("CPUUtilization", "cpu_pct"), ("MemoryUtilization", "mem_pct")):
            qid = f"{svc}_{col}"
            queries.append(query(qid, "AWS/ECS", metric, dims, "Maximum"))
            stats_names[qid] = (svc, col)
    if inst:
        queries.append(query("loadgen_cpu_pct", "AWS/EC2", "CPUUtilization", {"InstanceId": inst}, "Maximum"))
        stats_names["loadgen_cpu_pct"] = ("loadgen", "cpu_pct")
    for qid, metric, stat, col in (
        ("alb_p95", "TargetResponseTime", "p95", "target_response_p95_ms"),
        ("alb_t5xx", "HTTPCode_Target_5XX_Count", "Sum", "target_5xx"),
        ("alb_e5xx", "HTTPCode_ELB_5XX_Count", "Sum", "elb_5xx"),
    ):
        queries.append(query(qid, "AWS/ApplicationELB", metric, {"LoadBalancer": alb}, stat))
        alb_names[qid] = ("alb", col)

    def iso(ms):
        return datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # temp file lives outside the run dir and is deleted on exit
    with tempfile.TemporaryDirectory() as tmp:
        f = Path(tmp, "q.json")
        f.write_text(json.dumps({"MetricDataQueries": queries, "StartTime": iso(start_ms),
                                 "EndTime": iso(end_ms)}), encoding="utf-8")
        out = run_aws(["cloudwatch", "get-metric-data", "--cli-input-json", f"file://{f}"])
    if out is None:
        return None
    return stats_names, alb_names, out.get("MetricDataResults", [])


def task_limits(cluster: str) -> tuple:
    """(detector service events, or None if unread; LIMITS dict) from DescribeServices/DescribeTaskDefinition."""
    limits, det_events = {}, None
    for svc in SERVICES:
        out = run_aws(["ecs", "describe-services", "--cluster", cluster, "--services", svc])
        svcs = (out or {}).get("services") or []
        if not svcs:
            continue
        if svc == "detector":
            det_events = svcs[0].get("events", [])
        td = run_aws(["ecs", "describe-task-definition", "--task-definition", svcs[0].get("taskDefinition", "")])
        td = (td or {}).get("taskDefinition")
        if td:
            cpu = int(td["cpu"]) / 1024
            limits[f"{svc}_cpus"] = int(cpu) if cpu == int(cpu) else cpu
            limits[f"{svc}_mem_mib"] = int(td["memory"])
    return det_events, limits


def count_worker_row_failures(group: str, start_ms: int, end_ms: int) -> Optional[int]:
    # CLI v2 auto-paginates filter-log-events, so one call returns every page
    out = run_aws(["logs", "filter-log-events", "--log-group-name", group,
                   "--start-time", str(start_ms), "--end-time", str(end_ms),
                   "--filter-pattern", '"Failed to process batch row"'])
    return None if out is None else len(out.get("events", []))


def write_csv(path: Path, header: list, rows: list) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=header, restval="", extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--start-ms", type=int, required=True)
    ap.add_argument("--end-ms", type=int, required=True)
    a = ap.parse_args(argv)
    env = os.environ.get
    run_dir = Path(a.run_dir)

    wait_until(a.end_ms + SETTLE_S * 1000)
    fetched = fetch_metrics(a.start_ms, a.end_ms, env("LOADTEST_CLUSTER", ""),
                            env("LOADTEST_ALB_SUFFIX", ""), instance_id())
    stats, alb = [], []
    if fetched:
        stats_names, alb_names, results = fetched
        stats = metric_rows(results, stats_names)
        alb = metric_rows(results, alb_names)
        for r in alb:  # TargetResponseTime is in seconds
            if r.get("target_response_p95_ms") is not None:
                r["target_response_p95_ms"] *= 1000
    write_csv(run_dir / "stats.csv", ["epoch_s", "name", "cpu_pct", "mem_pct", "mem_usage"], stats)
    write_csv(run_dir / "alb.csv", ["epoch_s", "target_response_p95_ms", "target_5xx", "elb_5xx"], alb)

    failures = count_worker_row_failures(env("LOADTEST_WORKER_LOG_GROUP", ""), a.start_ms, a.end_ms)
    det_events, limits = task_limits(env("LOADTEST_CLUSTER", ""))
    cpu_max = max_or_none(stats, "loadgen", "cpu_pct")
    print(f"WORKER_ROW_FAILURES,{'' if failures is None else failures}")
    print(f"LOADGEN_CPU_MAX,{'' if cpu_max is None else cpu_max}")
    # Empty, not 0, when the detector's events couldn't be read: run.sh must not fail open.
    restarted = "" if det_events is None else int(detector_restarted(det_events, a.start_ms, a.end_ms))
    print(f"DETECTOR_RESTARTED,{restarted}")
    print(f"LIMITS,{json.dumps(limits)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

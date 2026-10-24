# PP-533 load test — experiment log

Lab notebook for the load test, oldest first. Two kinds of entries:

- **Hand-written** (under `## Notes`): predictions written *before* a phase runs,
  decisions and why, surprises, things that went wrong.
- **Automatic** (under `## Runs`): `run.sh` appends one line per run when it
  finishes. Never edit or delete these; a bad run is flagged in its
  `results/<run-id>/meta.json` (`status`), not removed.

## Notes

### Entry 0 — 2026-10-22: what we know before the first run

**AWS observation (CloudWatch, 2026-10-19 17:07:59 UTC, desklib, batch
`3f2baaf3`).** 340 rows uploaded, 8 rejected at parse, 332 detector calls all
200. Drained 17:08:00 → 17:12:46 (~286 s). Per-row gap p50 0.84 s / p95 1.08 s /
max 1.53 s, so S ≈ 0.84 s per row including worker overhead. The UI showed 322
processed; the 10-row gap is unexplained (no worker errors logged) and tracked
separately, not part of this test.

**Initial prediction (desklib).** If one inference takes S ≈ 0.84 s and the
detector scores one request at a time, capacity is C = 1/S ≈ 1.2 req/s
(~71 req/min).

- Idle (single checks only): breaking point a little under 1.2 req/s.
- Under a draining batch: roughly half, ~0.5–0.6 req/s. The sequential worker
  always has one row waiting, so once single checks queue it takes about half
  of the detector.

To be refined with the measured S after `run.sh calibrate`, before the ramps.

**Decision — WSL memory (2026-10-22).** No `.wslconfig` change. Docker has
7.1 GB; desklib's fit is measured (memory-pressure guard in `run.sh`), not
assumed. If desklib doesn't fit: either a temporary `.wslconfig` raise, or
desklib on AWS only. *(Superseded by Entry 1.)*

### Entry 1 — 2026-10-23: the measured runs move to AWS

**Decision (user).** No more local experiment runs. The local stack shares one
laptop between k6, the API, the worker, the detector, Postgres and LocalStack, so a
local breaking point measures the laptop, not the product. Its detector CPU, the
edge path (CloudFront, WAF, ALB), RDS, real SQS and real Auth0 sessions all
differ from production, and a QUICK stub dry-run was killed for low memory on
2026-10-22. Every measured phase (calibrate → ramps → headline → freeze) runs
against the AWS deployment before go-live instead. That deployment is the only
environment and stands in for staging until launch. See the AWS spec.

What stays local: `run.sh smoke` (stub detector), as a check that the harness
still works before a session on AWS. The 7 stub dry-run directories from
2026-10-22 (3 smoke, 2 calibrate, 2 aborted ramp-idle) were harness rehearsals,
not data, and were deleted with their `## Runs` lines. `run.sh` and the local
stack no longer support the real model or the memory guard.

### Entry 2 — 2026-10-24: prediction before the ramps

Calibrate (`20261024-035532_desklib_calibrate`): S = 0.909 s, p95 1.10 s, so
C ≈ 66 checks/min on one detector task (2 vCPU). S is end to end, so the
detector's own capacity is slightly above 66.

**ramp-idle.** Arrivals are evenly spaced and service time is nearly constant,
so I expect almost no queueing below C:

- 7–53/min (≤ 0.8C): flat, p95 ≈ 1.1–1.3 s.
- **Onset at 59–66/min (0.9–1.0C):** p95 rises to roughly 1.5–3 s as checks
  begin to overlap and share the 2 vCPU (the detector runs inference in a
  threadpool with no lock).
- **Break at 73/min (1.1C):** about 7 checks/min more than C arrive. Over a
  2-minute plateau that is a backlog of ~14 checks × 0.9 s ≈ 13 s, so
  p95 > 10 s (NFR3 fails) and the API's 10 s detector timeouts start.
- 83/min (1.25C): collapse. Timed-out checks still use detector CPU, so
  successful throughput falls *below* C and most requests fail.

**ramp-batch.** The worker sends batch rows to the same detector, so the batch
takes part of C away from single checks. I expect onset and break to move about
one step lower each: onset ~0.65–0.8C, break ~0.9–1.0C.

**What would prove this wrong:** if one inference doesn't use both vCPU,
overlapping checks run in parallel and C is effectively higher than 66. Then
the ramp shows no onset until 1.1–1.25C. That is a finding about the
detector's concurrency in its own right.

### Entry 3 — 2026-10-24: what the two sittings found

**Prediction vs. ramps.** Idle held almost exactly: flat to 59/min, a small rise
at 66 (p95 1.44 s), break at 73 (p95 9.05 s, 33% errors), and at 83/min every
check timed out while the detector kept completing work. Under batch, onset 53
and break 66, inside the predicted range. Not predicted: the batch costs ~45%
latency even at 7/min (p50 1.33 s vs 0.91 s), and 33 batch rows failed on the
first pass at the top steps (all succeeded on retry, DLQ stayed at 0).

**Rate choice.** R = 40/min = 60% of the under-batch breaking point (66), below
onset (53), leaving ~40% headroom for bursts that k6's evenly spaced arrivals
don't model. Plus one stress run at R = 53 (onset), kept apart in
`results/_stress/` so it never enters the AC4 medians.

**Headline at R = 40.** Idle: p95 1.05–1.07 s over 3 runs. Loaded: p95
2.65–2.71 s, 0 errors, 0 504s, 0 failed rows over 3 runs; one 500-row batch
drains in ~1,017 s (~29 rows/min). The 2-minute ramp plateau predicted the
full drain well (expected ~2.5 s).

**Stress at R = 53** (`_stress/20261024-080436_desklib_headline-loaded`): p95
5.0 s, 0 errors over a 1,884 s drain. Still inside NFR3 at onset, but the batch
takes almost twice as long, since checks take most of the detector.

**Freeze.** `POST /api/batches` took 19–21 s on all 5 submissions. While it
ran, the API's event loop was blocked: the `/api/detector` probe had p95
18.2 s, max 20.2 s (`20261024-075221_desklib_freeze`). Checks caught in that
window took up to ~21 s and one got a 504 (k6's all-checks p95 11.1 s;
successful-checks p95 8.3 s, the figure RESULTS.md uses). The detector holds
under batch load; submitting the batch is what fails.

**Detector uses one of its two vCPU.** CloudWatch detector CPU peaked at ~51%
of the task's reservation in every ramp, including the 83/min step where every
check timed out. Memory peaked at ~37% of 8 GB. So C ≈ 66/min is a one-core
number. Suspected cause (not yet confirmed): PyTorch's default thread count
on Fargate's hyperthreaded vCPU. `desklib.py` never sets it.

**Fargate CPU vs. EC2 GPU.** Not justified now: S = 0.91 s against NFR3's
10 s, and capacity is ~4× the placeholder demand (12/min, still to confirm
with the sponsor). Cheaper levers come first: use both cores, then scale the
detector to more tasks.

**Next.** (1) Fix `create_batch` blocking the event loop, then re-run freeze and
headline-loaded with `--variant async` (Phase 6). (2) Confirm the detector's
thread count, use both cores, re-run calibrate and ramp-idle. (3) Get the real
demand figure.

## Runs
- 2026-10-23T16:24Z `20261023-162238_stub_smoke` smoke stub sync **ok** p50=13.8 p95=40.5 err=0.0% 504=0 drain=5s
- 2026-10-23T17:00Z `20261023-165833_stub_smoke` smoke stub sync **ok** p50=13.6 p95=38.7 err=0.0% 504=0 drain=5s
- 2026-10-24T03:07Z `20261024-030558_stub_smoke` smoke stub sync **ok** p50=13.7 p95=52.9 err=0.0% 504=0 drain=5s
- 2026-10-24T03:46Z `20261024-034033_desklib_ramp-idle` ramp-idle desklib sync **ok** p50=1026.0 p95=6667.9 err=0.0% 504=0 drain=-
- 2026-10-24T04:01Z `20261024-035532_desklib_calibrate` calibrate desklib sync **ok** p50=908.6 p95=1100.3 err=0.0% 504=0 drain=-
- 2026-10-24T04:41Z `20261024-041736_desklib_ramp-idle` ramp-idle desklib sync **ok** p50=1031.7 p95=10021.0 err=24.8% 504=232 drain=-
- 2026-10-24T05:09Z `20261024-044353_desklib_ramp-batch` ramp-batch desklib sync **ok** p50=7776.4 p95=10023.7 err=45.2% 504=422 drain=-,-,-,-
- 2026-10-24T06:09Z `20261024-055542_desklib_headline-idle` headline-idle desklib sync **ok** p50=907.6 p95=1052.9 err=0.0% 504=0 drain=-
- 2026-10-24T06:24Z `20261024-060952_desklib_headline-idle` headline-idle desklib sync **ok** p50=905.0 p95=1048.1 err=0.0% 504=0 drain=-
- 2026-10-24T06:38Z `20261024-062400_desklib_headline-idle` headline-idle desklib sync **ok** p50=905.7 p95=1072.9 err=0.0% 504=0 drain=-
- 2026-10-24T07:02Z `20261024-063810_desklib_headline-loaded` headline-loaded desklib sync **ok** p50=2064.7 p95=2651.7 err=0.0% 504=0 drain=1015s
- 2026-10-24T07:27Z `20261024-070253_desklib_headline-loaded` headline-loaded desklib sync **ok** p50=2086.7 p95=2660.5 err=0.0% 504=0 drain=1016s
- 2026-10-24T07:52Z `20261024-072737_desklib_headline-loaded` headline-loaded desklib sync **ok** p50=2103.1 p95=2710.1 err=0.0% 504=0 drain=1020s
- 2026-10-24T08:00Z `20261024-075221_desklib_freeze` freeze desklib sync **ok** p50=2187.9 p95=11115.4 err=0.6% 504=1 drain=-
- 2026-10-24T08:47Z `20261024-080436_desklib_headline-loaded` headline-loaded desklib sync **ok** p50=4022.1 p95=5023.0 err=0.0% 504=0 drain=1884s

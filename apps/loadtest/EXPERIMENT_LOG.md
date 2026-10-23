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

## Runs
- 2026-10-23T16:24Z `20261023-162238_stub_smoke` smoke stub sync **ok** p50=13.8 p95=40.5 err=0.0% 504=0 drain=5s

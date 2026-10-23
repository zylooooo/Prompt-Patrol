#!/usr/bin/env bash
# PP-533 load test entry point: fresh stack -> seed session -> k6 phase -> collect -> down -v.
# Needs only Docker (Compose v2) and bash; runs in Git Bash on Windows and on Linux.
# See README.md for the phases and how to read the results.
#
#   run.sh <phase> [--model baseline|desklib] [--rate PER_MIN] [--runs N]
#                  [--variant sync|async] [--service-time S]
#
# The local stack runs only `smoke` (stub detector, harness check). The measured
# phases target AWS; see EXPERIMENT_LOG.md Entry 1 and the AWS spec.
set -euo pipefail
export MSYS_NO_PATHCONV=1
export LC_ALL=C  # awk/printf decimals go into meta.json; a comma locale would break the JSON

HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"
PROJECT=prompt-patrol-loadtest
PHASES="smoke calibrate ramp-idle ramp-batch headline-idle headline-loaded freeze render"
BATCH_SEED=533
STEP_FRACTIONS="0.1 0.25 0.5 0.65 0.8 0.9 1.0 1.1 1.25"

die() { echo "run.sh: $*" >&2; exit 1; }

phase="${1:-}"
[[ " $PHASES " == *" $phase "* ]] || die "usage: run.sh <$(echo "$PHASES" | tr ' ' '|')> [options], see README.md"
[[ "$phase" == smoke || "$phase" == render ]] ||
  die "$phase measures the deployment, not this laptop; locally only 'smoke' and 'render' run (EXPERIMENT_LOG.md Entry 1)"
shift
model=desklib rate="" runs=1 variant=sync service_time=""
detector=stub  # the local stack only ever runs the e2e stub
while [[ $# -gt 0 ]]; do
  case "$1" in
    --model) model="$2"; shift 2 ;;
    --rate) rate="$2"; shift 2 ;;
    --runs) runs="$2"; shift 2 ;;
    --variant) variant="$2"; shift 2 ;;
    --service-time) service_time="$2"; shift 2 ;;
    *) die "unknown option $1" ;;
  esac
done
[[ "$model" == baseline || "$model" == desklib ]] || die "--model must be baseline or desklib"
[[ "$variant" == sync || "$variant" == async ]] || die "--variant must be sync or async"
# These go into meta.json unquoted, so they must be plain numbers.
[[ -z "$rate" || "$rate" =~ ^[0-9]+([.][0-9]+)?$ ]] || die "--rate must be a number (req/min)"
[[ -z "$service_time" || "$service_time" =~ ^[0-9]+([.][0-9]+)?$ ]] || die "--service-time must be a number (s)"
[[ "$runs" =~ ^[1-9][0-9]*$ ]] || die "--runs must be a positive integer"

compose() { docker compose -p "$PROJECT" -f docker-compose.yml "$@"; }

if [[ "$phase" == render ]]; then
  compose --profile tools run --rm tools sh -c "pip install -q --root-user-action=ignore --disable-pip-version-check matplotlib==3.10.7 && python render.py"
  exit $?
fi

# Each run gets its own fresh stack, so --runs N re-invokes this script N times.
if [[ "$runs" -gt 1 ]]; then
  worst=0
  for ((i = 1; i <= runs; i++)); do
    echo "=== run $i/$runs ==="
    args=("$phase" --model "$model" --variant "$variant")
    [[ -n "$rate" ]] && args+=(--rate "$rate")
    [[ -n "$service_time" ]] && args+=(--service-time "$service_time")
    rc=0; bash "$0" "${args[@]}" || rc=$?
    [[ $rc -eq 130 ]] && exit 130  # Ctrl-C stops the series, not just this run
    [[ $rc -gt $worst ]] && worst=$rc
  done
  exit "$worst"
fi

# ---- preflight -------------------------------------------------------------
docker compose version >/dev/null 2>&1 || die "Docker Compose v2 not found (is Docker running?)"
leftover="$(docker ps -a --filter "label=com.docker.compose.project=$PROJECT" --format '{{.Names}}'
  docker volume ls --filter "label=com.docker.compose.project=$PROJECT" --format 'volume {{.Name}}')"
if [[ -n "$leftover" ]]; then
  echo "run.sh: a $PROJECT stack is already present (crashed run?):" >&2
  echo "$leftover" | sed 's/^/  /' >&2
  die "measure on a fresh stack only. Remove it with: docker compose -p $PROJECT down -v"
fi

label="$model"; [[ "$detector" == stub ]] && label=stub

# S: --service-time, else the newest ok, full-length calibrate run for this model.
needs_s() { [[ "$phase" == ramp-* || "$phase" == headline-loaded ]]; }
if needs_s && [[ -z "$service_time" ]]; then
  for d in $(ls -d results/*_"${label}"_calibrate 2>/dev/null | sort -r); do
    if grep -q '"status": "ok"' "$d/meta.json" 2>/dev/null && grep -q '"quick": false' "$d/meta.json"; then
      service_time="$(sed -n 's/.*"service_time_s": \([0-9.]*\).*/\1/p' "$d/meta.json")"
      [[ -n "$service_time" ]] && { echo "Using S=${service_time}s from $d"; break; }
    fi
  done
  [[ -n "$service_time" ]] || die "no ok calibrate run for $label; run 'run.sh calibrate --model $model' or pass --service-time"
fi
[[ "$phase" == headline-* || "$phase" == freeze ]] && [[ -z "$rate" ]] && die "$phase needs --rate PER_MIN"

quick="${QUICK:-0}"
scale=1; [[ "$quick" == 1 ]] && scale=10
batches=0 batch_rows=500 duration_s=""
case "$phase" in
  smoke) batches=1; batch_rows=20 ;;
  ramp-batch) batches="$(awk -v s="$service_time" -v q="$scale" 'BEGIN { x = (60 + 9 * 130 / q) / (500 * s); c = int(x); if (c < x) c++; print c + 1 }')" ;;
  headline-loaded)
    batches=1
    duration_s="$(awk -v s="$service_time" -v r="$rate" -v q="$scale" 'BEGIN {
      d = 1 - r / 60 * s; if (d < 0.2) d = 0.2; x = 500 * s / d / q; c = int(x); if (c < x) c++; print c + int(60 / q) }')" ;;
  freeze) batches=1 ;;
esac

# ---- run -------------------------------------------------------------------
run_id="$(date -u +%Y%m%d-%H%M%S)_${label}_${phase}"
RUN_DIR="$HERE/results/$run_id"
# Created here, world-writable: on Linux the k6 container (non-root) writes into it,
# and docker would otherwise create a missing bind source as root.
mkdir -p "$RUN_DIR" && chmod 777 "$RUN_DIR"
export RUN_DIR
started_utc="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
status=ok status_reason="" k6_rc="" model_version="" stack_up=0 finished=0

write_meta() {
  local steps git_sha git_dirty cpu_model ncpu mem k6v worker_timeouts=null
  steps="$(grep -o '^STEP,[0-9]*,[0-9]*' "$RUN_DIR/k6.log" 2>/dev/null | cut -d, -f3 | paste -sd, - || true)"
  git_sha="$(git rev-parse HEAD 2>/dev/null || echo unknown)"
  # Dirty = code differs from git_sha; the results and the log this script writes don't count.
  git_dirty=false
  [[ -n "$(git status --porcelain 2>/dev/null | grep -vE 'apps/loadtest/(results/|EXPERIMENT_LOG\.md)' || true)" ]] && git_dirty=true
  cpu_model="$(sed -n 's/^model name[[:space:]]*: //p' /proc/cpuinfo 2>/dev/null | head -1 | tr -d '"\\')"
  ncpu="$(docker info --format '{{.NCPU}}' 2>/dev/null || echo null)"
  mem="$(docker info --format '{{.MemTotal}}' 2>/dev/null || echo null)"
  k6v="$(docker run --rm grafana/k6:2.3.0 version 2>/dev/null | awk '{print $2; exit}')"
  [[ -f "$RUN_DIR/.worker_timeouts" ]] && worker_timeouts="$(cat "$RUN_DIR/.worker_timeouts")" && rm -f "$RUN_DIR/.worker_timeouts"
  cat >"$RUN_DIR/meta.json" <<EOF
{
  "run_id": "$run_id",
  "phase": "$phase",
  "model": "$model",
  "model_version": "${model_version:-unknown}",
  "variant": "$variant",
  "detector": "$detector",
  "status": "$status",
  "status_reason": "$status_reason",
  "git_sha": "$git_sha",
  "git_dirty": $git_dirty,
  "quick": $([[ "$quick" == 1 ]] && echo true || echo false),
  "rate_per_min": ${rate:-null},
  "service_time_s": ${service_time:-null},
  "steps_per_min": [${steps}],
  "batches": $batches,
  "batch_rows": $batch_rows,
  "batch_seed": $BATCH_SEED,
  "duration_s": ${duration_s:-null},
  "limits": {"detector_cpus": null, "api_cpus": 0.5, "worker_cpus": 0.25, "k6_cpus": 1, "detector_threads": null},
  "host": {"os": "$(uname -s)", "cpu_model": "$cpu_model", "ncpu": $ncpu, "docker_mem_bytes": $mem},
  "k6_version": "${k6v:-unknown}",
  "started_utc": "$started_utc",
  "ended_utc": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "k6_exit_code": ${k6_rc:-null},
  "worker_timeouts": $worker_timeouts
}
EOF
}

# BATCH_SUBMIT,<id>,<epoch_ms>,<post_ms> and BATCH_STATE,<id>,<epoch_ms>,<completed>,<failed>,<pending>
write_batches() {
  echo "batch_id,submit_epoch_ms,submit_ms,drain_end_epoch_ms,completed,failed,pending_at_end" >"$RUN_DIR/batches.csv"
  awk -F, '
    /^BATCH_SUBMIT,/ { order[++n] = $2; sub_t[$2] = $3; sub_ms[$2] = $4 }
    /^BATCH_STATE,/  { c[$2] = $4; f[$2] = $5; p[$2] = $6; if ($6 == 0 && !($2 in drain)) drain[$2] = $3 }
    END { for (i = 1; i <= n; i++) { b = order[i]; print b "," sub_t[b] "," sub_ms[b] "," drain[b] "," c[b] "," f[b] "," p[b] } }
  ' "$RUN_DIR/k6.log" >>"$RUN_DIR/batches.csv" 2>/dev/null || true
}

log_line() {
  local s p50="" p95="" err="" n504="" drain=""
  s="$(grep '^SUMMARY,' "$RUN_DIR/k6.log" 2>/dev/null | tail -1 || true)"
  [[ -n "$s" ]] && IFS=, read -r _ p50 p95 _ err n504 <<<"$s"
  # One drain time per batch, comma-separated (ramp-batch submits several).
  drain="$(awk -F, 'NR > 1 { d = ($4 == "") ? "-" : sprintf("%.0fs", ($4 - $2) / 1000); out = out (out == "" ? "" : ",") d } END { print out }' "$RUN_DIR/batches.csv" 2>/dev/null || true)"
  printf -- '- %s `%s` %s %s %s **%s** p50=%s p95=%s err=%s%% 504=%s drain=%s%s\n' \
    "$(date -u +%Y-%m-%dT%H:%MZ)" "$run_id" "$phase" "$label" "$variant" "$status" \
    "${p50:-?}" "${p95:-?}" "${err:-?}" "${n504:-?}" "${drain:--}" "${status_reason:+ ($status_reason)}" >>"$HERE/EXPERIMENT_LOG.md"
}

finish() {
  local rc=$?
  [[ "$finished" == 1 ]] && return
  finished=1
  trap '' INT TERM
  set +e  # collect and tear down no matter what fails in here
  [[ -z "$k6_rc" && "$status" == ok ]] && { status=aborted; status_reason="${status_reason:-interrupted or failed before k6 finished (exit $rc)}"; }
  if [[ "$stack_up" == 1 ]]; then
    compose logs worker 2>/dev/null | grep -c "Failed to process batch row" >"$RUN_DIR/.worker_timeouts" || true
  fi
  [[ -f "$RUN_DIR/k6.log" ]] && write_batches
  # ramp-batch is only valid if the worker was still busy when the last step started.
  if [[ "$phase" == ramp-batch && "$status" == ok ]]; then
    local t0 last_start
    t0="$(grep -o '^T0,[0-9]*' "$RUN_DIR/k6.log" | cut -d, -f2 | head -1)"
    last_start=$(( t0 + (60 + 8 * 130 / scale) * 1000 ))
    if awk -F, -v ls="$last_start" 'NR > 1 { n++; if ($4 != "" && $4 < ls) d++ } END { exit !(n > 0 && d == n) }' "$RUN_DIR/batches.csv"; then
      status=invalid; status_reason="queue drained before last step"
    fi
  fi
  if [[ "$phase" == headline-loaded && "$status" == ok ]] && awk -F, 'NR == 2 && $4 == "" { f = 1 } END { exit !f }' "$RUN_DIR/batches.csv"; then
    status_reason="${status_reason:+$status_reason; }window ended before drain"
  fi
  write_meta
  [[ -f "$RUN_DIR/requests.csv" ]] && gzip -f "$RUN_DIR/requests.csv"
  log_line
  echo "Tearing down $PROJECT..."
  compose --profile tools down -v --remove-orphans >/dev/null 2>&1 || true
  echo "Run dir: $RUN_DIR  status: $status${status_reason:+ ($status_reason)}"
  # A run that k6 passed but this script flagged (invalid, aborted) exits 3.
  [[ "$status" != ok && $rc -eq 0 ]] && exit 3
  return 0
}
trap finish EXIT
trap 'status=aborted; status_reason="interrupted"; exit 130' INT TERM

echo "Starting $PROJECT ($label, $phase)..."
stack_up=1
compose up -d --build --wait || { status=aborted; status_reason="stack failed to start"; exit 1; }
model_version="$(compose exec -T api curl -s http://detector:8001/health | sed -n 's/.*"model_version": *"\([^"]*\)".*/\1/p')"

compose --profile tools run --rm -T tools python make_batch_csv.py \
  --rows "$batch_rows" --seed "$BATCH_SEED" --out-dir "/repo/apps/loadtest/results/$run_id" >/dev/null

# Token lives only in this variable and the k6 container's env (passed by name, not value).
SESSION_TOKEN="$(compose exec -T api python -m scripts.e2e_seed 2>/dev/null | tail -1)"
[[ -n "$SESSION_TOKEN" ]] || { status=aborted; status_reason="session seed failed"; exit 1; }
export SESSION_TOKEN

export PHASE="$phase" RATE_PER_MIN="${rate:-}" SERVICE_TIME_S="${service_time:-}" BATCHES="$batches" \
  DURATION_S="${duration_s:-}" QUICK="$quick" \
  K6_WEB_DASHBOARD=true K6_WEB_DASHBOARD_EXPORT=/results/dashboard.html \
  K6_CSV_TIME_FORMAT=unix_milli  # default is whole seconds, too coarse for the timelines
set +e
compose --profile tools run --rm -T \
  -e PHASE -e SESSION_TOKEN -e RATE_PER_MIN -e SERVICE_TIME_S -e BATCHES -e DURATION_S -e QUICK \
  -e K6_WEB_DASHBOARD -e K6_WEB_DASHBOARD_EXPORT -e K6_CSV_TIME_FORMAT \
  k6 run --quiet --log-format=raw --out csv=/results/requests.csv /loadtest/checks.ts 2>&1 | tee "$RUN_DIR/k6.log"
k6_rc=${PIPESTATUS[0]}
set -e
# Guard: the session token must never reach a results file. Checked without printing it.
if grep -rqF -- "$SESSION_TOKEN" "$RUN_DIR"; then
  echo "run.sh: session token found in $RUN_DIR; do not commit this run" >&2
  status=invalid status_reason="session token found in results"
fi
unset SESSION_TOKEN

case "$k6_rc" in
  0) ;;
  99) grep -q "stopping test prematurely" "$RUN_DIR/k6.log" && status_reason="safety abort (error rate > 50%)" ;;
  *) status=aborted; status_reason="k6 exit $k6_rc" ;;
esac

if [[ "$phase" == calibrate ]]; then
  s="$(grep -o '^CAL_S,[0-9.]*' "$RUN_DIR/k6.log" | cut -d, -f2 | tail -1 || true)"
  if [[ -n "$s" ]]; then
    service_time="$s"
    echo
    awk -v s="$s" -v fr="$STEP_FRACTIONS" 'BEGIN {
      printf "S = %.3f s  ->  capacity C = 1/S = %.2f req/s = %.1f req/min\n", s, 1 / s, 60 / s
      n = split(fr, f, " "); printf "Ramp steps (req/min):"
      for (i = 1; i <= n; i++) { r = int(f[i] * 60 / s + 0.5); if (r < 1) r = 1; printf " %s×C=%d", f[i], r }
      print "\nWrite your Phase 2 prediction in EXPERIMENT_LOG.md before running ramp-idle."
    }'
  else
    status=aborted; status_reason="calibrate produced no CAL_S"
  fi
fi
exit "$k6_rc"

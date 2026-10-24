#!/usr/bin/env bash
# Tests for run.sh's --target aws path and `pack` (no framework, no AWS, no k6):
#   bash apps/loadtest/test_run_sh.sh
# run.sh runs from a throwaway copy of the repo layout, with fake curl/aws/docker/
# python3 first on PATH, so no results or log lines land in the real tree.
set -uo pipefail
SRC="$(cd "$(dirname "$0")" && pwd)"
T="$(mktemp -d)"
trap 'rm -rf "$T"' EXIT
REPO="$T/repo"
LT="$REPO/apps/loadtest"
mkdir -p "$T/bin" "$LT/figures" "$REPO/docs/assets"
cp "$SRC/run.sh" "$LT/"
echo "answer_text" >"$REPO/docs/assets/trial-data.csv"
echo x >"$LT/figures/fig.png"
cat >"$T/loadtest.env" <<'EOF'
LOADTEST_BASE_URL=https://app.example.test
LOADTEST_CLUSTER=pp-cluster
LOADTEST_QUEUE_URL=https://sqs.example.test/1/batches
LOADTEST_ALB_SUFFIX=app/pp/1
LOADTEST_WORKER_LOG_GROUP=/ecs/worker
LOADTEST_BUCKET=pp-loadtest
AWS_REGION=ap-southeast-1
AWS_DEFAULT_REGION=ap-southeast-1
EOF

# ---- fakes: canned output, steered by FAKE_* env vars -------------------------
# Every fake records its argv, so the test can prove the token never reaches one.
cat >"$T/bin/curl" <<'EOF'
#!/usr/bin/env bash
echo "curl $*" >>"$FAKE_ARGV_LOG"
[[ " $* " == *" @- "* ]] && cat >"$FAKE_DIR/curl_stdin"
case "${*: -1}" in
  */latest/api/token) printf tok ;;
  */meta-data/instance-type) printf c7i.xlarge ;;
  */api/auth/me) printf '{"user_id":"u"}\n%s' "${FAKE_ME:-200}" ;;
  */api/detector/status) printf '{"status":"ready","model_version":"desklib-test"}\n200' ;;
  *) exit 7 ;;
esac
EOF
cat >"$T/bin/aws" <<'EOF'
#!/usr/bin/env bash
echo "aws $*" >>"$FAKE_ARGV_LOG"
case "$1 $2" in
  "sqs get-queue-attributes") printf '%s\t0\n' "${FAKE_DEPTH:-0}" ;;
  "ecs describe-services") echo 1 ;;
  *) exit 254 ;;
esac
EOF
# make_batch_csv: nothing to write (the fake k6 doesn't read it). k6 run: print the
# lines run.sh greps (it tees stdout to k6.log) and write requests.csv to /results.
cat >"$T/bin/docker" <<'EOF'
#!/usr/bin/env bash
echo "docker $*" >>"$FAKE_ARGV_LOG"
case "$*" in
  *make_batch_csv.py*) ;;
  *grafana/k6*" version"*) echo "k6 v2.3.0 (fake)" ;;
  *grafana/k6*" run "*)
    for a; do [[ "$a" == *:/results ]] && out="${a%:/results}"; done
    echo "timestamp,metric_value" >"$out/requests.csv"
    echo "SUMMARY,100.0,200.0,300.0,0.0,0" ;;
  *) exit 1 ;;
esac
EOF
cat >"$T/bin/python3" <<'EOF'
#!/usr/bin/env bash
echo "python3 $*" >>"$FAKE_ARGV_LOG"
[[ -n "${FAKE_COLLECT_CRASH:-}" ]] && exit 1
echo "WORKER_ROW_FAILURES,2"
echo "LOADGEN_CPU_MAX,${FAKE_CPU-12.5}"
echo "DETECTOR_RESTARTED,${FAKE_RESTARTED-0}"
echo 'LIMITS,{"detector": {"cpu": 2048, "memory": 8192}}'
EOF
# grep logs its argv too, then runs the real one: proves the leak guard's argv lacks the token.
REAL_GREP="$(command -v grep)"
cat >"$T/bin/grep" <<EOF
#!/usr/bin/env bash
echo "grep \$*" >>"\$FAKE_ARGV_LOG"
exec "$REAL_GREP" "\$@"
EOF
chmod +x "$T/bin/"*

fails=0
ok() { echo "ok   $1"; }
bad() { echo "FAIL $1"; fails=$((fails + 1)); }

# run_case <env assignments...> -- <run.sh args...>; sets rc, out, meta.
run_case() {
  local envs=()
  while [[ "$1" != -- ]]; do envs+=("$1"); shift; done
  shift
  rm -rf "$LT/results" "$T/argv.log" "$T/curl_stdin"
  rc=0
  out="$(cd "$REPO" && env PATH="$T/bin:$PATH" FAKE_ARGV_LOG="$T/argv.log" FAKE_DIR="$T" \
    LOADTEST_ENV_FILE="$T/loadtest.env" SESSION_TOKEN=tok-s3cret-123 "${envs[@]}" \
    bash apps/loadtest/run.sh "$@" </dev/null 2>&1)" || rc=$?
  meta="$(cat "$LT"/results/2*/meta.json 2>/dev/null || true)"
}
has() { [[ "$2" == *"$1"* ]]; }

run_case -- ramp-idle --service-time 1
[[ $rc -eq 1 ]] && has "measures the deployment" "$out" && ok "ramp-idle locally refuses" || bad "ramp-idle locally refuses (rc=$rc: $out)"

run_case LOADTEST_ENV_FILE="$T/missing.env" -- ramp-idle --service-time 1 --target aws
[[ $rc -eq 1 ]] && has "run on the load generator" "$out" && ok "aws needs the env file" || bad "aws needs the env file (rc=$rc: $out)"

run_case -- ramp-idle --service-time 1 --target aws --model baseline
[[ $rc -eq 1 ]] && ok "aws rejects baseline" || bad "aws rejects baseline (rc=$rc: $out)"

run_case FAKE_ME=401 -- ramp-idle --service-time 1 --target aws
has '"status_reason": "session invalid, log in again"' "$meta" && has '"status": "aborted"' "$meta" && [[ $rc -eq 1 ]] &&
  ok "preflight: session invalid" || bad "preflight: session invalid (rc=$rc: $out)"
grep -qs make_batch_csv "$T/argv.log" && bad "preflight failure still ran the harness" || ok "preflight failure stops before k6"

run_case FAKE_DEPTH=3 -- ramp-idle --service-time 1 --target aws
has '"status_reason": "batches queue not empty"' "$meta" && ok "preflight: queue not empty" || bad "preflight: queue not empty (rc=$rc: $out)"

printf 'abc123\ndirty\n' >"$LT/GIT_SHA"  # what pack puts in the tarball; the copy has no .git
run_case -- ramp-idle --service-time 1 --target aws
{ [[ $rc -eq 0 ]] && has '"status": "ok"' "$meta" && has '"target": "aws"' "$meta" &&
  has '"model_version": "desklib-test"' "$meta" && has '"worker_row_failures": 2' "$meta" &&
  has '"git_sha": "abc123"' "$meta" && has '"git_dirty": true' "$meta" &&
  has '"instance_type": "c7i.xlarge"' "$meta" && has '"region": "ap-southeast-1"' "$meta" &&
  has '"limits": {"detector": {"cpu": 2048, "memory": 8192}}' "$meta" &&
  has "HEALTH_PATH=/api/detector" "$(cat "$T/argv.log")" && [[ -f "$(echo "$LT"/results/2*/requests.csv.gz)" ]]; } &&
  ok "aws happy path" || bad "aws happy path (rc=$rc: $out | $meta)"
grep -qs tok-s3cret-123 "$T/argv.log" && bad "session token in argv" || ok "session token never in argv"
grep -qs "^grep -rqF -f " "$T/argv.log" && ok "leak guard ran, pattern via -f" || bad "leak guard ran, pattern via -f"
grep -qs "Cookie: __Host-session=tok-s3cret-123" "$T/curl_stdin" && ok "cookie sent on curl stdin" || bad "cookie sent on curl stdin"

run_case FAKE_CPU=85.0 -- ramp-idle --service-time 1 --target aws
{ [[ $rc -eq 3 ]] && has '"status": "invalid"' "$meta" && has '"status_reason": "load generator saturated"' "$meta"; } &&
  ok "collector: load generator saturated" || bad "collector: load generator saturated (rc=$rc: $out | $meta)"

run_case FAKE_CPU= -- ramp-idle --service-time 1 --target aws
{ [[ $rc -eq 3 ]] && has '"status": "invalid"' "$meta" && has '"status_reason": "load generator CPU not measured"' "$meta"; } &&
  ok "collector: CPU not measured" || bad "collector: CPU not measured (rc=$rc: $out | $meta)"

run_case FAKE_RESTARTED= -- ramp-idle --service-time 1 --target aws
{ [[ $rc -eq 3 ]] && has '"status": "invalid"' "$meta" && has '"status_reason": "restart check unavailable"' "$meta"; } &&
  ok "collector: restart check unavailable" || bad "collector: restart check unavailable (rc=$rc: $out | $meta)"

run_case FAKE_COLLECT_CRASH=1 -- ramp-idle --service-time 1 --target aws
{ [[ $rc -eq 3 ]] && has '"status": "invalid"' "$meta" && has '"status_reason": "restart check unavailable"' "$meta"; } &&
  ok "collector crashed: invalid" || bad "collector crashed: invalid (rc=$rc: $out | $meta)"

run_case FAKE_RESTARTED=1 FAKE_CPU=85.0 -- ramp-idle --service-time 1 --target aws
{ [[ $rc -eq 3 ]] && has '"status": "aborted"' "$meta" && has '"status_reason": "detector task restarted"' "$meta"; } &&
  ok "collector: restart wins over saturation" || bad "collector: restart wins over saturation (rc=$rc: $out | $meta)"

rm -f "$LT/GIT_SHA"
run_case -- pack
tgz="$LT/results/_pack/loadtest.tgz"
list="$(tar -tzf "$tgz" 2>/dev/null || true)"
{ [[ $rc -eq 0 ]] && grep -qx apps/loadtest/GIT_SHA <<<"$list" && grep -qx docs/assets/trial-data.csv <<<"$list" &&
  grep -qx apps/loadtest/run.sh <<<"$list" && ! grep -qE 'results/|figures/' <<<"$list"; } &&
  ok "pack" || bad "pack (rc=$rc: $out | $list)"

[[ $fails -eq 0 ]] && echo "all passed" || { echo "$fails failed"; exit 1; }

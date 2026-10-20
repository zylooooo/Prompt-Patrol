#!/usr/bin/env bash
# Stub test for deploy.sh: a fake `aws` on PATH logs every call and returns
# canned JSON. Never touches real AWS. Run: bash .github/scripts/deploy_test.sh
set -uo pipefail

command -v jq >/dev/null || { echo "deploy_test.sh needs jq on PATH" >&2; exit 2; }

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY="$HERE/deploy.sh"
ROOT="$(mktemp -d)"
trap 'rm -rf "$ROOT"' EXIT
mkdir "$ROOT/bin"

# Fake aws. Scenario knobs (env): SCEN_PAUSED=1, SCEN_EXIT=<code>|none, SCEN_ROLLBACK=1, SCEN_RUNFAIL=1,
# SCEN_DESCFAIL=1 (any describe-services fails), SCEN_NETFAIL=1 (api describe fails), SCEN_REGFAIL=<svc>.
cat > "$ROOT/bin/aws" <<'FAKE'
#!/usr/bin/env bash
echo "$*" | tr '\n' ' ' >> "$FAKE_DIR/calls.log"; echo >> "$FAKE_DIR/calls.log"
NEW=arn:aws:ecs:ap-southeast-1:420974348257:task-definition
case "$1 $2" in
"ecs describe-services")
  if [ -n "${SCEN_DESCFAIL:-}" ] || { [ -n "${SCEN_NETFAIL:-}" ] && [[ "$*" != *worker* ]]; }; then exit 1
  elif [[ "$*" == *worker* ]]; then
    n=$(( $(cat "$FAKE_DIR/polls" 2>/dev/null || echo 0) + 1 )); echo $n > "$FAKE_DIR/polls"
    st=IN_PROGRESS; [ $n -ge 3 ] && st=COMPLETED
    jq -n --arg st "$st" --arg rb "${SCEN_ROLLBACK:-}" --arg new "$NEW" '
      ["api","worker","detector"] | {services: map({serviceName: ., deployments: [{status: "PRIMARY",
        rolloutState: $st,
        taskDefinition: (if $rb == "1" and . == "api" then "\($new)/prompt-patrol-api:1" else "\($new)/prompt-patrol-\(.):99" end)}]})}'
  elif [ -n "${SCEN_PAUSED:-}" ]; then
    echo '{"services":[],"failures":[{"reason":"MISSING"}]}'
  else
    echo '{"services":[{"status":"ACTIVE","networkConfiguration":{"awsvpcConfiguration":{"subnets":["subnet-1"],"securityGroups":["sg-1"]}}}]}'
  fi ;;
"ecs describe-task-definition")
  echo '{"taskDefinition":{"family":"x","taskDefinitionArn":"old","revision":1,"status":"ACTIVE","requiresAttributes":[],"compatibilities":[],"registeredAt":"t","registeredBy":"u","containerDefinitions":[{"name":"c","image":"old-image"}]}}' ;;
"ecs register-task-definition")
  # family comes from the --cli-input-json; the stub just needs a stable arn per call
  fam=$(echo "$*" | grep -o 'prompt-patrol/[a-z]*' | head -1 | cut -d/ -f2)
  [ "$fam" = "${SCEN_REGFAIL:-}" ] && exit 1
  echo "{\"taskDefinition\":{\"taskDefinitionArn\":\"$NEW/prompt-patrol-$fam:99\"}}" ;;
"ecs run-task")
  if [ -n "${SCEN_RUNFAIL:-}" ]; then echo '{"tasks":[],"failures":[{"reason":"RESOURCE:CPU"}]}'; else
  echo '{"tasks":[{"taskArn":"arn:aws:ecs:ap-southeast-1:420974348257:task/prompt-patrol/abc123"}]}'; fi ;;
"ecs describe-tasks")
  if [ "${SCEN_EXIT:-0}" = none ]; then echo '{"tasks":[{"stoppedReason":"CannotPullContainerError: denied","containers":[{}]}]}'
  else echo "{\"tasks\":[{\"containers\":[{\"exitCode\":${SCEN_EXIT:-0}}]}]}"; fi ;;
"logs get-log-events") echo "alembic: boom" ;;
"ssm get-parameter") echo '{"Parameter":{"Value":"EDIST123"}}' ;;
esac
exit 0
FAKE
chmod +x "$ROOT/bin/aws"

# Fake curl for smoke. SCEN_API=spa (paused: /api/* falls through to the SPA)
# or 502; SCEN_STALE=<n>: / serves the previous build for the first n calls.
cat > "$ROOT/bin/curl" <<'FAKE'
#!/usr/bin/env bash
echo "curl $*" >> "$FAKE_DIR/calls.log"
url="${!#}"
case "$url" in
*/api/auth/me)
  case "${SCEN_API:-}" in
  spa) printf '<!doctype html><script src="/assets/index-NEW.js"></script>'; code=200 ;;
  502) printf '<html>502 Bad Gateway</html>'; code=502 ;;
  *) printf '{"detail":{"code":"not_signed_in","message":"No session cookie was sent."}}'; code=401 ;;
  esac
  [[ " $* " == *" -w "* ]] && printf ' HTTP %s' "$code" ;;
*/)
  n=$(( $(cat "$FAKE_DIR/pages" 2>/dev/null || echo 0) + 1 )); echo $n > "$FAKE_DIR/pages"
  if [ "$n" -le "${SCEN_STALE:-0}" ]; then printf '<script src="/assets/index-OLD.js"></script>'
  else printf '<script src="/assets/index-NEW.js"></script>'; fi ;;
esac
exit 0
FAKE
chmod +x "$ROOT/bin/curl"

SHA=0123456789abcdef0123456789abcdef01234567
FAILED=0
ok() { "$@" || { echo "  assert failed: $*" >&2; [ -n "${DEBUG:-}" ] && cat "$FAKE_DIR/out" "$FAKE_DIR/err" >&2; FAILED=1; }; }
calls() { grep -c -- "$1" "$FAKE_DIR/calls.log" || true; }
eq() { [ "$1" = "$2" ]; }
line_of() { grep -n -- "$1" "$FAKE_DIR/calls.log" | head -1 | cut -d: -f1; }

# run <args...>: fresh fake state, runs deploy.sh, sets RC, OUT, ERR.
run() {
  FAKE_DIR="$(mktemp -d -p "$ROOT")"; export FAKE_DIR; : > "$FAKE_DIR/calls.log"
  RC=0
  PATH="$ROOT/bin:$PATH" SHA=$SHA ECR=123.dkr.ecr.ap-southeast-1.amazonaws.com \
    STABLE_TIMEOUT_SECONDS=60 POLL_SECONDS=0 SMOKE_ATTEMPTS=3 FRONTEND_URL=https://cdn.example \
    bash "$DEPLOY" "$@" >"$FAKE_DIR/out" 2>"$FAKE_DIR/err" || RC=$?
}

case_paused_fails_first() {
  SCEN_PAUSED=1 run check-running
  ok eq "$RC" 1
  ok grep -q "stack is paused" "$FAKE_DIR/err"
  ok eq "$(calls 'ecs register\|ssm put-parameter\|^s3 ')" 0
}

case_happy_path() {
  run release
  ok eq "$RC" 0
  ok eq "$(calls register-task-definition)" 3
  ok eq "$(calls "register-task-definition.*:$SHA.*ManagedBy,value=github-actions")" 3
  ok eq "$(calls run-task)" 1
  ok eq "$(calls 'run-task.*alembic')" 1
  ok eq "$(calls update-service)" 3
  ok eq "$(calls 'run-task.*task-definition arn:aws:ecs:[^ ]*prompt-patrol-api:99')" 1
  ok test "$(line_of update-service)" -gt "$(line_of run-task)"
  ok eq "$(calls deregister-task-definition)" 0
  ok eq "$(cat "$FAKE_DIR/polls")" 3
}

case_migration_failure_deregisters_and_stops() {
  SCEN_EXIT=1 run release
  ok eq "$RC" 1
  ok eq "$(calls 'logs get-log-events.*/ecs/prompt-patrol/api.*ecs/api/abc123')" 1
  ok eq "$(calls deregister-task-definition)" 3
  ok eq "$(calls update-service)" 0
  SCEN_EXIT=none run release   # missing exit code is also a failure
  ok eq "$RC" 1
  ok grep -q "CannotPullContainerError" "$FAKE_DIR/out"
  ok eq "$(calls deregister-task-definition)" 3
  ok eq "$(calls update-service)" 0
}

case_run_task_failures_deregisters() {
  SCEN_RUNFAIL=1 run release
  ok eq "$RC" 1
  ok grep -q "RESOURCE:CPU" "$FAKE_DIR/out"
  ok eq "$(calls deregister-task-definition)" 3
  ok eq "$(calls update-service)" 0
}

case_partial_register_deregisters() {
  SCEN_REGFAIL=worker run release
  ok eq "$RC" 1
  ok eq "$(calls "ecs register-task-definition")" 2   # api ok, worker attempted
  ok eq "$(calls deregister-task-definition)" 1
  ok eq "$(calls 'deregister-task-definition.*prompt-patrol-api:99')" 1
  ok eq "$(calls run-task)" 0
  ok eq "$(calls update-service)" 0
}

case_net_config_failure_deregisters() {
  SCEN_NETFAIL=1 run release
  ok eq "$RC" 1
  ok eq "$(calls deregister-task-definition)" 3
  ok eq "$(calls run-task)" 0
  ok eq "$(calls update-service)" 0
}

case_describe_error_not_paused() {
  SCEN_DESCFAIL=1 run check-running
  ok eq "$RC" 1
  ok grep -q "could not determine stack state" "$FAKE_DIR/err"
  ok eq "$(grep -c "stack is paused" "$FAKE_DIR/err" || true)" 0
}

case_rollback_detected_fails() {
  SCEN_ROLLBACK=1 run release
  ok eq "$RC" 1
  ok eq "$(calls update-service)" 3
  ok eq "$(calls deregister-task-definition)" 0
}

case_record_writes_sha() {
  run record
  ok eq "$RC" 0
  ok eq "$(calls "ssm put-parameter --name /prompt-patrol/image-tag --value $SHA --overwrite")" 1
}

case_publish_web() {
  local d; d="$(mktemp -d -p "$ROOT")"
  run publish-web "$d"
  ok eq "$RC" 0
  ok eq "$(calls "s3 sync $d s3://prompt-patrol-web-420974348257 --delete")" 1
  ok eq "$(calls 'cloudfront create-invalidation.*EDIST123.*/\*')" 1
  ok test "$(line_of 's3 sync')" -lt "$(line_of create-invalidation)"
}

# A dist dir whose index.html names the build the fake CloudFront serves.
smoke_dist() {
  local d; d="$(mktemp -d -p "$ROOT")"
  echo '<script type="module" crossorigin src="/assets/index-NEW.js"></script>' > "$d/index.html"
  echo "$d"
}

case_smoke_passes() {
  run smoke "$(smoke_dist)"
  ok eq "$RC" 0
  ok eq "$(calls 'curl .*https://cdn.example/$')" 1
  ok eq "$(calls 'curl .*https://cdn.example/api/auth/me$')" 1
}

case_smoke_waits_for_invalidation() {
  SCEN_STALE=2 run smoke "$(smoke_dist)"
  ok eq "$RC" 0
  ok eq "$(cat "$FAKE_DIR/pages")" 3
}

case_smoke_fails_on_spa_fallthrough() {
  SCEN_API=spa run smoke "$(smoke_dist)"
  ok eq "$RC" 1
  ok grep -q "smoke FAILED" "$FAKE_DIR/out"
  ok eq "$(calls 'curl .*/api/auth/me$')" 3
}

case_smoke_fails_on_5xx() {
  SCEN_API=502 run smoke "$(smoke_dist)"
  ok eq "$RC" 1
  ok grep -q "502 Bad Gateway</html> HTTP 502" "$FAKE_DIR/out"
}

EXIT=0
for c in paused_fails_first happy_path migration_failure_deregisters_and_stops \
         run_task_failures_deregisters partial_register_deregisters \
         net_config_failure_deregisters describe_error_not_paused rollback_detected_fails record_writes_sha publish_web \
         smoke_passes smoke_waits_for_invalidation smoke_fails_on_spa_fallthrough smoke_fails_on_5xx; do
  FAILED=0; unset SCEN_PAUSED SCEN_EXIT SCEN_ROLLBACK SCEN_RUNFAIL SCEN_DESCFAIL SCEN_NETFAIL SCEN_REGFAIL SCEN_API SCEN_STALE
  "case_$c"
  if [ $FAILED = 0 ]; then echo "PASS $c"; else echo "FAIL $c"; EXIT=1; fi
done
exit $EXIT

#!/usr/bin/env bash
# CD steps that talk to AWS. Called from the `deploy` job in ci.yml:
#   deploy.sh check-running        fail unless the stack is not paused
#   deploy.sh release              migrate -> roll out (images must already be in ECR)
#   deploy.sh publish-web <dir>    sync the SPA build to S3, invalidate CloudFront
#   deploy.sh record               store SHA as the image tag Terraform reads
# Env: SHA, ECR (registry host), optional STABLE_TIMEOUT_SECONDS, POLL_SECONDS.
set -euo pipefail

CLUSTER=prompt-patrol
SERVICES="api worker detector"
WEB_BUCKET=prompt-patrol-web-420974348257
TAG_PARAM=/prompt-patrol/image-tag
DIST_PARAM=/prompt-patrol/cloudfront-distribution-id
STABLE_TIMEOUT_SECONDS="${STABLE_TIMEOUT_SECONDS:-1800}" # detector startPeriod is 300s; waiters give up at 10 min
POLL_SECONDS="${POLL_SECONDS:-15}"

# Revisions registered this run, by service. ROLLING flips to 1 right before the
# first update-service: from then on ECS owns rollback and nothing is deregistered.
declare -A NEW_ARN=()
ROLLING=0

log() { echo "[deploy] $*"; }

check_running() {
  log "checking the stack is not paused"
  local out
  out="$(aws ecs describe-services --cluster "$CLUSTER" --services api --output json)" || {
    echo "could not determine stack state" >&2
    exit 1
  }
  if ! echo "$out" | jq -e '.services[0].status == "ACTIVE"' >/dev/null; then
    echo "stack is paused" >&2
    exit 1
  fi
  log "stack is running"
}

# Registers a new revision per service (latest ACTIVE revision, image swapped).
# Fills NEW_ARN[svc].
register_all() {
  local svc def arn
  for svc in $SERVICES; do
    log "registering prompt-patrol-$svc with image prompt-patrol/$svc:$SHA"
    def="$(aws ecs describe-task-definition --task-definition "prompt-patrol-$svc" --output json |
      jq -c --arg img "$ECR/prompt-patrol/$svc:$SHA" '
        .taskDefinition
        | .containerDefinitions[0].image = $img
        | del(.taskDefinitionArn, .revision, .status, .requiresAttributes, .compatibilities,
              .registeredAt, .registeredBy, .deregisteredAt)')"
    arn="$(aws ecs register-task-definition --cli-input-json "$def" \
      --tags key=Project,value=prompt-patrol key=ManagedBy,value=github-actions \
      --output json | jq -r '.taskDefinition.taskDefinitionArn')"
    log "  -> $arn"
    NEW_ARN[$svc]="$arn"
  done
}

# Deregisters only what was registered so far, and forgets each entry so a
# second call is a no-op.
deregister_all() {
  local svc
  for svc in $SERVICES; do
    [ -n "${NEW_ARN[$svc]:-}" ] || continue
    log "deregistering ${NEW_ARN[$svc]}"
    aws ecs deregister-task-definition --task-definition "${NEW_ARN[$svc]}" >/dev/null
    unset "NEW_ARN[$svc]"
  done
}

# The EXIT trap in release() deregisters on any failure before rolling starts
# (set -e included), so this only logs and fails.
fail_migration() {
  log "migration FAILED: $*"
  exit 1
}

migrate() {
  local net run task_arn task_id desc code
  log "running 'alembic upgrade head' on ${NEW_ARN[api]}"
  net="$(aws ecs describe-services --cluster "$CLUSTER" --services api --output json |
    jq -c '.services[0].networkConfiguration')"
  # run-task is only permitted on the revision-qualified ARN, never the bare family
  run="$(aws ecs run-task --cluster "$CLUSTER" --launch-type FARGATE \
      --task-definition "${NEW_ARN[api]}" --network-configuration "$net" \
      --overrides '{"containerOverrides":[{"name":"api","command":["alembic","upgrade","head"]}]}' \
      --output json)" || fail_migration "run-task call failed"
  task_arn="$(echo "$run" | jq -r '.tasks[0].taskArn // empty')"
  [ -n "$task_arn" ] || fail_migration "run-task started no task. failures: $(echo "$run" | jq -c '.failures')"
  task_id="${task_arn##*/}"
  log "migration task $task_id started, waiting for it to stop"
  aws ecs wait tasks-stopped --cluster "$CLUSTER" --tasks "$task_arn" ||
    fail_migration "waiter gave up (~10 min); task may still be running or timed out: $task_arn"
  desc="$(aws ecs describe-tasks --cluster "$CLUSTER" --tasks "$task_arn" --output json)" ||
    fail_migration "describe-tasks failed for $task_arn"
  code="$(echo "$desc" | jq -r '.tasks[0].containers[0].exitCode // "missing"')"
  if [ "$code" != 0 ]; then
    log "stoppedReason: $(echo "$desc" | jq -r '.tasks[0].stoppedReason // "none"')"
    log "container reason: $(echo "$desc" | jq -r '.tasks[0].containers[0].reason // "none"')"
    log "task log (empty if the container never started):"
    aws logs get-log-events --log-group-name /ecs/prompt-patrol/api \
      --log-stream-name "ecs/api/$task_id" --query 'events[].message' --output text || true
    fail_migration "exit code: $code"
  fi
  log "migration succeeded"
}

roll_out() {
  local svc want states deadline=$((SECONDS + STABLE_TIMEOUT_SECONDS))
  ROLLING=1
  for svc in $SERVICES; do
    log "updating service $svc -> ${NEW_ARN[$svc]}"
    aws ecs update-service --cluster "$CLUSTER" --service "$svc" \
      --task-definition "${NEW_ARN[$svc]}" >/dev/null
  done
  want="$(for svc in $SERVICES; do echo "$svc ${NEW_ARN[$svc]}"; done |
    jq -Rn '[inputs | split(" ") | {(.[0]): .[1]}] | add')"
  # `services-stable` also returns 0 after the circuit breaker rolled back, so
  # check each PRIMARY deployment ourselves. No deregister on failure: ECS has
  # already rolled back and a re-run registers again.
  while :; do
    states="$(aws ecs describe-services --cluster "$CLUSTER" --services $SERVICES --output json |
      jq -r --argjson want "$want" '
        .services[] | . as $s
        | ([.deployments[] | select(.status == "PRIMARY")][0]) as $p
        | "\($s.serviceName) " + (if $p.taskDefinition != $want[$s.serviceName]
            then "SUPERSEDED" else ($p.rolloutState // "UNKNOWN") end)')"
    log "rollout: $(echo "$states" | tr '\n' ' ')"
    if echo "$states" | grep -qE ' (FAILED|SUPERSEDED)$'; then
      log "rollout FAILED: a deployment failed or was rolled back by ECS"
      exit 1
    fi
    if [ "$(echo "$states" | grep -c ' COMPLETED$')" = 3 ]; then
      log "all services running the new revision"
      return
    fi
    if [ "$SECONDS" -ge "$deadline" ]; then
      log "rollout TIMED OUT after ${STABLE_TIMEOUT_SECONDS}s"
      exit 1
    fi
    sleep "$POLL_SECONDS"
  done
}

release() {
  : "${SHA:?SHA is required}" "${ECR:?ECR is required}"
  trap '[ "$?" = 0 ] || [ "$ROLLING" = 1 ] || deregister_all' EXIT
  register_all
  migrate
  roll_out
}

publish_web() {
  local dist="${1:?usage: deploy.sh publish-web <dist-dir>}" id
  log "syncing $dist to s3://$WEB_BUCKET"
  aws s3 sync "$dist" "s3://$WEB_BUCKET" --delete
  id="$(aws ssm get-parameter --name "$DIST_PARAM" --output json | jq -r '.Parameter.Value')"
  log "invalidating CloudFront distribution $id"
  aws cloudfront create-invalidation --distribution-id "$id" --paths "/*" >/dev/null
}

record() {
  : "${SHA:?SHA is required}"
  log "recording $SHA as $TAG_PARAM"
  aws ssm put-parameter --name "$TAG_PARAM" --value "$SHA" --overwrite >/dev/null
}

case "${1:-}" in
  check-running) check_running ;;
  release) release ;;
  publish-web) publish_web "${2:-}" ;;
  record) record ;;
  *) echo "usage: deploy.sh check-running|release|publish-web <dir>|record" >&2; exit 2 ;;
esac

#!/usr/bin/env bash
# Required env: IMAGE_TAG, DOCKERHUB_USERNAME, EC2_INSTANCE_ID, DEPLOY_DIR
set -euo pipefail

: "${IMAGE_TAG:?}" "${DOCKERHUB_USERNAME:?}" "${EC2_INSTANCE_ID:?}" "${DEPLOY_DIR:?}"

# These values are spliced into a root shell script on the host — reject anything
# that is not a plain identifier/path.
[[ "$IMAGE_TAG" =~ ^[A-Za-z0-9_.-]+$ ]] || { echo "invalid IMAGE_TAG: $IMAGE_TAG" >&2; exit 1; }
[[ "$DOCKERHUB_USERNAME" =~ ^[a-z0-9_.-]+$ ]] || { echo "invalid DOCKERHUB_USERNAME" >&2; exit 1; }
[[ "$DEPLOY_DIR" =~ ^/[A-Za-z0-9_./-]+$ ]] || { echo "invalid DEPLOY_DIR" >&2; exit 1; }

compose_b64=$(base64 -w0 docker-compose.prod.yml)

remote_script=$(cat <<EOF
set -euo pipefail
export IMAGE_TAG='$IMAGE_TAG'
export DOCKERHUB_USERNAME='$DOCKERHUB_USERNAME'
cd '$DEPLOY_DIR'
[ -f .env ] || { echo "no .env in $DEPLOY_DIR" >&2; exit 1; }

echo '$compose_b64' | base64 -d > docker-compose.prod.yml

# Keep .env in step with what is running so manual compose commands on the host
# target the same images.
set_env() {
  if grep -q "^\$1=" .env; then sed -i "s|^\$1=.*|\$1=\$2|" .env; else echo "\$1=\$2" >> .env; fi
}
set_env IMAGE_TAG "\$IMAGE_TAG"
set_env DOCKERHUB_USERNAME "\$DOCKERHUB_USERNAME"

compose="docker compose -f docker-compose.prod.yml"
fail() {
  echo "\$1" >&2
  \$compose logs --no-color --tail 60 api worker >&2 || true
  exit 1
}

# Only our images — cloudflared stays on whatever the host already has, so a
# deploy never silently upgrades the tunnel. --quiet keeps SSM's 24k stdout /
# 8k stderr capture for the lines that matter.
\$compose pull --quiet api worker judge-image
# up waits for api to be healthy (cloudflared depends on it) and exits non-zero
# if it turns unhealthy.
\$compose up -d --remove-orphans --quiet-pull || fail "compose up failed"

cid=\$(\$compose ps -q api)
status=unknown
for _ in \$(seq 1 36); do
  status=\$(docker inspect -f '{{.State.Health.Status}}' "\$cid" 2>/dev/null || echo unknown)
  case "\$status" in healthy|unhealthy) break ;; esac
  sleep 5
done
[ "\$status" = healthy ] || fail "api is \$status"

docker image prune -af --filter "until=72h" >/dev/null
\$compose ps
echo "Deployed \$IMAGE_TAG"
EOF
)

command="bash -c \"\$(echo $(printf '%s' "$remote_script" | base64 -w0) | base64 -d)\""
params=$(jq -n --arg c "$command" '{commands: [$c], executionTimeout: ["900"]}')

command_id=$(aws ssm send-command \
  --instance-ids "$EC2_INSTANCE_ID" \
  --document-name AWS-RunShellScript \
  --comment "hello-bitcoin deploy $IMAGE_TAG" \
  --parameters "$params" \
  --query Command.CommandId --output text)
echo "SSM command: $command_id"

status=Pending
for _ in $(seq 1 180); do
  sleep 5
  status=$(aws ssm get-command-invocation --command-id "$command_id" --instance-id "$EC2_INSTANCE_ID" \
    --query Status --output text 2>/dev/null || echo Pending)
  case "$status" in Success|Failed|Cancelled|TimedOut) break ;; esac
done

echo "── host stdout ──"
aws ssm get-command-invocation --command-id "$command_id" --instance-id "$EC2_INSTANCE_ID" \
  --query StandardOutputContent --output text || true
echo "── host stderr ──"
aws ssm get-command-invocation --command-id "$command_id" --instance-id "$EC2_INSTANCE_ID" \
  --query StandardErrorContent --output text || true

echo "SSM status: $status"
[ "$status" = Success ]

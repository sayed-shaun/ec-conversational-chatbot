#!/usr/bin/env bash
# Point ec-chatbot.vercel.app at the latest READY production deployment.
#
# ec-chatbot.vercel.app is not a domain this project can formally register
# (it collides with an unrelated project's default .vercel.app subdomain),
# so it does not auto-update on push the way ec-chatbot-xi.vercel.app does.
# Run this after every deploy (manual or GitHub-triggered) to re-point it.
#
# Requires: the vercel CLI, logged in (`vercel login`) with access to the
# sit12 team's ec-chatbot project, and `jq`.

set -euo pipefail

PROJECT="ec-chatbot"
ALIAS="ec-chatbot.vercel.app"

cd "$(dirname "${BASH_SOURCE[0]}")/.."

latest="$(vercel ls "$PROJECT" --json \
  | jq -r '[.deployments[] | select(.state == "READY" and .target == "production")]
           | sort_by(.createdAt) | last | .url')"

if [[ -z "$latest" || "$latest" == "null" ]]; then
  echo "No ready production deployment found for $PROJECT" >&2
  exit 1
fi

echo "Pointing $ALIAS -> $latest"
vercel alias set "$latest" "$ALIAS"

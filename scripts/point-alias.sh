#!/usr/bin/env bash
# Point ec-chatbot.vercel.app at the latest READY production deployment.
#
# ec-chatbot.vercel.app cannot auto-update the way the project's own
# .vercel.app domains do: it is the default subdomain of a project outside
# this team, so `vercel domains add` rejects it with alias_conflict and it
# can only be assigned per-deployment. Run this after every deploy.
#
# Locally: needs the vercel CLI logged in (`vercel login`) with access to the
# sit12 team, plus `jq`. In CI: set VERCEL_TOKEN (and VERCEL_SCOPE if the
# token is not already scoped to the team) instead of logging in. See
# .github/workflows/point-alias.yml, which runs this on every production
# deploy.

set -euo pipefail

PROJECT="ec-conversational-chatbot"
ALIAS="ec-chatbot.vercel.app"

cd "$(dirname "${BASH_SOURCE[0]}")/.."

# Empty when running locally against a logged-in CLI. Written as ifs rather
# than `[[ ... ]] && auth+=(...)`: under `set -e` a false test there is a
# failing top-level command, which would exit the script instead of skipping
# the flag. ${auth[@]+...} keeps `set -u` quiet when the array is empty.
auth=()
if [[ -n "${VERCEL_TOKEN:-}" ]]; then auth+=(--token "$VERCEL_TOKEN"); fi
if [[ -n "${VERCEL_SCOPE:-}" ]]; then auth+=(--scope "$VERCEL_SCOPE"); fi

latest="$(vercel ls "$PROJECT" --json ${auth[@]+"${auth[@]}"} \
  | jq -r '[.deployments[] | select(.state == "READY" and .target == "production")]
           | sort_by(.createdAt) | last | .url')"

if [[ -z "$latest" || "$latest" == "null" ]]; then
  echo "No ready production deployment found for $PROJECT" >&2
  exit 1
fi

echo "Pointing $ALIAS -> $latest"
vercel alias set "$latest" "$ALIAS" ${auth[@]+"${auth[@]}"}

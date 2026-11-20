#!/usr/bin/env bash
# deploy.sh [ref] : deploys the function from a laptop with the podinfo-sls
# tooling (same create-or-update + wait READY as the other alpha demos).
#
# Needs: ~/.ovh.conf with the serverless-alpha profile (see
# podinfo-sls/tools/ovh.conf.example), python-ovh, jq, and the podinfo-sls
# repository cloned next to this one (or PODINFO_TOOLS pointing at its tools/).
#
# Env: OVH_CLOUD_PROJECT (required), NOTIFY_URLS (required: the Apprise URLs,
#      comma-separated), SLS_REGION (EU-WEST-PAR), FUNCTION_NAME (demo-notify),
#      NOTIFY_TITLE (OVHcloud Serverless).
#
# The ref must exist on GitHub: the platform clones it from the public repo.
set -euo pipefail
ref="${1:-main}"
here="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
tools="${PODINFO_TOOLS:-$here/../podinfo-sls/tools}"
[[ -x "$tools/deploy.sh" ]] || { echo "podinfo-sls tooling not found at $tools (set PODINFO_TOOLS)" >&2; exit 1; }
: "${OVH_CLOUD_PROJECT:?OVH_CLOUD_PROJECT is required}"
: "${NOTIFY_URLS:?NOTIFY_URLS is required (comma-separated Apprise URLs)}"
export SLS_REGION="${SLS_REGION:-EU-WEST-PAR}"

repo_url="https://github.com/antonin-a/serverless-fn-notify"
code="$(curl -s -o /dev/null -w '%{http_code}' "$repo_url/tree/$ref")"
[[ "$code" == "200" ]] || { echo "ref $ref not found on $repo_url (HTTP $code): push it first" >&2; exit 1; }

"$tools/deploy.sh" function "${FUNCTION_NAME:-demo-notify}" "$here/deploy/function.json" \
  REF="$ref" RELEASE="$ref" REPO_URL="$repo_url" \
  NOTIFY_TITLE="${NOTIFY_TITLE:-OVHcloud Serverless}" \
  NOTIFY_URLS="$NOTIFY_URLS"

#!/usr/bin/env bash
# deploy-waha.sh : deploys WAHA (WhatsApp HTTP API, unofficial WhatsApp Web
# client, https://waha.devlike.pro) as a Serverless container, for the demo
# "the function notifies a WhatsApp group through a self-hosted gateway".
#
# One instance kept alive (minInstances 1): the WhatsApp session lives in the
# instance memory, there is no persistent storage. A restart or a new revision
# means scanning the QR code again. Good enough for a demo, not for production.
#
# Needs the same tooling as deploy.sh (podinfo-sls/tools, ~/.ovh.conf).
# Env: OVH_CLOUD_PROJECT (required), WAHA_API_KEY (required, long random string),
#      SLS_REGION (EU-WEST-PAR), CONTAINER_NAME (demo-waha).
#
# After deploy:
#   1. open <url>/dashboard (admin / WAHA_API_KEY), start session "default",
#      scan the QR code with the phone (Linked devices).
#   2. list the groups: curl -H "X-Api-Key: $WAHA_API_KEY" <url>/api/default/groups
#   3. point the function at it, see README "Send to a WhatsApp group with WAHA".
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
tools="${PODINFO_TOOLS:-$here/../podinfo-sls/tools}"
[[ -x "$tools/deploy.sh" ]] || { echo "podinfo-sls tooling not found at $tools (set PODINFO_TOOLS)" >&2; exit 1; }
: "${OVH_CLOUD_PROJECT:?OVH_CLOUD_PROJECT is required}"
: "${WAHA_API_KEY:?WAHA_API_KEY is required (a long random string, e.g. uuidgen)}"
export SLS_REGION="${SLS_REGION:-EU-WEST-PAR}"

"$tools/deploy.sh" container "${CONTAINER_NAME:-demo-waha}" "$here/deploy/waha-container.json" \
  WAHA_API_KEY="$WAHA_API_KEY"

#!/bin/sh
# n8n container entrypoint (Gate 9). Creates n8n credentials from environment variables, imports and publishes the
# PulseOps workflow, then starts n8n. Secrets exist only in the environment, in n8n's encrypted credential store
# (keyed by N8N_ENCRYPTION_KEY) and in a short-lived temp file that is removed immediately.
set -eu

: "${PULSEOPS_N8N_TOKEN:?PULSEOPS_N8N_TOKEN (the service_n8n bearer token) is required}"
: "${N8N_WEBHOOK_SECRET:?N8N_WEBHOOK_SECRET (the webhook header secret) is required}"
: "${N8N_ENCRYPTION_KEY:?N8N_ENCRYPTION_KEY is required}"

# Token / secret charset is validated so substitution cannot be abused (letters, digits and . _ ~ + / = -).
for value in "$PULSEOPS_N8N_TOKEN" "$N8N_WEBHOOK_SECRET"; do
  case "$value" in
    *[!A-Za-z0-9._~+/=-]*) echo "bootstrap: token/secret contains unsupported characters" >&2; exit 1 ;;
  esac
done

credentials=/tmp/n8n-credentials.json
sed -e "s|\${PULSEOPS_N8N_TOKEN}|${PULSEOPS_N8N_TOKEN}|g" \
    -e "s|\${N8N_WEBHOOK_SECRET}|${N8N_WEBHOOK_SECRET}|g" \
    /n8n/credentials.template.json > "$credentials"
n8n import:credentials --input="$credentials"
rm -f "$credentials"

n8n import:workflow --input=/n8n/pulseops-event-workflow.json
n8n publish:workflow --id=pulseopsEventGate6

exec n8n start

#!/usr/bin/env bash
# Start TLS local SuperLink with persistent DB so SuperNodes rejoin the same IDs.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"   # Untitled/
FRAMEWORK="${ROOT}/flower/framework"
SECRETS="${HOME}/.flwr/secrets.env"
DATABASE="${HOME}/.flwr/local-agent.db"

if [[ ! -f "${SECRETS}" ]]; then
  echo "Missing ${SECRETS}. Add export FLWR_MODEL_API_KEY=... and related vars." >&2
  exit 1
fi
# shellcheck source=/dev/null
source "${SECRETS}"

mkdir -p "${HOME}/.flwr"
cd "${FRAMEWORK}"
exec uv run --python 3.11.14 flower-superlink \
  --database "${DATABASE}" \
  --ssl-ca-certfile /tmp/flower-tls/certificates/ca.crt \
  --ssl-certfile /tmp/flower-tls/certificates/server.pem \
  --ssl-keyfile /tmp/flower-tls/certificates/server.key \
  --enable-supernode-auth

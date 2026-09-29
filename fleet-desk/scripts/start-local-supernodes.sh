#!/usr/bin/env bash
# Reconnect the three named SuperNodes. Safe to re-run.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"   # Untitled/
FRAMEWORK="${ROOT}/flower/framework"
KEYS=/tmp/flower-tls/keys
CERT=/tmp/flower-tls/certificates/ca.crt
cd "${FRAMEWORK}"

register_one() {
  local pub="$1" name="$2" loc="$3"
  uv run --python 3.11.14 flwr supernode register "${pub}" local-agent \
    --name "${name}" --location "${loc}" 2>&1 || true
}

register_one "${KEYS}/supernode_credentials_1.pub" site-a '37.4275,-122.1697'
register_one "${KEYS}/supernode_credentials_2.pub" site-b '37.4419,-122.1430'
register_one "${KEYS}/supernode_credentials_3.pub" site-c '37.3861,-122.0839'

echo "Starting SuperNodes (they rejoin the persistent SuperLink DB)..."
uv run --python 3.11.14 flower-supernode \
  --root-certificates "${CERT}" \
  --superlink 127.0.0.1:9092 --host 127.0.0.1 --port 9094 \
  --auth-supernode-private-key "${KEYS}/supernode_credentials_1" &
uv run --python 3.11.14 flower-supernode \
  --root-certificates "${CERT}" \
  --superlink 127.0.0.1:9092 --host 127.0.0.1 --port 9095 \
  --auth-supernode-private-key "${KEYS}/supernode_credentials_2" &
uv run --python 3.11.14 flower-supernode \
  --root-certificates "${CERT}" \
  --superlink 127.0.0.1:9092 --host 127.0.0.1 --port 9096 \
  --auth-supernode-private-key "${KEYS}/supernode_credentials_3" &
wait

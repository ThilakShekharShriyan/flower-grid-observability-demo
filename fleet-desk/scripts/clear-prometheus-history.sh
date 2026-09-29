#!/usr/bin/env bash
# Clear Grafana/Prometheus history only. Does NOT wipe SuperLink DB.
set -euo pipefail
pkill -f 'keep_training.py' 2>/dev/null || true
pkill -f '/tmp/flower-metrics-demo/bin/prometheus' 2>/dev/null || true
sleep 0.5
rm -rf /tmp/flower-metrics-demo/data/*
mkdir -p /tmp/flower-metrics-demo/data /tmp/flower-agent-audit
rm -f /tmp/flower-agent-audit/flower_*.prom /tmp/flower-agent-audit/flower_agent_audit.jsonl
: > /tmp/flower-agent-audit/flower_agent.prom
: > /tmp/flower-agent-audit/flower_training.prom
: > /tmp/flower-agent-audit/flower_site_training.prom
: > /tmp/flower-agent-audit/flower_decision.prom
echo "Prometheus history cleared. SuperLink DB kept at ~/.flwr/local-agent.db"
echo "Restart prometheus + keep_training after SuperNodes are online."

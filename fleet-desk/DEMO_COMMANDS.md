# Demo runbook — commands (stack is STOPPED right now)

Paths:
- `FW=~/Projects/FLoweLABS/Untitled/flower/framework`
- `DESK=~/Projects/FLoweLABS/Untitled/fleet-desk`
- `NUMPY=~/Projects/FLoweLABS/Untitled/flower/examples/quickstart-numpy`
- TLS certs already at `/tmp/flower-tls/`
- Secrets: `~/.flwr/secrets.env` (never open on screen)

---

## 0) Kill everything (already done; re-run anytime)

```bash
pkill -f 'flower-superlink' || true
pkill -f 'flower-supernode' || true
pkill -f 'keep_training.py' || true
pkill -f 'serve_metrics.py' || true
pkill -f '/tmp/flower-metrics-demo/bin/prometheus' || true
pkill -f 'flwr chat' || true
for p in 9090 9092 9093 9094 9095 9096 9105; do
  kill $(lsof -tiTCP:$p -sTCP:LISTEN) 2>/dev/null || true
done
```

---

## 1) Boot the stack (separate terminals / tabs)

### Terminal A — SuperLink
```bash
source ~/.flwr/secrets.env
~/Projects/FLoweLABS/Untitled/fleet-desk/scripts/start-local-superlink.sh
```

### Terminal B — SuperNodes (site-a/b/c)
```bash
# wait ~2s after SuperLink is up
~/Projects/FLoweLABS/Untitled/fleet-desk/scripts/start-local-supernodes.sh
```

### Terminal C — Metrics exporter (:9105)
```bash
mkdir -p /tmp/flower-metrics-demo /tmp/flower-agent-audit
cp ~/Projects/FLoweLABS/Untitled/fleet-desk/scripts/serve_metrics.py /tmp/flower-metrics-demo/
cp ~/Projects/FLoweLABS/Untitled/fleet-desk/scripts/keep_training.py /tmp/flower-metrics-demo/
# prometheus binary should already be at /tmp/flower-metrics-demo/bin/prometheus
cat > /tmp/flower-metrics-demo/prometheus.host.yml <<'EOF'
global:
  scrape_interval: 5s
scrape_configs:
  - job_name: flower-grid
    static_configs:
      - targets: ["127.0.0.1:9105"]
EOF

cd ~/Projects/FLoweLABS/Untitled/flower/framework
uv run --python 3.11.14 python /tmp/flower-metrics-demo/serve_metrics.py
```

### Terminal D — Prometheus (:9090)
```bash
/tmp/flower-metrics-demo/bin/prometheus \
  --config.file=/tmp/flower-metrics-demo/prometheus.host.yml \
  --storage.tsdb.path=/tmp/flower-metrics-demo/data \
  --web.listen-address=127.0.0.1:9090 \
  --storage.tsdb.retention.time=2h
```

### Terminal E — Training loop
```bash
cd ~/Projects/FLoweLABS/Untitled/flower/examples/quickstart-numpy
uv run --project ~/Projects/FLoweLABS/Untitled/flower/framework --python 3.11.14 \
  python /tmp/flower-metrics-demo/keep_training.py
```

### Terminal F — flwr chat
```bash
export FLWR_CHAT_SUPERLINK=local-agent
source ~/.flwr/secrets.env
cd ~/Projects/FLoweLABS/Untitled/flower/framework
uv run --python 3.11.14 flwr chat
```

Optional Grafana: http://127.0.0.1:3000/d/flower-grid (admin / flower) if still running.

---

## 2) Health check (before audience)

```bash
curl -s http://127.0.0.1:9090/-/healthy
curl -s 'http://127.0.0.1:9090/api/v1/query?query=flower_supernode_up' \
  | python3 -c 'import sys,json;d=json.load(sys.stdin);print([r["metric"].get("name") for r in d["data"]["result"] if r["metric"].get("status")=="online" or "status" not in r["metric"]])'
# expect site-a, site-b, site-c
```

Phone nearby. Inbox open. Secrets NOT on screen.

---

## 3) Live demo beats + commands

### Beat — metrics (Grafana or Prom)
Show: `flower_site_train_metric`, `flower_site_online`, `flower_supernodes_online`

### Beat — chat (paste into flwr chat)
```
What are the site train metrics for the last 5 minutes? Use the fleet tools and cite the Prometheus source.
```

### Beat — rules (optional show)
```bash
cd ~/Projects/FLoweLABS/Untitled/fleet-desk
PYTHONPATH=. ../flower/framework/.venv/bin/python manage_alerts.py list
```

### Beat — MONEY SHOT (node-down → email + call → restore)
```bash
cd ~/Projects/FLoweLABS/Untitled/fleet-desk
set -a && source ~/.flwr/secrets.env && set +a
export RESEND_TO=thilakshekharshriyan@gmail.com
export PYTHONPATH=.
../flower/framework/.venv/bin/python simulate_node_down.py --site site-b --timeout 120
```

Narrate: process killed → Prom offline → email → phone rings → site-b back.

Optional mid-incident chat:
```
Site-b just went offline. Evaluate fleet alerts and summarize what actions fired.
```

### Beat — close
“One control plane: chat, ServerApp, email, voice. Nervous system with a phone number.”

---

## 4) Tear down again

Same as section 0.

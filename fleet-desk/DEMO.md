# Flower Grid Observability — Demo Script (~12–15 min)

Talk track + click path for presenting the Agent Grid + Prometheus + alert demo.
Audience: eng / partner who already knows Flower basics.

---

## One-liner

**Named SuperNodes publish live metrics to Prometheus; `flwr chat` queries them with first-party tools; when a site drops, the same rules email on-call and place a Twilio voice call.**

---

## Architecture (30 sec, one slide / whiteboard)

```
site-a / site-b / site-c  →  TLS SuperLink (local-agent)
         │                         │
         │                    Agent / ServerApp
         ▼                         ▼
   :9105 prom files  →  Prometheus :9090  →  Grafana
                              │
                    fleet_ops connector
                    (PromQL + email + Twilio)
```

| Piece | Where |
|-------|--------|
| Product fork | `flower/` branch `agent-grid-observability` |
| Operator FAB | `fleet-desk/` |
| Secrets / rules | `~/.flwr/secrets.env`, `grid_alerts.json` |
| Launch | `fleet-desk/scripts/start-local-*.sh` |

---

## Pre-flight (before audience sits down)

1. Secrets loaded (`RESEND_*`, `TWILIO_*`, `FLWR_MODEL_*`).
2. Stack up:
   - SuperLink + 3 SuperNodes online in Prom
   - Prometheus `:9090`, metrics exporter `:9105`
   - Optional: Grafana dashboard `flower-grid`
   - Training loop (`keep_training`) running
3. `flwr chat` open (`FLWR_CHAT_SUPERLINK=local-agent`)
4. Phone nearby (Twilio trial → verified number)
5. Inbox open for Resend

Quick health check:

```bash
curl -s 'http://127.0.0.1:9090/api/v1/query?query=flower_supernode_up' \
  | python3 -c 'import sys,json;d=json.load(sys.stdin);print([r["metric"]["name"] for r in d["data"]["result"]])'
# expect: site-a, site-b, site-c
```

---

## Act 1 — Live fleet metrics (3 min)

**Say:** “Each SuperNode is a named site. Training metrics land in Prometheus as first-class Flower series — not a sidecar hack.”

**Show Grafana or Prom UI:**
- `flower_site_train_metric`
- `flower_site_online`
- `flower_supernodes_online`

**In `flwr chat`, ask:**

> What are the site train metrics for the last 5 minutes? Use the fleet tools and cite the Prometheus source.

**Expect:** tool call to `fleet_get_site_metrics` (or equivalent), answer with `source` / `prometheus_url` so it’s clear data came from Prom, not the model.

**Optional follow-up:**

> Is any site offline or trending unhealthy?

---

## Act 2 — Rules as code (2 min)

**Say:** “Alerts are editable rules the agent and ServerApp share — exclude a bad site, pause if the fleet is too thin, page humans.”

**Show** `~/.flwr/grid_alerts.json` (or):

```bash
cd fleet-desk
PYTHONPATH=. ../flower/framework/.venv/bin/python manage_alerts.py list
```

Call out rules: `site_offline` → exclude + email + **call**; `fleet_too_thin` → pause + email + call.

---

## Act 3 — Node-down page (5 min) — the climax

**Say:** “We’ll kill site-b. Watch Prometheus flip offline, then the same path emails you and rings your phone with the Twilio Auto Response.”

```bash
cd fleet-desk
set -a && source ~/.flwr/secrets.env && set +a
export PYTHONPATH=.
../flower/framework/.venv/bin/python simulate_node_down.py --site site-b --timeout 120
```

**While it runs, narrate:**
1. SuperNode process stopped
2. Prom: `site-b` leaves `flower_supernode_up`
3. Resend email (Prom HTML report)
4. Twilio call(s) — Auto Response `<Say>` sequence
5. Script restarts site-b; fleet healthy again

**In chat (optional, after restore or mid-incident):**

> Site-b just went offline. Evaluate fleet alerts and summarize what actions fired.

---

## Act 4 — Close the loop (2 min)

**Say:** “Chat, ServerApp exclude lists, email, and voice all read the same control file and rules — one control plane.”

Point at:
- `/tmp/flower-agent-audit/grid_control.json` (exclude / pause)
- `fleet_ops` connector in the Flower fork (first-party tools)
- `fleet-desk` as the operator FAB / demo harness — not a second product

**Ask the room:** “Where would you hang the next rule — battery, latency, data drift?”

---

## Backup lines if something flakes

| Failure | Fix / line |
|---------|------------|
| Chat empty metrics | “Exporter on :9105 — restart and re-ask.” |
| Chat model abort | Rebuild FAB / check Nebius MiniMax key |
| Email “sent” but missing | Confirm `RESEND_TO` spelling |
| Twilio 400 Twiml | Trial needs `Url` → Auto Response template (already wired) |
| SuperNode won’t rejoin | Wait heartbeat; re-run `start-local-supernodes.sh` |

---

## Timing card (print this)

| Min | Beat |
|-----|------|
| 0–1 | One-liner + architecture |
| 1–4 | Grafana + chat metrics |
| 4–6 | Rules file |
| 6–11 | Kill site-b → email + call → restore |
| 11–13 | One control plane + Q&A |

---

## Don’t say / don’t show

- Don’t open `secrets.env` on screen
- Don’t push to `flwrlabs/flower` `main`
- Don’t dwell on nested `Untitled` git vs `flower` fork — “product in flower fork, demo harness in fleet-desk”

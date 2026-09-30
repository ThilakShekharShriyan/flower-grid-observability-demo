# Flower Grid Observability — Hackathon Demo Script (~12–15 min)

Catchy talk track. Theatrical, high-energy, still true to the stack.
Audience: judges / partners who skim Flower.

**Vibe:** Mission control + courtroom drama. You are the fleet commander.
The grid is the client. Prometheus is the witness. Twilio is the bailiff.

---

## One-liner (memorize this)

**Three sites. Live metrics. One agent. When a SuperNode dies — we don't pager-fatigue you with a Slack emoji. We call your phone.**

Alt (more product):
**Named SuperNodes speak Prometheus. `flwr chat` interrogates them with first-party tools. Rules don't just alert — they exclude, pause, email, and ring.**

---

## Architecture (30 sec)

```
site-a / site-b / site-c  →  TLS SuperLink (local-agent)
         │                         │
         ▼                         ▼
   metrics plane  →  Prometheus  →  Grafana (the wall)
                              │
                    fleet_ops  (the nervous system)
                              │
                    email + Twilio voice  (the bailiff)
```

**Say:** “This isn't a dashboard bolted onto Flower. The grid has a nervous system — metrics in, decisions out, humans paged when the fleet bleeds.”

---

## Pre-flight (before judges sit)

1. Secrets loaded (never show on screen).
2. Stack hot: SuperLink, 3 SuperNodes, Prom `:9090`, exporter `:9105`, training loop.
3. `flwr chat` already open. Phone on the table. Inbox open.
4. Health check: all three sites in `flower_supernode_up`.

---

## SLIDE / BEAT SCRIPT

### Beat 0 — Cold open (30 sec)
**On slide:** `THE GRID IS WATCHING` · Flower Agent Grid Observability  
**Say:**  
“Forget another MLOps dashboard. We gave Flower a pulse, a brain, and a phone number.  
In the next twelve minutes: live fleet metrics, an agent that actually queries Prometheus, and a SuperNode assassination that ends with *your* phone ringing.”

---

### Beat 1 — The claim (45 sec)
**On slide:** Observe → Ask → Act  
Three sites. First-party tools. Email + voice. One control plane.  
**Say:**  
“Named SuperNodes publish live metrics to Prometheus.  
`flwr chat` doesn't hallucinate fleet health — it *interrogates* it with first-party tools.  
When a site drops, the same rules exclude it from training, email on-call, and place a Twilio voice call.  
Observe. Ask. Act. No duct tape.”

---

### Beat 2 — Architecture flex (60 sec)
**On slide:** sites → SuperLink → Prom/Grafana → fleet_ops → humans  
**Say:**  
“Left side: three named sites — site-a, site-b, site-c — on TLS SuperLink.  
Middle: Prometheus is the witness stand. Grafana is the war room wall.  
Right: `fleet_ops` — first-party Flower connector. Chat agent and ServerApp share it.  
When the fleet lies, we don't open a ticket. We page a human. Voice included.”

---

### Beat 3 — Act 1: Show the pulse (2–3 min)
**On slide:** `flower_site_train_metric` · `flower_site_online` · `flower_supernodes_online`  
**Say:**  
“Every SuperNode is a named site — not an anonymous worker.  
These aren't scraped leftovers. They're first-class Flower series in Prometheus.  
Three greens. Fleet breathing. That's our baseline before we start stabbing things.”

**Then chat — paste:**
> What are the site train metrics for the last 5 minutes? Use the fleet tools and cite the Prometheus source.

**Say while it runs:**  
“Plain English in. Tool call out. I want to see `fleet_get_site_metrics` and a Prometheus URL in the answer — receipts, not vibes.”

**Optional roast follow-up:**
> Is any site offline or trending unhealthy — or are we still living our best fleet life?

---

### Beat 4 — Act 2: Rules with teeth (2 min)
**On slide:**
| Rule | What hits |
|------|-----------|
| `site_offline` | exclude + email + **CALL** |
| `fleet_too_thin` | pause training + email + **CALL** |
| high/low train | exclude + email |

**Say:**  
“Alerts aren't a YAML graveyard. They're law the agent and ServerApp both obey.  
Site goes dark? We exile it from FedAvg, email the on-call, and the bailiff dials.  
Fleet drops under three nodes? Training freezes. Same law. Same file. No 'wait, which script?'”

---

### Beat 5 — Act 3: Assassinate site-b (5 min) — THE MONEY SHOT
**On slide:** `simulate_node_down.py --site site-b`  
Stop → Prom flips → email → **phone rings** → revive  

**Say before Enter:**  
“Judges — phones out or watch mine. We're about to murder site-b in cold blood.  
Prometheus will flip it offline. Resend will hit the inbox. Twilio will call.  
This is not a mock. This is the bailiff.”

**Run:**
```bash
cd fleet-desk
set -a && source ~/.flwr/secrets.env && set +a
export PYTHONPATH=.
../flower/framework/.venv/bin/python simulate_node_down.py --site site-b --timeout 120
```

**Narrate like a sports cast:**
1. “Site-b is down. Process gone.”
2. “Prometheus: two of three. The fleet is bleeding.”
3. “Rules fired — exclude, pause, page.”
4. “Inbox — Prometheus crime-scene report.”
5. “Phone — that's the Auto Response. The grid is calling you.”
6. “And… site-b resurrected. Fleet back to three. Clean kill. Clean revive.”

**Optional chat mid-chaos:**
> Site-b just went offline. Evaluate fleet alerts and summarize what actions fired — like you're briefing the war room.

---

### Beat 6 — Close like a winner (2 min)
**On slide:** ONE CONTROL PLANE  
Chat · ServerApp · email · voice · same rules · same `grid_control.json`  

**Say:**  
“Chat, training loop, email, and voice — same rules, same control file.  
`fleet_ops` lives in the Flower fork. `fleet-desk` is the operator stage for this demo — not a second product.  
We didn't build another monitoring toy. We gave federated learning a nervous system with a phone number.”

**Kill shot question:**  
“Where do *you* hang the next rule — battery, latency, or data drift? Because the grid is already listening.”

---

## Timing card (print / sticky)

| Min | Beat | Energy |
|-----|------|--------|
| 0–1 | Cold open + claim | Loud |
| 1–4 | Metrics + chat receipts | Confident |
| 4–6 | Rules with teeth | Sharp |
| 6–11 | Kill site-b → ring → revive | Chaos → triumph |
| 11–13 | One plane + kill-shot Q | Mic drop |

---

## Backup lines (stay charismatic)

| Failure | Line |
|---------|------|
| Empty metrics | “Pulse flatlined on :9105 — defibrillating the exporter.” |
| Chat abort | “Agent blinked. One retry — FAB/model.” |
| Email missing | “Courier lost the address — `RESEND_TO` typo, fixed before.” |
| No call | “Bailiff's in the Twilio lobby — check the SID.” |
| Node stuck | “Heartbeat lag — reconnecting SuperNodes.” |

---

## Don't

- Don't open `secrets.env` on the projector.
- Don't apologize mid-demo — narrate the recovery.
- Don't say “basically” or “just a prototype.” Say **live stack**.
- Don't push to `flwrlabs/flower` `main`.

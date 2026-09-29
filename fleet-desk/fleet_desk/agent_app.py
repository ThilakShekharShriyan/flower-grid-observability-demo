"""Grid Drift Tribunal — multi-role agents on live Prometheus + SuperNodes.

Roles in one AgentApp FAB:
  Chief of Watch (SuperLink)  – PromQL scout, names a defendant, runs the vote
  Defendant (SuperNode)       – files a defense from its local briefing
  Jurors (other SuperNodes)   – vote clear / watch / quarantine

Promotion gate (replaces the old promote/hold desk):
  - Jurors vote in `_juror_vote` (clear / watch / quarantine)
  - Chief decides in `_chief_verdict` — `quarantine` blocks promotion;
    `clear` allows a later promotion review; `watch` / `fleet_hold` pause
  - Verdict gauges land in Prometheus for Grafana + the email agent

The verdict is written back as Prometheus gauges so Grafana shows the case.
"""

from __future__ import annotations

import json
from pathlib import Path

from flwr.agentapp import AgentApp, AgentSession
from flwr.app import Context

from fleet_desk.email_alert import send_issue_email, should_alert
from fleet_desk.oncall import assignee_for

DECISION_METRICS = Path("/tmp/flower-agent-audit/flower_decision.prom")
DRIFT_WATCH = 0.03
DRIFT_QUARANTINE = 0.08
HEARTBEAT_FLOOR_SECONDS = 20.0
REPLY_TIMEOUT_SECONDS = 180.0

app = AgentApp()


@app.main()
def main(agent: AgentSession, context: Context) -> None:
    """Run the tribunal as Chief of Watch, or answer as defendant/juror."""
    del context
    if _is_site(agent):
        _answer_site(agent)
        return
    _tribunal(agent)


def _is_site(agent: AgentSession) -> bool:
    names = {tool["name"] for tool in agent.grid.tools()}
    return "push_reply_message" in names and "get_nodes" not in names


def _answer_site(agent: AgentSession) -> None:
    briefing = _briefing(agent.prompt)
    role = str(briefing.get("role") or "juror")
    if role == "defendant":
        vote, reason, sentence = _defendant_plea(briefing)
    else:
        vote, reason, sentence = _juror_vote(briefing)
    payload = json.dumps(
        {
            "node_id": briefing.get("node_id"),
            "node": briefing.get("node_name"),
            "location": briefing.get("location"),
            "role": role,
            "vote": vote,
            "reason": reason,
            "sentence": sentence,
            "own_train": briefing.get("own_train"),
            "drift": briefing.get("own_drift"),
        }
    )
    _call(agent.grid, "push_reply_message", {"payload": payload}, "site-reply")
    print(f"[{role}] {briefing.get('node_name')}: {sentence}", flush=True)


def _tribunal(agent: AgentSession) -> None:
    runs = _scalar(agent, "flower_training_runs_completed")
    failures = _scalar(agent, "flower_training_result_failures")
    sampled = _scalar(agent, "flower_training_nodes_sampled")
    online = _scalar(agent, "flower_supernodes_online")
    train_latest = _scalar(agent, "flower_training_train_metric")
    train_high = _scalar(agent, "max_over_time(flower_training_train_metric[5m])")
    train_low = _scalar(agent, "min_over_time(flower_training_train_metric[5m])")
    site_train = _labeled_values(agent, "flower_site_train_metric", "name")
    heartbeats = _labeled_values(
        agent, "flower_supernode_heartbeat_remaining_seconds", "name"
    )
    nodes = _call(agent.grid, "get_nodes", {"sample_size": None}, "grid-nodes")["nodes"]

    swing = None
    if train_high or train_low:
        swing = abs(train_high - train_low)

    defendant_name, defendant_train, drift_map = _pick_defendant(
        site_train, train_latest
    )
    case = {
        "ask": "drift_tribunal",
        "runs_completed": runs,
        "failures": failures,
        "nodes_online": online,
        "nodes_sampled": sampled,
        "train_latest": train_latest,
        "site_train": site_train,
        "swing": swing,
        "defendant": defendant_name,
        "defendant_train": defendant_train,
        "federation_mean": train_latest,
        "drift_map": drift_map,
        "thresholds": {"watch": DRIFT_WATCH, "quarantine": DRIFT_QUARANTINE},
    }

    print("GRID DRIFT TRIBUNAL", flush=True)
    print(
        "Scout (Prometheus): "
        f"{runs:.0f} completed runs, {online:.0f} SuperNodes online, "
        f"{sampled:.0f} sampled last round, {failures:.0f} failures.",
        flush=True,
    )
    if train_latest:
        sites = ", ".join(
            f"{name}={value:.3f} (Δ{drift_map.get(name, 0.0):+.3f})"
            for name, value in sorted(site_train.items())
        )
        swing_text = "n/a" if swing is None else f"{swing:.3f}"
        print(
            f"Federation train={train_latest:.3f}, 5m swing={swing_text}. "
            f"Sites: {sites or 'n/a'}.",
            flush=True,
        )
    else:
        print("Federation train metric: none yet — tribunal will pause.", flush=True)

    if defendant_name:
        print(
            f"Accused: {defendant_name} "
            f"(train={defendant_train:.3f}, "
            f"|drift|={abs(drift_map.get(defendant_name, 0.0)):.3f} "
            f"from federation mean).",
            flush=True,
        )
    else:
        print("No defendant — not enough per-site series to open a case.", flush=True)

    outgoing = []
    for node in nodes:
        name = node.get("name") or node["id"]
        own_train = site_train.get(name)
        own_drift = drift_map.get(name)
        role = "defendant" if name == defendant_name else "juror"
        briefing = {
            **case,
            "role": role,
            "node_id": node["id"],
            "node_name": name,
            "location": node.get("location"),
            "heartbeat_seconds": heartbeats.get(name),
            "own_train": own_train,
            "own_drift": own_drift,
        }
        outgoing.append(
            {
                "dst_node_id": node["id"],
                "payload": json.dumps(briefing),
                "reply_to_message_id": None,
            }
        )
        print(
            f"Summoned {name} as {role} ({node.get('location') or 'no location'}).",
            flush=True,
        )

    replies: list[dict[str, object]] = []
    if outgoing:
        pushed = _call(
            agent.grid, "push_messages", {"messages": outgoing}, "grid-ask"
        )
        message_ids = [
            result["message_id"]
            for result in pushed["results"]
            if result.get("message_id")
        ]
        if message_ids:
            pulled = _call(
                agent.grid,
                "pull_messages",
                {"message_ids": message_ids, "timeout": REPLY_TIMEOUT_SECONDS},
                "grid-replies",
            )
            for message in pulled["messages"]:
                if message.get("error") or not message.get("payload"):
                    continue
                replies.append(json.loads(message["payload"]))
            pending = pulled.get("pending_message_ids") or []
            if pending:
                print(f"Still waiting on {len(pending)} site(s).", flush=True)

    for reply in replies:
        print(
            f"[{reply.get('role')}] {reply.get('node')}: {reply.get('sentence')}",
            flush=True,
        )

    outcome, reason, sentence = _chief_verdict(
        expected=len(nodes),
        replies=replies,
        defendant=defendant_name,
        drift_map=drift_map,
        online=online,
        failures=failures,
    )
    print(f"Verdict: {sentence}", flush=True)
    _write_decision(
        outcome=outcome,
        reason=reason,
        swing=swing,
        defendant=defendant_name,
        drift_map=drift_map,
        replies=replies,
    )
    if should_alert(outcome):
        person = assignee_for(defendant_name)
        status = send_issue_email(
            outcome=outcome,
            reason=reason,
            sentence=sentence,
            defendant=defendant_name,
            drift_map=drift_map,
            replies=replies,
            to_address=person["email"],
            assignee_name=person["name"],
        )
        print(f"Email agent: {status}", flush=True)
    else:
        print("Email agent: no issue — skipping Twilio alert.", flush=True)
    agent.events.emit({"type": "message", "role": "assistant", "content": sentence})


def _pick_defendant(
    site_train: dict[str, float], federation: float
) -> tuple[str | None, float | None, dict[str, float]]:
    if not site_train or not federation:
        return None, None, {}
    drift_map = {name: value - federation for name, value in site_train.items()}
    defendant = max(drift_map, key=lambda name: abs(drift_map[name]))
    return defendant, site_train[defendant], drift_map


def _defendant_plea(briefing: dict[str, object]) -> tuple[str, str, str]:
    name = str(briefing.get("node_name") or "this site")
    heartbeat = briefing.get("heartbeat_seconds")
    own_drift = briefing.get("own_drift")
    own_train = briefing.get("own_train")
    federation = briefing.get("federation_mean")
    if isinstance(heartbeat, (int, float)) and heartbeat < HEARTBEAT_FLOOR_SECONDS:
        return (
            "recuse",
            "heartbeat_low",
            (
                f"{name} cannot stand trial — only {heartbeat:.0f}s of heartbeat left "
                "before it drops off the federation."
            ),
        )
    if not isinstance(own_drift, (int, float)) or not isinstance(own_train, (int, float)):
        return (
            "not_guilty",
            "no_local_metric",
            f"{name} pleads not guilty: Prometheus has no local train series yet.",
        )
    abs_drift = abs(own_drift)
    mean_text = (
        f"{federation:.3f}" if isinstance(federation, (int, float)) else "unknown"
    )
    if abs_drift < DRIFT_WATCH:
        return (
            "not_guilty",
            "within_noise",
            (
                f"{name} pleads not guilty. Local train={own_train:.3f} is only "
                f"{abs_drift:.3f} from the federation mean ({mean_text}) — noise, "
                "not sabotage."
            ),
        )
    if abs_drift < DRIFT_QUARANTINE:
        return (
            "mitigate",
            "acknowledge_watch",
            (
                f"{name} acknowledges a watch-band drift of {abs_drift:.3f} "
                f"(local={own_train:.3f}, mean={mean_text}) and asks to keep "
                "training instead of quarantine."
            ),
        )
    return (
        "mitigate",
        "acknowledge_outlier",
        (
            f"{name} concedes it is the outlier (|drift|={abs_drift:.3f}, "
            f"local={own_train:.3f} vs mean={mean_text}) but argues for one more "
            "training window before anyone quarantines it from promotion."
        ),
    )


def _juror_vote(briefing: dict[str, object]) -> tuple[str, str, str]:
    name = str(briefing.get("node_name") or "this site")
    defendant = str(briefing.get("defendant") or "the accused")
    drift_map = briefing.get("drift_map")
    heartbeat = briefing.get("heartbeat_seconds")
    failures = briefing.get("failures")
    online = briefing.get("nodes_online")

    if isinstance(heartbeat, (int, float)) and heartbeat < HEARTBEAT_FLOOR_SECONDS:
        return (
            "abstain",
            "heartbeat_low",
            f"{name} abstains — its own heartbeat is critically low.",
        )
    if isinstance(failures, (int, float)) and failures > 0:
        return (
            "quarantine",
            "fleet_failures",
            (
                f"{name} votes to quarantine {defendant}. The fleet already shows "
                f"{failures:.0f} client failure(s); an outlier on top is too risky."
            ),
        )
    if isinstance(online, (int, float)) and online < 3:
        return (
            "watch",
            "fleet_thin",
            (
                f"{name} votes watch-only. With fewer than three SuperNodes online, "
                "quarantine would shrink the federation further."
            ),
        )

    accused_drift = 0.0
    if isinstance(drift_map, dict) and isinstance(drift_map.get(defendant), (int, float)):
        accused_drift = abs(float(drift_map[defendant]))

    if accused_drift >= DRIFT_QUARANTINE:
        return (
            "quarantine",
            "drift_over_quarantine",
            (
                f"{name} votes to quarantine {defendant} from the next promotion. "
                f"|drift|={accused_drift:.3f} crosses the {DRIFT_QUARANTINE:.2f} line."
            ),
        )
    if accused_drift >= DRIFT_WATCH:
        return (
            "watch",
            "drift_over_watch",
            (
                f"{name} votes to put {defendant} on watch. "
                f"|drift|={accused_drift:.3f} is elevated but not quarantine-grade."
            ),
        )
    return (
        "clear",
        "drift_within_noise",
        (
            f"{name} votes to clear {defendant}. "
            f"|drift|={accused_drift:.3f} is inside the noise band."
        ),
    )


def _chief_verdict(
    *,
    expected: int,
    replies: list[dict[str, object]],
    defendant: str | None,
    drift_map: dict[str, float],
    online: float,
    failures: float,
) -> tuple[str, str, str]:
    if expected == 0 or len(replies) < expected:
        return (
            "mistrial",
            "missing_site",
            "Mistrial. A site did not answer the summons.",
        )
    if any(r.get("vote") == "recuse" for r in replies):
        return (
            "mistrial",
            "defendant_recused",
            "Mistrial. The accused site is about to leave the federation.",
        )
    if not defendant:
        return (
            "no_case",
            "no_defendant",
            "No case. Prometheus did not expose enough per-site train series.",
        )
    if online < 3 or failures > 0:
        return (
            "fleet_hold",
            "fleet_not_ready",
            (
                "Hold the fleet. Do not promote anyone while the SuperNode set is "
                "incomplete or training failures are non-zero."
            ),
        )

    juror_votes = [
        str(r.get("vote"))
        for r in replies
        if r.get("role") == "juror" and r.get("vote") != "abstain"
    ]
    abs_drift = abs(drift_map.get(defendant, 0.0))

    if juror_votes and all(v == "quarantine" for v in juror_votes):
        return (
            "quarantine",
            "unanimous_quarantine",
            (
                f"Quarantine {defendant} from the next promotion. "
                f"Both jurors agreed (|drift|={abs_drift:.3f})."
            ),
        )
    if "quarantine" in juror_votes:
        return (
            "watch",
            "split_quarantine",
            (
                f"Watch {defendant}. At least one juror wanted quarantine "
                f"(|drift|={abs_drift:.3f}); Chief of Watch will not escalate alone."
            ),
        )
    if juror_votes and all(v == "clear" for v in juror_votes) and abs_drift < DRIFT_WATCH:
        return (
            "clear",
            "unanimous_clear",
            (
                f"Clear {defendant}. Jurors see noise-level drift "
                f"(|drift|={abs_drift:.3f}). Promotion review may proceed."
            ),
        )
    return (
        "watch",
        "elevated_or_split",
        (
            f"Watch {defendant}. Keep training and re-open the tribunal after the "
            f"next window (|drift|={abs_drift:.3f})."
        ),
    )


def _briefing(prompt: str) -> dict[str, object]:
    try:
        outer = json.loads(prompt)
    except json.JSONDecodeError:
        return {}
    if not isinstance(outer, dict):
        return {}
    payload = outer.get("payload", outer)
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            return {}
    return payload if isinstance(payload, dict) else {}


def _scalar(agent: AgentSession, query: str) -> float:
    series = _query(agent, query)
    if not series:
        return 0.0
    value = series[0].get("value")
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _labeled_values(agent: AgentSession, query: str, label: str) -> dict[str, float]:
    values: dict[str, float] = {}
    for item in _query(agent, query):
        labels = item.get("labels")
        if not isinstance(labels, dict):
            continue
        key = labels.get(label)
        if not isinstance(key, str):
            continue
        try:
            values[key] = float(item.get("value"))
        except (TypeError, ValueError):
            continue
    return values


def _query(agent: AgentSession, query: str) -> list[dict[str, object]]:
    result = _call(
        agent.connectors, "prometheus_query", {"query": query}, f"prom-{query}"
    )
    series = result.get("series")
    if not isinstance(series, list):
        return []
    return [item for item in series if isinstance(item, dict)]


def _call(api: object, name: str, arguments: dict[str, object], call_id: str) -> dict:
    item = api.call({"name": name, "call_id": call_id, "arguments": arguments})
    output = item.get("output") if isinstance(item, dict) else None
    if isinstance(output, str):
        output = json.loads(output)
    if not isinstance(output, dict):
        raise RuntimeError(f"{name} returned no object.")
    return output


def _write_decision(
    *,
    outcome: str,
    reason: str,
    swing: float | None,
    defendant: str | None,
    drift_map: dict[str, float],
    replies: list[dict[str, object]],
) -> None:
    accused = _label(defendant or "none")
    lines = [
        "# HELP flower_agent_decision 1 for the tribunal verdict.",
        "# TYPE flower_agent_decision gauge",
        (
            f'flower_agent_decision{{outcome="{_label(outcome)}",'
            f'reason="{_label(reason)}",defendant="{accused}"}} 1'
        ),
        "# HELP flower_agent_metric_swing Train-metric swing the tribunal reviewed.",
        "# TYPE flower_agent_metric_swing gauge",
        "flower_agent_metric_swing " + ("0" if swing is None else f"{swing:.6f}"),
        "# HELP flower_agent_site_drift Signed drift of each site from federation mean.",
        "# TYPE flower_agent_site_drift gauge",
    ]
    for name, drift in sorted(drift_map.items()):
        lines.append(
            f'flower_agent_site_drift{{name="{_label(name)}",'
            f'defendant="{"true" if name == defendant else "false"}"}} {drift:.6f}'
        )
    lines.extend(
        [
            "# HELP flower_agent_vote 1 for each site reply in the latest tribunal.",
            "# TYPE flower_agent_vote gauge",
        ]
    )
    for reply in replies:
        node = _label(str(reply.get("node") or "unknown"))
        choice = _label(str(reply.get("vote") or "unknown"))
        role = _label(str(reply.get("role") or "unknown"))
        lines.append(
            f'flower_agent_vote{{node="{node}",vote="{choice}",role="{role}"}} 1'
        )
    DECISION_METRICS.parent.mkdir(parents=True, exist_ok=True)
    DECISION_METRICS.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _label(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "")

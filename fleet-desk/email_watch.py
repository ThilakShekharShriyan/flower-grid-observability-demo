"""Email agent: if Grafana/Prometheus already shows an issue, page the operator.

Reads the latest tribunal gauges from Prometheus (or the local decision file)
and sends one Twilio email when the outcome is quarantine / mistrial / fleet_hold.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from pathlib import Path

from fleet_desk.email_alert import (
    ISSUE_OUTCOMES,
    send_issue_email,
    should_alert,
)

PROMETHEUS = "http://127.0.0.1:9090"
DECISION = Path("/tmp/flower-agent-audit/flower_decision.prom")


def _prom_query(query: str) -> list[dict]:
    url = f"{PROMETHEUS}/api/v1/query?{urllib.parse.urlencode({'query': query})}"
    with urllib.request.urlopen(url, timeout=15) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if payload.get("status") != "success":
        return []
    return payload.get("data", {}).get("result") or []


def _from_prometheus() -> tuple[str, str, str, str | None, dict[str, float], list[dict]]:
    decisions = _prom_query("flower_agent_decision")
    if not decisions:
        raise RuntimeError("No flower_agent_decision series in Prometheus yet.")
    metric = decisions[0]["metric"]
    outcome = str(metric.get("outcome") or "unknown")
    reason = str(metric.get("reason") or "unknown")
    defendant = metric.get("defendant")
    if defendant in (None, "none"):
        defendant = None
    drift_map: dict[str, float] = {}
    for row in _prom_query("flower_agent_site_drift"):
        name = row["metric"].get("name")
        if name:
            drift_map[name] = float(row["value"][1])
    replies: list[dict] = []
    for row in _prom_query("flower_agent_vote"):
        replies.append(
            {
                "node": row["metric"].get("node"),
                "role": row["metric"].get("role"),
                "vote": row["metric"].get("vote"),
                "sentence": f"{row['metric'].get('node')} voted {row['metric'].get('vote')}",
            }
        )
    sentence = f"Prometheus shows outcome={outcome} reason={reason}."
    return outcome, reason, sentence, defendant, drift_map, replies


def main() -> None:
    outcome, reason, sentence, defendant, drift_map, replies = _from_prometheus()
    print(f"Watch: outcome={outcome} reason={reason} defendant={defendant}", flush=True)
    if not should_alert(outcome):
        print(
            f"Email agent: '{outcome}' is not an issue "
            f"(alerts on {sorted(ISSUE_OUTCOMES)}).",
            flush=True,
        )
        return
    status = send_issue_email(
        outcome=outcome,
        reason=reason,
        sentence=sentence,
        defendant=defendant,
        drift_map=drift_map,
        replies=replies,
    )
    print(f"Email agent: {status}", flush=True)


if __name__ == "__main__":
    main()

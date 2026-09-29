"""Dual-model Grid Insight Desk (Nebius MiniMax + Kimi).

MiniMax formulates an operator briefing from live Prometheus / tribunal state.
Kimi turns that into concrete remediation steps for the federation.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

SECRETS = Path.home() / ".flwr" / "secrets.env"
ALERT_DETAIL = Path("/tmp/flower-agent-audit/last_email_alert.json")
REPORT = Path("/tmp/flower-agent-audit/grid_insights.json")
PROMETHEUS = os.environ.get("FLWR_PROMETHEUS_URL", "http://127.0.0.1:9090")


def _load_env() -> dict[str, str]:
    values: dict[str, str] = {}
    if SECRETS.exists():
        for line in SECRETS.read_text(encoding="utf-8").splitlines():
            text = line.strip()
            if not text or text.startswith("#") or "=" not in text:
                continue
            if text.startswith("export "):
                text = text[len("export ") :]
            key, value = text.split("=", 1)
            values[key] = value.strip().strip("'").strip('"')
    values.update({k: v for k, v in os.environ.items() if k.startswith("NEBIUS_") or k.startswith("FLWR_")})
    return values


def _prom(query: str) -> list[dict]:
    url = f"{PROMETHEUS}/api/v1/query?{urllib.parse.urlencode({'query': query})}"
    with urllib.request.urlopen(url, timeout=15) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if payload.get("status") != "success":
        return []
    return payload.get("data", {}).get("result") or []


def _scalar(query: str) -> float | None:
    rows = _prom(query)
    if not rows:
        return None
    try:
        return float(rows[0]["value"][1])
    except (KeyError, TypeError, ValueError, IndexError):
        return None


def _labeled(query: str, label: str) -> dict[str, float]:
    out: dict[str, float] = {}
    for row in _prom(query):
        name = row.get("metric", {}).get(label)
        if not name:
            continue
        try:
            out[name] = float(row["value"][1])
        except (KeyError, TypeError, ValueError):
            continue
    return out


def collect_snapshot() -> dict:
    site_train = _labeled("flower_site_train_metric", "name")
    federation = _scalar("flower_training_train_metric")
    drift = {}
    if federation is not None:
        drift = {name: value - federation for name, value in site_train.items()}
    decision_rows = _prom("flower_agent_decision")
    decision = decision_rows[0]["metric"] if decision_rows else {}
    votes = [
        {
            "node": row["metric"].get("node"),
            "role": row["metric"].get("role"),
            "vote": row["metric"].get("vote"),
        }
        for row in _prom("flower_agent_vote")
    ]
    online = sorted(_labeled('flower_supernode_up{status="online"}', "name"))
    alert = None
    if ALERT_DETAIL.exists():
        try:
            alert = json.loads(ALERT_DETAIL.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            alert = None
    return {
        "supernodes_online": _scalar("flower_supernodes_online"),
        "online_sites": online,
        "runs_completed": _scalar("flower_training_runs_completed"),
        "failures": _scalar("flower_training_result_failures"),
        "nodes_sampled": _scalar("flower_training_nodes_sampled"),
        "federation_train": federation,
        "site_train": site_train,
        "site_drift": drift,
        "swing_5m": (
            None
            if _scalar("max_over_time(flower_training_train_metric[5m])") is None
            else abs(
                (_scalar("max_over_time(flower_training_train_metric[5m])") or 0.0)
                - (_scalar("min_over_time(flower_training_train_metric[5m])") or 0.0)
            )
        ),
        "tribunal_decision": decision,
        "tribunal_votes": votes,
        "last_alert": alert,
    }


def _extract_text(payload: dict) -> str:
    if isinstance(payload.get("output_text"), str) and payload["output_text"].strip():
        return payload["output_text"].strip()
    parts: list[str] = []
    for item in payload.get("output") or []:
        if not isinstance(item, dict):
            continue
        if item.get("type") != "message":
            continue
        for content in item.get("content") or []:
            if isinstance(content, dict) and content.get("type") == "output_text":
                text = content.get("text")
                if isinstance(text, str) and text.strip():
                    parts.append(text.strip())
    return "\n".join(parts).strip()


def call_model(*, model: str, api_key: str, endpoint: str, prompt: str) -> str:
    body = {"model": model, "input": prompt, "stream": False}
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read(300).decode("utf-8", errors="replace")
        raise RuntimeError(f"model HTTP {exc.code}: {detail}") from exc
    text = _extract_text(payload)
    if not text:
        raise RuntimeError("model returned no output_text")
    return text


def main() -> None:
    env = _load_env()
    endpoint = env.get("NEBIUS_ENDPOINT") or env.get("FLWR_MODEL_API_ENDPOINT")
    if not endpoint:
        raise SystemExit("NEBIUS_ENDPOINT / FLWR_MODEL_API_ENDPOINT missing")

    snapshot = collect_snapshot()
    print("Collected fleet snapshot from Prometheus.", flush=True)
    print(
        f"Online={snapshot['online_sites']} runs={snapshot['runs_completed']} "
        f"federation={snapshot['federation_train']} "
        f"decision={snapshot['tribunal_decision'].get('outcome')}",
        flush=True,
    )

    briefing_prompt = f"""You are MiniMax, the Flower Grid briefing officer.
Read this live federation snapshot (JSON) and write a concise operator briefing.

Cover:
1) What is happening right now (fleet health, training, drift)
2) What the tribunal / last alert implies for model promotion
3) Who is at risk and why (name sites)
4) One clear recommendation: promote / keep training / quarantine / page on-call

Be concrete. Use the numbers. No fluff. Max 250 words.

SNAPSHOT:
{json.dumps(snapshot, indent=2)}
"""

    print("\n=== MiniMax (understand / formulate) ===", flush=True)
    briefing = call_model(
        model=env["NEBIUS_MINIMAX_MODEL"],
        api_key=env["NEBIUS_MINIMAX_API_KEY"],
        endpoint=endpoint,
        prompt=briefing_prompt,
    )
    print(briefing, flush=True)

    kimi_prompt = f"""You are Kimi-K2.7-Code, the Flower Grid remediation engineer.
Given the fleet snapshot and MiniMax briefing, produce actionable ops insights.

Return markdown with these sections only:
## Diagnosis
## Immediate actions (ordered checklist)
## Prometheus / Grafana checks
## Promotion gate
## If a SuperNode is down

Be specific to this federation (site-a/b/c, flower_* metrics, fleet-desk tribunal).
No secrets. Max 300 words.

SNAPSHOT:
{json.dumps(snapshot, indent=2)}

MINIMAX BRIEFING:
{briefing}
"""

    print("\n=== Kimi (insights / remediation) ===", flush=True)
    remediation = call_model(
        model=env["NEBIUS_KIMI_MODEL"],
        api_key=env["NEBIUS_KIMI_API_KEY"],
        endpoint=endpoint,
        prompt=kimi_prompt,
    )
    print(remediation, flush=True)

    report = {
        "snapshot": snapshot,
        "minimax_briefing": briefing,
        "kimi_remediation": remediation,
        "models": {
            "briefing": env.get("NEBIUS_MINIMAX_MODEL"),
            "remediation": env.get("NEBIUS_KIMI_MODEL"),
        },
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"\nSaved {REPORT}", flush=True)


if __name__ == "__main__":
    main()

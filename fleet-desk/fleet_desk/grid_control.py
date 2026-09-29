"""Shared grid alert rules + control plane used by fleet_ops and ServerApp.

Files:
  ~/.flwr/grid_alerts.json     – user-editable alert rules
  /tmp/flower-agent-audit/grid_control.json – live exclude/pause state
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

ALERTS_PATH = Path.home() / ".flwr" / "grid_alerts.json"
CONTROL_PATH = Path("/tmp/flower-agent-audit/grid_control.json")
SECRETS = Path.home() / ".flwr" / "secrets.env"
DEFAULT_PROMETHEUS = os.environ.get("FLWR_PROMETHEUS_URL", "http://127.0.0.1:9090")

DEFAULT_RULES: dict[str, Any] = {
    "rules": [
        {
            "id": "high_site_train",
            "enabled": True,
            "metric": "flower_site_train_metric",
            "op": ">",
            "threshold": 0.85,
            "scope": "per_site",
            "actions": ["exclude_site", "email"],
            "description": (
                "If a site's train metric exceeds 0.85, exclude that SuperNode "
                "from the next FedAvg rounds and email on-call."
            ),
        },
        {
            "id": "low_site_train",
            "enabled": True,
            "metric": "flower_site_train_metric",
            "op": "<",
            "threshold": 0.15,
            "scope": "per_site",
            "actions": ["exclude_site", "email"],
            "description": (
                "If a site's train metric collapses below 0.15, treat it as "
                "unhealthy: exclude from the next rounds and email on-call."
            ),
        },
        {
            "id": "fleet_too_thin",
            "enabled": True,
            "metric": "flower_supernodes_online",
            "op": "<",
            "threshold": 3,
            "scope": "scalar",
            "actions": ["pause_training", "email"],
            "description": (
                "If fewer than 3 SuperNodes are online, pause further training "
                "and email fleet on-call."
            ),
        },
    ]
}


def _load_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return json.loads(json.dumps(default))
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return json.loads(json.dumps(default))
    return data if isinstance(data, dict) else json.loads(json.dumps(default))


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def ensure_default_rules() -> dict[str, Any]:
    if not ALERTS_PATH.exists():
        _write_json(ALERTS_PATH, DEFAULT_RULES)
    return load_rules()


def load_rules() -> dict[str, Any]:
    data = _load_json(ALERTS_PATH, DEFAULT_RULES)
    rules = data.get("rules")
    if not isinstance(rules, list):
        data = json.loads(json.dumps(DEFAULT_RULES))
    return data


def save_rules(data: dict[str, Any]) -> dict[str, Any]:
    if "rules" not in data or not isinstance(data["rules"], list):
        raise ValueError("rules document must contain a rules array")
    _write_json(ALERTS_PATH, data)
    return data


def load_control() -> dict[str, Any]:
    data = _load_json(
        CONTROL_PATH,
        {"excluded_sites": [], "pause_training": False, "last_evaluation": None},
    )
    data.setdefault("excluded_sites", [])
    data.setdefault("pause_training", False)
    if not isinstance(data["excluded_sites"], list):
        data["excluded_sites"] = []
    return data


def save_control(data: dict[str, Any]) -> dict[str, Any]:
    _write_json(CONTROL_PATH, data)
    return data


def excluded_sites() -> set[str]:
    return {str(name) for name in load_control().get("excluded_sites", [])}


def pause_training() -> bool:
    return bool(load_control().get("pause_training"))


def set_excluded(site: str, *, excluded: bool, reason: str = "") -> dict[str, Any]:
    control = load_control()
    sites = {str(name) for name in control.get("excluded_sites", [])}
    if excluded:
        sites.add(site)
    else:
        sites.discard(site)
    control["excluded_sites"] = sorted(sites)
    control["last_change"] = {
        "site": site,
        "excluded": excluded,
        "reason": reason,
    }
    return save_control(control)


def set_pause(paused: bool, reason: str = "") -> dict[str, Any]:
    control = load_control()
    control["pause_training"] = bool(paused)
    control["pause_reason"] = reason
    return save_control(control)


def upsert_rule(rule: dict[str, Any]) -> dict[str, Any]:
    if not rule.get("id"):
        raise ValueError("rule.id is required")
    data = load_rules()
    rules = list(data.get("rules") or [])
    replaced = False
    for index, existing in enumerate(rules):
        if existing.get("id") == rule["id"]:
            merged = {**existing, **rule}
            rules[index] = merged
            replaced = True
            break
    if not replaced:
        rules.append(rule)
    data["rules"] = rules
    return save_rules(data)


def delete_rule(rule_id: str) -> dict[str, Any]:
    data = load_rules()
    data["rules"] = [r for r in (data.get("rules") or []) if r.get("id") != rule_id]
    return save_rules(data)


def _compare(value: float, op: str, threshold: float) -> bool:
    if op == ">":
        return value > threshold
    if op == ">=":
        return value >= threshold
    if op == "<":
        return value < threshold
    if op == "<=":
        return value <= threshold
    if op == "==":
        return abs(value - threshold) < 1e-12
    if op == "!=":
        return abs(value - threshold) >= 1e-12
    raise ValueError(f"unsupported op {op}")


def _prom_query(query: str) -> list[dict[str, Any]]:
    base = os.environ.get("FLWR_PROMETHEUS_URL") or DEFAULT_PROMETHEUS
    url = f"{base.rstrip('/')}/api/v1/query?{urllib.parse.urlencode({'query': query})}"
    with urllib.request.urlopen(url, timeout=15) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if payload.get("status") != "success":
        return []
    return payload.get("data", {}).get("result") or []


def _load_secrets() -> dict[str, str]:
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
    for key, value in os.environ.items():
        if key.startswith(("RESEND_", "EMAIL_", "ATTORNEY_", "NEBIUS_", "FLWR_")):
            values[key] = value
    return values


def _send_resend_email(*, subject: str, html: str, text: str, to_addr: str) -> str:
    cfg = _load_secrets()
    api_key = cfg.get("RESEND_API_KEY", "")
    from_addr = cfg.get("EMAIL_FROM", "")
    if not (api_key and from_addr and to_addr):
        return "email skipped: resend not configured"
    payload = {
        "from": from_addr,
        "to": [to_addr],
        "subject": subject,
        "html": html,
        "text": text,
    }
    request = urllib.request.Request(
        "https://api.resend.com/emails",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "flower-fleet-desk/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8"))
            return f"email sent id={data.get('id')}"
    except urllib.error.HTTPError as exc:
        return f"email failed HTTP {exc.code}"
    except Exception as exc:  # noqa: BLE001
        return f"email failed {type(exc).__name__}"


def evaluate_alerts(
    *,
    send_email: bool = True,
    apply_actions: bool = True,
    site_values: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Evaluate configured rules against Prometheus (or provided site values)."""
    ensure_default_rules()
    data = load_rules()
    fired: list[dict[str, Any]] = []
    actions_taken: list[dict[str, Any]] = []

    for rule in data.get("rules") or []:
        if not rule.get("enabled", True):
            continue
        rule_id = str(rule.get("id") or "unnamed")
        metric = str(rule.get("metric") or "")
        op = str(rule.get("op") or ">")
        threshold = float(rule.get("threshold"))
        scope = str(rule.get("scope") or "scalar")
        actions = [str(a) for a in (rule.get("actions") or [])]

        if scope == "per_site":
            series: dict[str, float] = {}
            if site_values is not None and metric == "flower_site_train_metric":
                series = dict(site_values)
            else:
                for row in _prom_query(metric):
                    name = (row.get("metric") or {}).get("name")
                    if not name:
                        continue
                    try:
                        series[str(name)] = float(row["value"][1])
                    except (KeyError, TypeError, ValueError, IndexError):
                        continue
            for site, value in sorted(series.items()):
                if not _compare(value, op, threshold):
                    continue
                event = {
                    "rule_id": rule_id,
                    "site": site,
                    "metric": metric,
                    "value": value,
                    "op": op,
                    "threshold": threshold,
                    "description": rule.get("description"),
                }
                fired.append(event)
                if apply_actions:
                    actions_taken.extend(
                        _apply_actions(
                            actions=actions,
                            event=event,
                            send_email=send_email,
                        )
                    )
        else:
            rows = _prom_query(metric)
            if not rows:
                continue
            try:
                value = float(rows[0]["value"][1])
            except (KeyError, TypeError, ValueError, IndexError):
                continue
            if not _compare(value, op, threshold):
                continue
            event = {
                "rule_id": rule_id,
                "site": None,
                "metric": metric,
                "value": value,
                "op": op,
                "threshold": threshold,
                "description": rule.get("description"),
            }
            fired.append(event)
            if apply_actions:
                actions_taken.extend(
                    _apply_actions(
                        actions=actions,
                        event=event,
                        send_email=send_email,
                    )
                )

    control = load_control()
    control["last_evaluation"] = {
        "fired": fired,
        "actions_taken": actions_taken,
    }
    save_control(control)
    return {
        "fired_count": len(fired),
        "fired": fired,
        "actions_taken": actions_taken,
        "control": load_control(),
        "rules_path": str(ALERTS_PATH),
        "control_path": str(CONTROL_PATH),
    }


def _apply_actions(
    *,
    actions: list[str],
    event: dict[str, Any],
    send_email: bool,
) -> list[dict[str, Any]]:
    taken: list[dict[str, Any]] = []
    site = event.get("site")
    for action in actions:
        if action == "exclude_site" and isinstance(site, str):
            set_excluded(
                site,
                excluded=True,
                reason=f"{event['rule_id']}: {event['metric']}={event['value']}",
            )
            taken.append({"action": "exclude_site", "site": site})
        elif action == "pause_training":
            set_pause(
                True,
                reason=f"{event['rule_id']}: {event['metric']}={event['value']}",
            )
            taken.append({"action": "pause_training"})
        elif action == "email" and send_email:
            to_addr = (
                _load_secrets().get("RESEND_TO")
                or _load_secrets().get("ATTORNEY_NOTIFICATION_EMAIL")
                or ""
            )
            subject = (
                f"[Flower Grid Alert] {event['rule_id']}"
                + (f" / {site}" if site else "")
            )
            html = f"""
            <html><body>
              <h2>Flower Grid alert: {_esc(event['rule_id'])}</h2>
              <p>{_esc(event.get('description') or '')}</p>
              <ul>
                <li><b>Metric:</b> {_esc(event['metric'])}</li>
                <li><b>Value:</b> {_esc(event['value'])}</li>
                <li><b>Condition:</b> {_esc(event['op'])} {_esc(event['threshold'])}</li>
                <li><b>Site:</b> {_esc(site or 'fleet')}</li>
              </ul>
              <p>Excluded sites / pause state are in
                 <code>/tmp/flower-agent-audit/grid_control.json</code>.
                 Rules live in <code>~/.flwr/grid_alerts.json</code>.</p>
            </body></html>
            """
            text = (
                f"Alert {event['rule_id']}: {event['metric']}={event['value']} "
                f"{event['op']} {event['threshold']} site={site or 'fleet'}"
            )
            status = _send_resend_email(
                subject=subject, html=html, text=text, to_addr=to_addr
            )
            taken.append({"action": "email", "status": status, "to": to_addr})
    return taken


def _esc(value: object) -> str:
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )

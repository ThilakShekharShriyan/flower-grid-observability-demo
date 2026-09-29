"""Thin shim — canonical grid control lives in the Flower fleet_ops connector.

Prefer importing from:
  flwr.supercore.task_process.connector.fleet_ops.control

This module keeps fleet-desk CLIs (`manage_alerts.py`) working without
duplicating alert / exclude / Twilio / Resend logic.
"""

from __future__ import annotations

from flwr.supercore.task_process.connector.fleet_ops.control import (
    ALERTS_PATH,
    CONTROL_PATH,
    DEFAULT_PROMETHEUS,
    DEFAULT_RULES,
    SECRETS,
    collect_prometheus_snapshot,
    delete_rule,
    ensure_default_rules,
    evaluate_alerts,
    excluded_sites,
    load_control,
    load_rules,
    pause_training,
    place_twilio_call,
    prometheus_url,
    render_prometheus_report_html,
    save_control,
    save_rules,
    send_prometheus_report,
    set_excluded,
    set_pause,
    upsert_rule,
)

__all__ = [
    "ALERTS_PATH",
    "CONTROL_PATH",
    "DEFAULT_PROMETHEUS",
    "DEFAULT_RULES",
    "SECRETS",
    "collect_prometheus_snapshot",
    "delete_rule",
    "ensure_default_rules",
    "evaluate_alerts",
    "excluded_sites",
    "load_control",
    "load_rules",
    "pause_training",
    "place_twilio_call",
    "prometheus_url",
    "render_prometheus_report_html",
    "save_control",
    "save_rules",
    "send_prometheus_report",
    "set_excluded",
    "set_pause",
    "upsert_rule",
]

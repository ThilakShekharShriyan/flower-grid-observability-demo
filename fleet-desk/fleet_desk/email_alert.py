"""Send Grid incident emails via Resend (same API as AlmaProject).

MiniMax drafts an informative subject + HTML body from the live case.
Delivery uses https://api.resend.com/emails with EMAIL_FROM on the verified
domain (leads@thilakshekharshriyan.com).
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path

SECRETS = Path.home() / ".flwr" / "secrets.env"
ALERT_DETAIL = Path("/tmp/flower-agent-audit/last_email_alert.json")
ALERT_HTML = Path("/tmp/flower-agent-audit/last_email_alert.html")
RESEND_EMAILS_URL = "https://api.resend.com/emails"
ISSUE_OUTCOMES = frozenset({"quarantine", "mistrial", "fleet_hold", "node_down"})
NEBIUS_CHAT_URL = "https://api.tokenfactory.tf-ca1.nebius.com/v1/chat/completions"


def load_secrets() -> dict[str, str]:
    """Load Resend + Nebius settings from the process env, then secrets.env."""
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
    for key in (
        "RESEND_API_KEY",
        "EMAIL_FROM",
        "ATTORNEY_NOTIFICATION_EMAIL",
        "RESEND_TO",
        "NEBIUS_MINIMAX_API_KEY",
        "NEBIUS_MINIMAX_MODEL",
        "NEBIUS_KIMI_API_KEY",
        "NEBIUS_KIMI_MODEL",
        "NEBIUS_API_KEY",
        "FLWR_MODEL_API_KEY",
    ):
        if os.environ.get(key):
            values[key] = os.environ[key]
    return values


def should_alert(outcome: str) -> bool:
    return outcome in ISSUE_OUTCOMES


def _case_payload(
    *,
    outcome: str,
    reason: str,
    sentence: str,
    defendant: str | None,
    drift_map: dict[str, float],
    replies: list[dict[str, object]],
    assignee_name: str | None,
    to_address: str | None,
) -> dict[str, object]:
    return {
        "outcome": outcome,
        "reason": reason,
        "sentence": sentence,
        "defendant": defendant,
        "assignee_name": assignee_name,
        "to_address": to_address,
        "drift_map": drift_map,
        "replies": [
            {
                "node": reply.get("node"),
                "role": reply.get("role"),
                "vote": reply.get("vote"),
                "sentence": reply.get("sentence"),
            }
            for reply in replies
        ],
    }


def draft_informative_email(case: dict[str, object], cfg: dict[str, str]) -> tuple[str, str, str]:
    """Use MiniMax chat.completions to draft copy; we assemble safe HTML."""
    api_key = (
        cfg.get("NEBIUS_MINIMAX_API_KEY")
        or cfg.get("NEBIUS_API_KEY")
        or cfg.get("FLWR_MODEL_API_KEY")
        or ""
    )
    model = cfg.get("NEBIUS_MINIMAX_MODEL") or ""
    if not api_key or not model:
        subject, html = _fallback_email(case)
        return subject, html, "template-fallback"

    system = (
        "You are the Flower Grid incident email writer. "
        "Return ONLY valid JSON with keys: "
        "subject (string), headline (string), summary (string), "
        "actions (array of 3-5 short strings), notes (string). "
        "No markdown fences. No HTML tags. Keep each string under 240 chars."
    )
    user = f"""Draft on-call email copy for this Flower federation incident.

Make it concrete using the numbers and site names in the case.
Mention Grafana dashboard uid flower-grid in notes.

Case JSON:
{json.dumps(case, indent=2)}
"""
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0.2,
        "max_tokens": 800,
    }
    request = urllib.request.Request(
        NEBIUS_CHAT_URL,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            payload = json.loads(response.read().decode("utf-8"))
        content = str(payload["choices"][0]["message"]["content"]).strip()
        if content.startswith("```"):
            content = re.sub(r"^```(?:json)?\s*", "", content)
            content = re.sub(r"\s*```$", "", content)
        drafted = json.loads(content)
        subject = str(drafted.get("subject") or "").strip()
        headline = str(drafted.get("headline") or subject).strip()
        summary = str(drafted.get("summary") or case.get("sentence") or "").strip()
        notes = str(drafted.get("notes") or "").strip()
        actions = drafted.get("actions") or []
        if not isinstance(actions, list):
            actions = []
        actions = [str(item).strip() for item in actions if str(item).strip()]
        if not subject or not summary:
            raise ValueError("missing subject/summary")
        html = _render_email_html(
            case=case,
            headline=headline,
            summary=summary,
            actions=actions,
            notes=notes,
        )
        return subject, html, "minimax"
    except Exception:  # noqa: BLE001
        subject, html = _fallback_email(case)
        return subject, html, "template-fallback"


def _esc(value: object) -> str:
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _render_email_html(
    *,
    case: dict[str, object],
    headline: str,
    summary: str,
    actions: list[str],
    notes: str,
) -> str:
    drift_rows = "".join(
        f"<li><code>{_esc(name)}</code>: {_esc(f'{drift:+.3f}')}</li>"
        for name, drift in sorted((case.get("drift_map") or {}).items())
    ) or "<li>n/a</li>"
    vote_rows = "".join(
        (
            "<li>"
            f"[{_esc(reply.get('role'))}] <b>{_esc(reply.get('node'))}</b>: "
            f"{_esc(reply.get('vote'))} — {_esc(reply.get('sentence'))}"
            "</li>"
        )
        for reply in (case.get("replies") or [])
    ) or "<li>n/a</li>"
    action_rows = "".join(f"<li>{_esc(item)}</li>" for item in actions) or (
        "<li>Open Grafana flower-grid and investigate the affected SuperNode.</li>"
    )
    notes_html = f"<p>{_esc(notes)}</p>" if notes else ""
    return f"""
<html><body style="font-family:Helvetica,Arial,sans-serif;line-height:1.45;color:#111">
  <h2>{_esc(headline)}</h2>
  <p><b>Assigned to:</b> {_esc(case.get('assignee_name') or 'fleet on-call')}<br/>
     <b>Outcome:</b> {_esc(case.get('outcome'))}<br/>
     <b>Reason:</b> {_esc(case.get('reason'))}<br/>
     <b>Site:</b> {_esc(case.get('defendant') or 'fleet')}</p>
  <p>{_esc(summary)}</p>
  <h3>Site drift vs federation mean</h3>
  <ul>{drift_rows}</ul>
  <h3>Agent replies</h3>
  <ul>{vote_rows}</ul>
  <h3>Immediate actions</h3>
  <ul>{action_rows}</ul>
  {notes_html}
  <p>— Flower Grid Watch</p>
</body></html>
"""


def _fallback_email(case: dict[str, object]) -> tuple[str, str]:
    subject = (
        f"[Flower Grid] {case.get('outcome')}: "
        f"{case.get('defendant') or 'fleet'} — action needed"
    )
    html = _render_email_html(
        case=case,
        headline="Flower Grid incident",
        summary=str(case.get("sentence") or ""),
        actions=[
            "Check Grafana dashboard flower-grid",
            "Contact the assigned on-call for the affected site",
            "Hold model promotion until the site is cleared",
        ],
        notes="Open Grafana flower-grid for live metrics.",
    )
    return subject, html


def _resend_send(
    *,
    cfg: dict[str, str],
    to_addr: str,
    subject: str,
    html: str,
    text: str | None = None,
) -> tuple[bool, str]:
    """Send via Resend — same pattern as AlmaProject apps/web/lib/mail.ts."""
    api_key = cfg.get("RESEND_API_KEY", "")
    from_addr = cfg.get("EMAIL_FROM") or ""
    if not (api_key and from_addr and to_addr):
        return False, "resend not configured"
    payload: dict[str, object] = {
        "from": from_addr,
        "to": [to_addr],
        "subject": subject,
        "html": html,
    }
    if text:
        payload["text"] = text
    request = urllib.request.Request(
        RESEND_EMAILS_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            # Cloudflare/Resend rejects bare urllib without a UA (error 1010).
            "User-Agent": "flower-fleet-desk/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read().decode("utf-8", errors="replace")
            data = json.loads(raw) if raw else {}
            email_id = data.get("id") or "ok"
            return True, f"resend id={email_id}"
    except urllib.error.HTTPError as exc:
        err = exc.read(300).decode("utf-8", errors="replace")
        return False, f"HTTP {exc.code}: {err[:200]}"
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"


def send_issue_email(
    *,
    outcome: str,
    reason: str,
    sentence: str,
    defendant: str | None,
    drift_map: dict[str, float] | None = None,
    replies: list[dict[str, object]] | None = None,
    to_address: str | None = None,
    assignee_name: str | None = None,
) -> str:
    """Draft informative email with MiniMax, then send via Resend."""
    drift_map = drift_map or {}
    replies = replies or []
    cfg = load_secrets()
    to_addr = (
        to_address
        or cfg.get("RESEND_TO")
        or cfg.get("ATTORNEY_NOTIFICATION_EMAIL")
        or ""
    )
    case = _case_payload(
        outcome=outcome,
        reason=reason,
        sentence=sentence,
        defendant=defendant,
        drift_map=drift_map,
        replies=replies,
        assignee_name=assignee_name,
        to_address=to_addr or None,
    )

    subject, html, draft_source = draft_informative_email(case, cfg)
    plain = (
        f"{outcome} / {reason} / {defendant or 'fleet'}\n\n"
        f"{sentence}\n\n"
        f"Assigned: {assignee_name or 'fleet on-call'}\n"
        f"Open Grafana dashboard flower-grid for live metrics.\n"
    )
    ALERT_DETAIL.parent.mkdir(parents=True, exist_ok=True)
    ALERT_HTML.write_text(html, encoding="utf-8")

    detail = {
        **case,
        "email_subject": subject,
        "email_draft_source": draft_source,
        "email_html_path": str(ALERT_HTML),
        "transport": "resend",
        "note": (
            "Incident HTML drafted by MiniMax; delivered with Resend "
            "(AlmaProject mail.ts pattern)."
        ),
    }
    ALERT_DETAIL.write_text(json.dumps(detail, indent=2) + "\n", encoding="utf-8")

    who = assignee_name or to_addr or "on-call"
    ok, resend_msg = _resend_send(
        cfg=cfg, to_addr=to_addr, subject=subject, html=html, text=plain
    )
    if ok:
        return (
            f"email sent to {who} via Resend ({resend_msg}) with {draft_source} body "
            f"for {outcome}/{defendant or 'fleet'}; draft also at {ALERT_HTML}"
        )
    return (
        f"Resend failed ({resend_msg}); informative {draft_source} draft at {ALERT_HTML}"
    )

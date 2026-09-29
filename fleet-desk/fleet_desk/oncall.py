"""On-call roster: which person owns each SuperNode when it fails."""

from __future__ import annotations

import json
import os
from pathlib import Path

# Default demo roster. Override with FLEET_ONCALL_JSON or ~/.flwr/oncall.json.
DEFAULT_ONCALL: dict[str, dict[str, str]] = {
    "site-a": {
        "name": "Alex (Site A)",
        "email": "thilakshekharshriyan@gmail.com",
    },
    "site-b": {
        "name": "Blake (Site B)",
        "email": "thilakshekharshriyan@gmail.com",
    },
    "site-c": {
        "name": "Casey (Site C)",
        "email": "thilakshekharshriyan@gmail.com",
    },
    "fleet": {
        "name": "Fleet on-call",
        "email": "thilakshekharshriyan@gmail.com",
    },
}

ONCALL_FILE = Path.home() / ".flwr" / "oncall.json"

# SuperNode listen port → site name (matches local TLS demo).
PORT_TO_SITE = {
    9094: "site-a",
    9095: "site-b",
    9096: "site-c",
}
SITE_TO_PORT = {site: port for port, site in PORT_TO_SITE.items()}
SITE_TO_CREDENTIAL = {
    "site-a": 1,
    "site-b": 2,
    "site-c": 3,
}


def load_oncall() -> dict[str, dict[str, str]]:
    roster = {key: dict(value) for key, value in DEFAULT_ONCALL.items()}
    if ONCALL_FILE.exists():
        try:
            loaded = json.loads(ONCALL_FILE.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                for site, person in loaded.items():
                    if isinstance(person, dict) and person.get("email"):
                        roster[str(site)] = {
                            "name": str(person.get("name") or site),
                            "email": str(person["email"]),
                        }
        except json.JSONDecodeError:
            pass
    raw = os.environ.get("FLEET_ONCALL_JSON")
    if raw:
        try:
            loaded = json.loads(raw)
            if isinstance(loaded, dict):
                for site, person in loaded.items():
                    if isinstance(person, dict) and person.get("email"):
                        roster[str(site)] = {
                            "name": str(person.get("name") or site),
                            "email": str(person["email"]),
                        }
        except json.JSONDecodeError:
            pass
    return roster


def assignee_for(site: str | None) -> dict[str, str]:
    roster = load_oncall()
    if site and site in roster:
        return roster[site]
    return roster.get("fleet") or DEFAULT_ONCALL["fleet"]

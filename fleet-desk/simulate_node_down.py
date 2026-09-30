"""Simulate a SuperNode going down and email the assigned on-call person.

Steps:
  1. Confirm the site is online in Prometheus
  2. Stop the local flower-supernode for that site
  3. Wait until Prometheus shows it offline / fleet thin
  4. Email the site's assignee with the issue detail file
  5. Optionally restart the SuperNode (--restart, default on)
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import time
import urllib.parse
import urllib.request
from pathlib import Path

from fleet_desk.email_alert import send_issue_email
from fleet_desk.oncall import (
    SITE_TO_CREDENTIAL,
    SITE_TO_PORT,
    assignee_for,
)

PROMETHEUS = os.environ.get("FLWR_PROMETHEUS_URL", "http://127.0.0.1:9090")
FRAMEWORK = Path(__file__).resolve().parents[1] / "flower" / "framework"
CA = Path("/tmp/flower-tls/certificates/ca.crt")
KEYS = Path("/tmp/flower-tls/keys")


def _prom(query: str) -> list[dict]:
    url = f"{PROMETHEUS}/api/v1/query?{urllib.parse.urlencode({'query': query})}"
    with urllib.request.urlopen(url, timeout=15) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if payload.get("status") != "success":
        return []
    return payload.get("data", {}).get("result") or []


def online_sites() -> set[str]:
    names: set[str] = set()
    for row in _prom('flower_supernode_up{status="online"}'):
        name = row.get("metric", {}).get("name")
        if name:
            names.add(name)
    return names


def pids_for_port(port: int) -> list[int]:
    try:
        out = subprocess.check_output(["lsof", "-ti", f"TCP:{port}"], text=True)
    except subprocess.CalledProcessError:
        return []
    pids: list[int] = []
    for line in out.splitlines():
        line = line.strip()
        if line.isdigit():
            pids.append(int(line))
    return sorted(set(pids))


def stop_site(site: str) -> list[int]:
    port = SITE_TO_PORT[site]
    pids = pids_for_port(port)
    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            continue
    # Brief wait, then force if still listening
    time.sleep(1.5)
    left = pids_for_port(port)
    for pid in left:
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            continue
    return pids


def wait_until_down(site: str, timeout: float = 90.0) -> tuple[bool, set[str]]:
    deadline = time.time() + timeout
    while time.time() < deadline:
        online = online_sites()
        if site not in online:
            return True, online
        time.sleep(2.0)
    return False, online_sites()


def restart_site(site: str) -> subprocess.Popen:
    port = SITE_TO_PORT[site]
    cred = SITE_TO_CREDENTIAL[site]
    key = KEYS / f"supernode_credentials_{cred}"
    cmd = [
        "uv",
        "run",
        "--python",
        "3.11.14",
        "flower-supernode",
        "--root-certificates",
        str(CA),
        "--superlink",
        "127.0.0.1:9092",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--auth-supernode-private-key",
        str(key),
    ]
    return subprocess.Popen(
        cmd,
        cwd=str(FRAMEWORK),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--site",
        default="site-b",
        choices=sorted(SITE_TO_PORT),
        help="SuperNode to take down (default: site-b)",
    )
    parser.add_argument(
        "--no-restart",
        action="store_true",
        help="Leave the SuperNode down after paging",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=20.0,
        help="Seconds to wait for Prometheus offline / online (default: 20)",
    )
    args = parser.parse_args()
    site = args.site

    before = online_sites()
    print(f"Online before: {sorted(before) or 'none'}", flush=True)
    if site not in before:
        raise SystemExit(f"{site} is not online — pick an online site to simulate.")

    person = assignee_for(site)
    print(
        f"Assigned on-call for {site}: {person['name']} <{person['email']}>",
        flush=True,
    )

    killed = stop_site(site)
    print(f"Stopped {site} (killed PIDs {killed or 'none'}).", flush=True)

    down, after = wait_until_down(site, timeout=args.timeout)
    print(f"Online after: {sorted(after) or 'none'}", flush=True)
    if not down:
        raise SystemExit(
            f"Timed out waiting for {site} to leave flower_supernode_up. "
            "Heartbeat window may still be open — increase --timeout."
        )

    sentence = (
        f"{site} dropped offline. Fleet online now: {sorted(after) or 'none'}. "
        f"Assigned owner {person['name']} must investigate before the next "
        "promotion / training window."
    )
    status = send_issue_email(
        outcome="node_down",
        reason="supernode_offline",
        sentence=sentence,
        defendant=site,
        drift_map={},
        replies=[
            {
                "node": site,
                "role": "watchdog",
                "vote": "page",
                "sentence": sentence,
            }
        ],
        to_address=person["email"],
        assignee_name=person["name"],
    )
    print(f"Email agent: {status}", flush=True)

    # Also fire fleet_ops Prometheus rules (email + Twilio call for site_offline /
    # fleet_too_thin) so chat and ServerApp share the same alert path.
    try:
        from flwr.supercore.task_process.connector.fleet_ops import control

        evaluation = control.evaluate_alerts(send_email=True, apply_actions=True)
        print(
            "fleet_ops evaluate:",
            f"fired={evaluation.get('fired_count')} "
            f"actions={len(evaluation.get('actions_taken') or [])}",
            flush=True,
        )
        for action in evaluation.get("actions_taken") or []:
            print(f"  action: {action}", flush=True)
        # Explicit call in case rules didn't fire yet (heartbeat lag)
        call = control.place_twilio_call(
            reason=(
                f"Flower Grid demo. {site} dropped offline. "
                "Please check Prometheus and the Flower dashboard."
            ),
            site=site,
        )
        print(f"Twilio call: {call.get('status')} to={call.get('to')}", flush=True)
    except Exception as exc:  # noqa: BLE001
        print(f"fleet_ops alert path failed: {type(exc).__name__}: {exc}", flush=True)

    if args.no_restart:
        print(f"Left {site} down (--no-restart).", flush=True)
        return

    proc = restart_site(site)
    print(
        f"Restarted {site} as pid {proc.pid}. Waiting for it to reappear…",
        flush=True,
    )
    deadline = time.time() + args.timeout
    restored = False
    while time.time() < deadline:
        if site in online_sites():
            print(f"{site} is online again.", flush=True)
            restored = True
            break
        time.sleep(1.0)
    if not restored:
        print(
            f"{site} restart launched but not online yet — check SuperLink auth/TLS.",
            flush=True,
        )

    # Clear sticky exclude/pause from the alert path so training metrics resume.
    try:
        from flwr.supercore.task_process.connector.fleet_ops import control

        control.set_excluded(site, excluded=False, reason="simulate_node_down restore")
        control.set_pause(False, "simulate_node_down restore")
        print(f"Cleared exclude for {site} and resumed training.", flush=True)
    except Exception as exc:  # noqa: BLE001
        print(f"Could not clear control state: {type(exc).__name__}: {exc}", flush=True)


if __name__ == "__main__":
    main()

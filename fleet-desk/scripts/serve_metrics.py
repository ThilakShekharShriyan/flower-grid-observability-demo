"""Serve Flower audit metrics plus live SuperLink fleet and run readings."""

import json
import time
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from flwr.cli.flower_config import read_superlink_connection
from flwr.cli.utils import init_http_client_from_connection
from flwr.proto.control_pb2 import (  # pylint: disable=E0611
    ListNodesRequest,
    ListRunsRequest,
)

METRICS = Path("/tmp/flower-agent-audit/flower_agent.prom")
TRAINING = Path("/tmp/flower-agent-audit/flower_training.prom")
DECISION = Path("/tmp/flower-agent-audit/flower_decision.prom")
SITE = Path("/tmp/flower-agent-audit/flower_site_training.prom")
KNOWN_SITES = Path("/tmp/flower-agent-audit/known_sites.json")
SUPERLINK = "local-agent"
_RUN_LIMIT = 20


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        audit = METRICS.read_text(encoding="utf-8") if METRICS.exists() else ""
        training = TRAINING.read_text(encoding="utf-8") if TRAINING.exists() else ""
        decision = DECISION.read_text(encoding="utf-8") if DECISION.exists() else ""
        site = SITE.read_text(encoding="utf-8") if SITE.exists() else ""
        body = (
            audit.rstrip()
            + "\n"
            + training.rstrip()
            + "\n"
            + decision.rstrip()
            + "\n"
            + site.rstrip()
            + "\n"
            + _superlink_metrics()
            + "\n"
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; version=0.0.4")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        return


def _superlink_metrics() -> str:
    """Read SuperNode and run state from the local SuperLink."""
    lines = [
        "# HELP flower_supernodes SuperNodes by status.",
        "# TYPE flower_supernodes gauge",
        "# HELP flower_supernodes_online SuperNodes currently connected.",
        "# TYPE flower_supernodes_online gauge",
        "# HELP flower_supernodes_missing_identity Online SuperNodes without a name.",
        "# TYPE flower_supernodes_missing_identity gauge",
        "# HELP flower_supernode_up 1 when a SuperNode is online or registered.",
        "# TYPE flower_supernode_up gauge",
        "# HELP flower_supernode_heartbeat_remaining_seconds "
        "Seconds until SuperLink marks the node offline.",
        "# TYPE flower_supernode_heartbeat_remaining_seconds gauge",
        "# HELP flower_runs Agent runs by status.",
        "# TYPE flower_runs gauge",
        "# HELP flower_run_info 1 for a recent agent run.",
        "# TYPE flower_run_info gauge",
        "# HELP flower_run_bytes_sent Bytes the run has sent.",
        "# TYPE flower_run_bytes_sent gauge",
        "# HELP flower_run_bytes_received Bytes the run has received.",
        "# TYPE flower_run_bytes_received gauge",
    ]
    try:
        client = init_http_client_from_connection(read_superlink_connection(SUPERLINK))
        try:
            nodes = client.ListNodes(ListNodesRequest())
            runs = client.ListRuns(ListRunsRequest(limit=_RUN_LIMIT))
        finally:
            client.close()
    except Exception:  # noqa: BLE001
        lines.append("flower_supernodes_online 0")
        return "\n".join(lines)

    now = time.time()
    _append_nodes(lines, nodes.nodes_info, now)
    _append_runs(lines, runs.run_dict.values())
    return "\n".join(lines)


def _append_nodes(lines: list[str], nodes: object, now: float) -> None:
    counts: Counter[str] = Counter()
    online = 0
    missing_name = 0
    online_names: set[str] = set()
    known = _load_known_sites()
    for node in nodes:
        status = _label(node.status or "unknown")
        counts[status] += 1
        if node.status != "online" and node.status != "registered":
            continue
        name = node.name if node.HasField("name") and node.name else "unspecified"
        location = (
            node.location
            if node.HasField("location") and node.location
            else "unspecified"
        )
        if name != "unspecified":
            known.add(name)
        if node.status == "online":
            online += 1
            if name != "unspecified":
                online_names.add(name)
            if name == "unspecified":
                missing_name += 1
        lines.append(
            "flower_supernode_up"
            f'{{node_id="{node.node_id}",name="{_label(name)}",'
            f'location="{_label(location)}",status="{status}"}} 1'
        )
        if node.status == "online" and node.HasField("online_until"):
            remaining = max(0.0, float(node.online_until) - now)
            lines.append(
                "flower_supernode_heartbeat_remaining_seconds"
                f'{{node_id="{node.node_id}",name="{_label(name)}"}} '
                f"{remaining:.3f}"
            )
    _save_known_sites(known)
    # Stable 0/1 series so Grafana can chart downs/rejoins (not just gaps).
    lines.extend(
        [
            "# HELP flower_site_online 1 when the named SuperNode is online, else 0.",
            "# TYPE flower_site_online gauge",
        ]
    )
    for name in sorted(known):
        value = 1 if name in online_names else 0
        lines.append(f'flower_site_online{{name="{_label(name)}"}} {value}')
    for status, count in sorted(counts.items()):
        lines.append(f'flower_supernodes{{status="{status}"}} {count}')
    lines.append(f"flower_supernodes_online {online}")
    lines.append(f"flower_supernodes_missing_identity {missing_name}")


def _load_known_sites() -> set[str]:
    if not KNOWN_SITES.exists():
        return set()
    try:
        data = json.loads(KNOWN_SITES.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    if isinstance(data, list):
        return {str(item) for item in data}
    return set()


def _save_known_sites(names: set[str]) -> None:
    KNOWN_SITES.parent.mkdir(parents=True, exist_ok=True)
    KNOWN_SITES.write_text(
        json.dumps(sorted(names), indent=2) + "\n", encoding="utf-8"
    )


def _append_runs(lines: list[str], runs: object) -> None:
    counts: Counter[tuple[str, str]] = Counter()
    for run in runs:
        status = _label(run.status.status or "unknown")
        sub_status = _label(run.status.sub_status or "none")
        counts[(status, sub_status)] += 1
        federation = _label(run.federation or "none")
        fab_id = _label(run.fab_id or "unknown")
        labels = (
            f'run_id="{run.run_id}",status="{status}",'
            f'sub_status="{sub_status}",federation="{federation}",fab_id="{fab_id}"'
        )
        lines.append(f"flower_run_info{{{labels}}} 1")
        lines.append(f"flower_run_bytes_sent{{{labels}}} {run.bytes_sent}")
        lines.append(f"flower_run_bytes_received{{{labels}}} {run.bytes_recv}")
    for (status, sub_status), count in sorted(counts.items()):
        lines.append(
            f'flower_runs{{status="{status}",sub_status="{sub_status}"}} {count}'
        )
    if not counts:
        lines.append('flower_runs{status="none",sub_status="none"} 0')


def _label(value: str) -> str:
    return (
        str(value)
        .replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "")
        .replace(" ", "_")
    )


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 9105), Handler).serve_forever()

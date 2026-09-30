"""Repeat quickstart-numpy: 500+ runs, 20s gap, only the 3 SuperNodes."""

import re
import subprocess
import time
from pathlib import Path

OUT = Path("/tmp/flower-agent-audit/flower_training.prom")
APP = Path(
    "/Users/thilakshekharshriyan/Projects/FLoweLABS/Untitled/flower/examples/quickstart-numpy"
)
FRAMEWORK = "/Users/thilakshekharshriyan/Projects/FLoweLABS/Untitled/flower/framework"
SAMPLED_RE = re.compile(r"Sampled (\d+) nodes")
FAILURES_RE = re.compile(r"Received (\d+) results and (\d+) failures")

# Short jobs so many runs accumulate; Prometheus history is per-round points.
ROUNDS_PER_RUN = "5"
# Fixed pause between finished run and the next start (what you see as the gap).
GAP_SECONDS = 20
# Keep going until at least this many successful runs, then continue forever.
TARGET_RUNS = 500
EXPECTED_NODES = 3

runs_completed = 0
run_errors = 0
nodes_sampled = 0
result_failures = 0


def write_metrics() -> None:
    lines = [
        "# HELP flower_training_runs_completed Completed quickstart-numpy FedAvg runs.",
        "# TYPE flower_training_runs_completed counter",
        f"flower_training_runs_completed {runs_completed}",
        "# HELP flower_training_run_errors quickstart-numpy runs that failed.",
        "# TYPE flower_training_run_errors counter",
        f"flower_training_run_errors {run_errors}",
        "# HELP flower_training_nodes_sampled Nodes used in the latest round.",
        "# TYPE flower_training_nodes_sampled gauge",
        f"flower_training_nodes_sampled {nodes_sampled}",
        "# HELP flower_training_result_failures Failed client results in the latest round.",
        "# TYPE flower_training_result_failures gauge",
        f"flower_training_result_failures {result_failures}",
        "# HELP flower_training_gap_seconds Planned pause between training runs.",
        "# TYPE flower_training_gap_seconds gauge",
        f"flower_training_gap_seconds {GAP_SECONDS}",
        "# HELP flower_training_target_runs Desired successful-run count.",
        "# TYPE flower_training_target_runs gauge",
        f"flower_training_target_runs {TARGET_RUNS}",
    ]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def consume(line: str) -> None:
    global nodes_sampled, result_failures
    sampled = SAMPLED_RE.search(line)
    if sampled:
        nodes_sampled = int(sampled.group(1))
        write_metrics()
    failures = FAILURES_RE.search(line)
    if failures:
        result_failures = int(failures.group(2))
        write_metrics()


def one_run() -> None:
    global runs_completed, run_errors
    print(
        f"=== starting run {runs_completed + run_errors + 1} "
        f"(completed={runs_completed}, target={TARGET_RUNS}, "
        f"expect {EXPECTED_NODES} SuperNodes) ===",
        flush=True,
    )
    process = subprocess.Popen(
        [
            "uv",
            "run",
            "--project",
            FRAMEWORK,
            "--python",
            "3.11.14",
            "flwr",
            "run",
            ".",
            "local-agent",
            "--federation",
            "@none/default",
            "--stream",
            "--run-config",
            f"num-server-rounds={ROUNDS_PER_RUN}",
        ],
        cwd=APP,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env={**dict(**__import__("os").environ), "FLWR_DISABLE_UPDATE_CHECK": "1"},
    )
    assert process.stdout is not None
    for line in process.stdout:
        print(line, end="", flush=True)
        consume(line)
    code = process.wait()
    if code == 0 and nodes_sampled == EXPECTED_NODES:
        runs_completed += 1
    else:
        run_errors += 1
        if code == 0 and nodes_sampled != EXPECTED_NODES:
            print(
                f"Rejecting run: sampled {nodes_sampled} nodes, "
                f"want exactly {EXPECTED_NODES}.",
                flush=True,
            )
    write_metrics()


if __name__ == "__main__":
    write_metrics()
    while True:
        control_path = Path("/tmp/flower-agent-audit/grid_control.json")
        if control_path.exists():
            try:
                import json

                control = json.loads(control_path.read_text(encoding="utf-8"))
            except Exception:
                control = {}
            if control.get("pause_training"):
                print(
                    f"=== training paused ({control.get('pause_reason') or 'fleet_ops'}) "
                    f"— sleeping {GAP_SECONDS}s ===",
                    flush=True,
                )
                write_metrics()
                time.sleep(GAP_SECONDS)
                continue
        one_run()
        print(
            f"=== gap {GAP_SECONDS}s before next run "
            f"(completed={runs_completed}/{TARGET_RUNS}) ===",
            flush=True,
        )
        time.sleep(GAP_SECONDS)

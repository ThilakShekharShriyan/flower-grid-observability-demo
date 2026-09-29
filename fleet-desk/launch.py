"""Open one Grid Drift Tribunal on the local SuperLink."""

import hashlib
from pathlib import Path

from flwr.cli.build import build_fab_from_disk
from flwr.cli.flower_config import read_superlink_connection
from flwr.cli.log import start_stream
from flwr.cli.utils import init_http_client_from_connection
from flwr.common.serde import fab_to_proto
from flwr.proto.control_pb2 import StartRunRequest  # pylint: disable=E0611
from flwr.supercore.fab import Fab

APP = Path(__file__).resolve().parent
PROMPT = (
    "Open the Grid Drift Tribunal. Scout Prometheus for per-site train drift, "
    "name the farthest SuperNode as defendant, let that site plead, let the "
    "peer sites jury-vote, and publish the verdict back as Grafana metrics."
)


def main() -> None:
    connection = read_superlink_connection("local-agent")
    client = init_http_client_from_connection(connection)
    try:
        fab_bytes = build_fab_from_disk(APP)
        request = StartRunRequest(
            fab=fab_to_proto(
                Fab(hashlib.sha256(fab_bytes).hexdigest(), fab_bytes, {})
            ),
            federation=connection.federation or "@none/default",
        )
        request.user_prompt = PROMPT
        response = client.StartRun(request)
        if not response.HasField("run_id"):
            raise RuntimeError("SuperLink did not start the drift tribunal.")
        print(f"Started drift tribunal {response.run_id}", flush=True)
        start_stream(response.run_id, client)
    finally:
        client.close()


if __name__ == "__main__":
    main()

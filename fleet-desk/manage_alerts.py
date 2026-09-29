"""CLI helper to set / evaluate Flower Grid alert rules."""

from __future__ import annotations

import argparse
import json

from fleet_desk import grid_control as gc


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="List alert rules and control state")

    up = sub.add_parser("set-rule", help="Create/update a threshold rule")
    up.add_argument("--id", required=True)
    up.add_argument("--metric", required=True)
    up.add_argument("--op", required=True, choices=[">", ">=", "<", "<=", "==", "!="])
    up.add_argument("--threshold", type=float, required=True)
    up.add_argument("--scope", default="per_site", choices=["per_site", "scalar"])
    up.add_argument(
        "--actions",
        default="exclude_site,email",
        help="Comma list: exclude_site,pause_training,email",
    )
    up.add_argument("--description", default="")
    up.add_argument("--disabled", action="store_true")

    ev = sub.add_parser("evaluate", help="Evaluate rules against Prometheus")
    ev.add_argument("--no-email", action="store_true")
    ev.add_argument("--dry-run", action="store_true", help="Do not apply actions")

    ex = sub.add_parser("exclude", help="Manually exclude a site")
    ex.add_argument("site")
    inc = sub.add_parser("include", help="Clear exclude for a site")
    inc.add_argument("site")
    pause = sub.add_parser("pause", help="Pause training loop")
    pause.add_argument("--reason", default="manual pause")
    sub.add_parser("resume", help="Clear pause_training")

    args = parser.parse_args()
    gc.ensure_default_rules()

    if args.cmd == "list":
        print(json.dumps({"rules": gc.load_rules(), "control": gc.load_control()}, indent=2))
        return
    if args.cmd == "set-rule":
        rule = {
            "id": args.id,
            "enabled": not args.disabled,
            "metric": args.metric,
            "op": args.op,
            "threshold": args.threshold,
            "scope": args.scope,
            "actions": [a.strip() for a in args.actions.split(",") if a.strip()],
            "description": args.description
            or f"{args.metric} {args.op} {args.threshold}",
        }
        print(json.dumps(gc.upsert_rule(rule), indent=2))
        return
    if args.cmd == "evaluate":
        result = gc.evaluate_alerts(
            send_email=not args.no_email,
            apply_actions=not args.dry_run,
        )
        print(json.dumps(result, indent=2))
        return
    if args.cmd == "exclude":
        print(json.dumps(gc.set_excluded(args.site, excluded=True, reason="cli"), indent=2))
        return
    if args.cmd == "include":
        print(json.dumps(gc.set_excluded(args.site, excluded=False, reason="cli"), indent=2))
        return
    if args.cmd == "pause":
        print(json.dumps(gc.set_pause(True, args.reason), indent=2))
        return
    if args.cmd == "resume":
        print(json.dumps(gc.set_pause(False, "cli resume"), indent=2))
        return


if __name__ == "__main__":
    main()

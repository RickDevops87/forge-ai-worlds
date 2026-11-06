from __future__ import annotations

import argparse
import json
from pathlib import Path

from .config import WorldConfig
from .engine import WorldRunner


def main() -> None:
    parser = argparse.ArgumentParser(prog="forge-world")
    parser.add_argument("--config", type=Path, required=True, help="world pack TOML manifest")
    sub = parser.add_subparsers(dest="operation", required=True)
    start = sub.add_parser("start")
    start.add_argument("--run-id")
    for operation in ("status", "stop"):
        command = sub.add_parser(operation)
        command.add_argument("run_id")
    args = parser.parse_args()
    runner = WorldRunner(WorldConfig.load(args.config))
    if args.operation == "start":
        result = runner.start(args.run_id)
    elif args.operation == "status":
        result = runner.status(args.run_id)
    else:
        result = runner.stop(args.run_id)
    print(json.dumps(result, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()

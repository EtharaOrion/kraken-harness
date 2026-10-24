"""The shared command line: ``kraken-infer`` and ``kraken-eval``."""

from __future__ import annotations

import argparse
import json
import sys
import tomllib
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from kraken_harness import benchmarks

# A fixed width keeps --help, and the README rendered from it, the same on every terminal.
HELP_WIDTH = 88
RUN_ERRORS = (ValueError, RuntimeError, LookupError, OSError)


def _formatter(prog: str) -> argparse.HelpFormatter:
    return argparse.HelpFormatter(prog, width=HELP_WIDTH)


def _common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--root",
        type=Path,
        default=Path("."),
        help="the parent project root that holds the lane roots and harbor.lock (default: .)",
    )
    parser.add_argument(
        "--benchmark",
        default="kraken",
        help="the benchmark directory to run (default: kraken)",
    )
    parser.add_argument(
        "--work-dir",
        type=Path,
        required=True,
        help="a directory outside --root for workspaces, trial layers and records",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="prepare and validate everything, print the Harbor commands, and run none",
    )


def infer_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="kraken-infer",
        description="Run the agent under test on resident bundles through the pinned Harbor "
        "release with verification off. Each trial directory is a rollout log for kraken-eval.",
        formatter_class=_formatter,
    )
    _common(parser)
    parser.add_argument(
        "--agent-config",
        type=Path,
        required=True,
        help="a JSON or TOML file holding one agent table: the agent under test and its model",
    )
    parser.add_argument(
        "--lane",
        action="append",
        help="a lane to read; repeatable (default: the benchmark's resident lanes)",
    )
    parser.add_argument(
        "--instance",
        action="append",
        help="a bundle uuid to run; repeatable (default: every resident bundle)",
    )
    parser.add_argument(
        "--rollouts",
        type=int,
        help="rollouts per instance (default: the benchmark's rollouts)",
    )
    return parser


def eval_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="kraken-eval",
        description="Score each rollout kraken-infer recorded in --work-dir by regrading its "
        "trial through the pinned Harbor release with the bundle's own tests.",
        formatter_class=_formatter,
    )
    _common(parser)
    return parser


def _work_dir(root: Path, work_dir: Path) -> Path:
    work = work_dir.resolve()
    if work == root or root in work.parents:
        raise ValueError(
            f"--work-dir {work} lies inside --root {root}; choose a directory outside it"
        )
    work.mkdir(parents=True, exist_ok=True)
    return work


def _agent(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    document = json.loads(text) if path.suffix == ".json" else tomllib.loads(text)
    if (
        not isinstance(document, dict)
        or set(document) != {"agent"}
        or not isinstance(document["agent"], dict)
    ):
        raise ValueError(f"{path}: must hold exactly one top-level agent table")
    return document["agent"]


def _report(prog: str, records: list[dict[str, Any]], dry_run: bool) -> int:
    for record in records:
        state = "dry run" if dry_run else f"exit {record['exit_code']}"
        print(
            f"{prog}: {record['bundle_uuid']} r{record['attempt']} [{state}]: {' '.join(record['command'])}"
        )
    print(f"{prog}: {len(records)} trial(s)" + (", none run" if dry_run else ""))
    return 0 if all(record["exit_code"] in (0, None) for record in records) else 1


def infer_main(argv: Sequence[str] | None = None) -> int:
    args = infer_parser().parse_args(argv)
    root = args.root.resolve()
    try:
        records = benchmarks.load(args.benchmark).run_inference(
            root,
            _work_dir(root, args.work_dir),
            _agent(args.agent_config),
            lanes=tuple(args.lane) if args.lane else None,
            only=frozenset(args.instance or ()),
            rollouts=args.rollouts,
            dry_run=args.dry_run,
        )
    except RUN_ERRORS as error:
        print(f"kraken-infer: {error}", file=sys.stderr)
        return 2
    return _report("kraken-infer", records, args.dry_run)


def eval_main(argv: Sequence[str] | None = None) -> int:
    args = eval_parser().parse_args(argv)
    root = args.root.resolve()
    try:
        records = benchmarks.load(args.benchmark).run_evaluation(
            root, _work_dir(root, args.work_dir), dry_run=args.dry_run
        )
    except RUN_ERRORS as error:
        print(f"kraken-eval: {error}", file=sys.stderr)
        return 2
    return _report("kraken-eval", records, args.dry_run)

#!/usr/bin/env python3
"""Collect metadata for the current datalink snapshot in an active trace."""

from __future__ import annotations

import argparse
import json
import logging
import os
from pathlib import Path
import sys

from ThematicAtlases.collector import AtlasCollector


ROOT = Path(__file__).resolve().parent


def require_project_venv(
    root: Path = ROOT,
    executable: str | Path = sys.executable,
) -> None:
    expected = root / ".env" / "bin" / "python"
    if os.path.abspath(executable) != os.path.abspath(expected):
        raise RuntimeError(
            "Run this workflow with the repository virtual environment: "
            ".env/bin/python run_accession_metadata_collector.py TRACE_DIR"
        )


def configure_logging(verbosity: int) -> None:
    level = logging.WARNING
    if verbosity == 1:
        level = logging.INFO
    elif verbosity >= 2:
        level = logging.DEBUG
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.stderr,
        force=True,
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "trace_dir",
        type=Path,
        help="run directory containing 00_run_manifest.json and resume_state.sqlite",
    )
    parser.add_argument("-v", "--verbose", action="count", default=0)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    require_project_venv(root=ROOT, executable=sys.executable)
    configure_logging(args.verbose)
    result = AtlasCollector().resume_metadata(args.trace_dir)
    print(
        json.dumps(
            {
                "trace_dir": str(args.trace_dir),
                "accessions": len(result.get("accessions", [])),
                "progress_artifact": str(
                    args.trace_dir / "resume_metadata_progress.json"
                ),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

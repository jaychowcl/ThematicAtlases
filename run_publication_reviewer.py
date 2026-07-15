#!/usr/bin/env python3
"""Review the current publication snapshot in an actively growing trace."""

from __future__ import annotations

import argparse
import json
import logging
import os
from pathlib import Path
import sys

from ThematicAtlases.credentials import GoogleCredentialPreflight
from ThematicAtlases.filterer import PublicationTextReviewer
from ThematicAtlases.run_archive import workflow_activity_lock


ROOT = Path(__file__).resolve().parent


def require_project_venv(
    root: Path = ROOT,
    executable: str | Path = sys.executable,
) -> None:
    expected = root / ".env" / "bin" / "python"
    if os.path.abspath(executable) != os.path.abspath(expected):
        raise RuntimeError(
            "Run this workflow with the repository virtual environment: "
            ".env/bin/python run_publication_reviewer.py TRACE_DIR"
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
    parser.add_argument(
        "--theme-file",
        type=Path,
        default=None,
        help="optional theme file; otherwise use the theme stored in the manifest",
    )
    parser.add_argument(
        "--strategy",
        choices=("direct", "evidence_then_judgement"),
        default="direct",
        help="review contract to run; direct is the default",
    )
    parser.add_argument(
        "--allow-theme-override",
        action="store_true",
        help=(
            "allow --theme-file to override the historical manifest theme for "
            "this reviewer invocation without changing the collector manifest"
        ),
    )
    parser.add_argument("-v", "--verbose", action="count", default=0)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    require_project_venv(root=ROOT, executable=sys.executable)
    configure_logging(args.verbose)
    theme = (
        args.theme_file.read_text(encoding="utf-8")
        if args.theme_file is not None
        else None
    )
    with workflow_activity_lock(
        args.trace_dir.parent, exclusive=False, blocking=False
    ):
        GoogleCredentialPreflight().check()
        result = PublicationTextReviewer().resume(
            args.trace_dir,
            theme=theme,
            strategy=args.strategy,
            allow_theme_override=args.allow_theme_override,
        )
    print(
        json.dumps(
            {
                "trace_dir": str(args.trace_dir),
                "accessions": len(result.get("accessions", [])),
                "publication_texts": len(result.get("publication_texts", {})),
                "progress_artifact": str(
                    args.trace_dir / "resume_review_progress.json"
                ),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

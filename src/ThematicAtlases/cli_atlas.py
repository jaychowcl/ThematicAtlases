from __future__ import annotations

import argparse
import json
import logging
from typing import Any

from ThematicAtlases.atlas import Atlas


def _emit(command: str, result: Any) -> None:
    payload = {
        "command": command,
        "status": "placeholder",
        "result": result,
    }
    print(json.dumps(payload, separators=(",", ":")))


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="thematic-atlas",
        description="Run placeholder ThematicAtlases atlas commands.",
    )
    parser.add_argument("-v", "--verbose", action="count", default=0)
    parser.add_argument("--log-file", default=None)
    subparsers = parser.add_subparsers(dest="command", required=True)

    collect = subparsers.add_parser(
        "collect-jsons",
        help="Call the placeholder JSON collection workflow.",
    )
    collect.add_argument("--query", action="append", default=None)
    collect.add_argument("--file", default=None)
    collect.add_argument("--out", default=None)

    subparsers.add_parser(
        "filter-jsons",
        help="Call the placeholder JSON filtering workflow.",
    )

    subparsers.add_parser(
        "harmonize-jsons",
        help="Call the placeholder JSON harmonization workflow.",
    )

    return parser


def _configure_logging(verbosity: int, log_file: str | None) -> None:
    level = logging.WARNING

    if verbosity == 1:
        level = logging.INFO
    elif verbosity >= 2:
        level = logging.DEBUG

    logging_kwargs = {
        "level": level,
        "format": "%(levelname)s:%(name)s:%(message)s",
        "force": True,
    }

    if log_file is not None:
        logging_kwargs["filename"] = log_file
        logging_kwargs["encoding"] = "utf-8"

    logging.basicConfig(**logging_kwargs)


def main(argv: list[str] | None = None) -> int:

    parser = _build_parser()
    args = parser.parse_args(argv)
    _configure_logging(verbosity=args.verbose, log_file=args.log_file)

    atlas = Atlas(metadata={})

    if args.command == "collect-jsons":
        result = atlas.collect_jsons(
            query=args.query,
            file=args.file,
            out=args.out,
        )
    elif args.command == "filter-jsons":
        result = atlas.filter_jsons()
    elif args.command == "harmonize-jsons":
        result = atlas.harmonize_jsons()
    else:
        parser.error(f"unknown command: {args.command}")

    _emit(args.command, result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

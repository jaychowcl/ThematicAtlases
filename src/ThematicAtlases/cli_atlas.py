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


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s:%(name)s:%(message)s",
    )

    parser = _build_parser()
    args = parser.parse_args(argv)

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

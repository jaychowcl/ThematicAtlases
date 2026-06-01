from __future__ import annotations

import argparse
import json
import logging
import sys

from ThematicAtlases.atlas import Atlas


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

    create = subparsers.add_parser(
        "create-atlas",
        help="Run the atlas collection and filtering workflow.",
    )
    create.add_argument("--query", action="append", default=None)
    create.add_argument("--file", default=None)
    create.add_argument("--out", default=None)

    filter_parser = subparsers.add_parser(
        "filter-jsons",
        help="Call the placeholder JSON filtering workflow.",
    )
    filter_parser.add_argument("--file", default=None)
    filter_parser.add_argument("--out", default=None)

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
    else:
        logging_kwargs["stream"] = sys.stdout

    logging.basicConfig(**logging_kwargs)


def main(argv: list[str] | None = None) -> int:

    parser = _build_parser()
    args = parser.parse_args(argv)
    _configure_logging(verbosity=args.verbose, log_file=args.log_file)

    atlas = Atlas(metadata={})

    if args.command == "collect-jsons":
        atlas.collect_jsons(
            query=args.query,
            file=args.file,
            out=args.out,
        )
    elif args.command == "create-atlas":
        atlas.create_atlas(
            query=args.query,
            file=args.file,
            out=args.out,
        )
    elif args.command == "filter-jsons":
        result = atlas.filter_jsons(file=args.file)

        if args.out is not None:
            with open(args.out, "w", encoding="utf-8") as handle:
                json.dump(result, handle, indent=2)
    elif args.command == "harmonize-jsons":
        atlas.harmonize_jsons()
    else:
        parser.error(f"unknown command: {args.command}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

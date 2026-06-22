from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from ThematicAtlases.atlas import Atlas

REVIEW_FILTER_CHOICES = ("none", "not-relevant", "not-relevant-and-unsure")
METADATA_REPOSITORY_CHOICES = ("geo", "arrayexpress")


def _positive_int(value: str) -> int:
    integer = int(value)

    if integer < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")

    return integer


def _add_logging_options(
    parser: argparse.ArgumentParser,
    *,
    verbose_dest: str,
    log_file_dest: str,
) -> None:
    parser.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=None,
        dest=verbose_dest,
    )
    parser.add_argument(
        "--log-file",
        default=None,
        dest=log_file_dest,
        metavar="LOG_FILE",
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="thematic-atlas",
        description="Run placeholder ThematicAtlases atlas commands.",
    )
    _add_logging_options(
        parser,
        verbose_dest="global_verbose",
        log_file_dest="global_log_file",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    collect = subparsers.add_parser(
        "collect-datasets",
        help="Collect and filter datasets into an atlas object.",
    )
    _add_logging_options(
        collect,
        verbose_dest="command_verbose",
        log_file_dest="command_log_file",
    )
    collect.add_argument("--query", action="append", default=None)
    collect.add_argument("--file", default=None)
    collect.add_argument("--out", default=None)
    collect.add_argument("--max-publications", type=_positive_int, default=None)
    collect.add_argument("--skip-metadata", action="store_true", default=False)
    collect.add_argument(
        "--metadata-repository",
        action="append",
        choices=METADATA_REPOSITORY_CHOICES,
        default=None,
    )
    collect.add_argument("--theme", default=None)
    collect.add_argument("--theme-file", default=None)
    collect.add_argument(
        "--review-filter",
        choices=REVIEW_FILTER_CHOICES,
        default="none",
    )

    create = subparsers.add_parser(
        "create-atlas",
        help="Run the atlas collection and filtering workflow.",
    )
    _add_logging_options(
        create,
        verbose_dest="command_verbose",
        log_file_dest="command_log_file",
    )
    create.add_argument("--query", action="append", default=None)
    create.add_argument("--file", default=None)
    create.add_argument("--out", default=None)
    create.add_argument("--max-publications", type=_positive_int, default=None)
    create.add_argument("--skip-metadata", action="store_true", default=False)
    create.add_argument(
        "--metadata-repository",
        action="append",
        choices=METADATA_REPOSITORY_CHOICES,
        default=None,
    )
    create.add_argument("--theme", default=None)
    create.add_argument("--theme-file", default=None)
    create.add_argument(
        "--review-filter",
        choices=REVIEW_FILTER_CHOICES,
        default="none",
    )

    harmonize = subparsers.add_parser(
        "harmonize-datasets",
        help="Call the placeholder dataset harmonization workflow.",
    )
    _add_logging_options(
        harmonize,
        verbose_dest="command_verbose",
        log_file_dest="command_log_file",
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


def _input_value(value: str | None, file: str | None) -> str | None:
    if file is not None:
        return Path(file).read_text(encoding="utf-8")

    return value


def _review_filter(value: str) -> str:
    return value.replace("-", "_")


def _resolved_logging_options(args: argparse.Namespace) -> tuple[int, str | None]:
    command_verbose = getattr(args, "command_verbose", None)
    global_verbose = getattr(args, "global_verbose", None)
    command_log_file = getattr(args, "command_log_file", None)
    global_log_file = getattr(args, "global_log_file", None)

    verbosity = command_verbose if command_verbose is not None else global_verbose
    log_file = command_log_file if command_log_file is not None else global_log_file

    return verbosity or 0, log_file


def main(argv: list[str] | None = None) -> int:

    parser = _build_parser()
    args = parser.parse_args(argv)
    verbosity, log_file = _resolved_logging_options(args)
    _configure_logging(verbosity=verbosity, log_file=log_file)

    atlas = Atlas(metadata={})

    if args.command == "collect-datasets":
        atlas.collect_datasets(
            query=args.query,
            file=args.file,
            out=args.out,
            theme=_input_value(value=args.theme, file=args.theme_file),
            review_filter=_review_filter(args.review_filter),
            metadata_repositories=args.metadata_repository,
            max_publications=args.max_publications,
            collect_metadata=not args.skip_metadata,
        )
    elif args.command == "create-atlas":
        atlas.create_atlas(
            query=args.query,
            file=args.file,
            out=args.out,
            theme=_input_value(value=args.theme, file=args.theme_file),
            review_filter=_review_filter(args.review_filter),
            metadata_repositories=args.metadata_repository,
            max_publications=args.max_publications,
            collect_metadata=not args.skip_metadata,
        )
    elif args.command == "harmonize-datasets":
        atlas.harmonize_datasets(datasets={"accessions": [], "publication_texts": {}})
    else:
        parser.error(f"unknown command: {args.command}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

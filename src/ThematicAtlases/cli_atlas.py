"""Backward-compatible installed entrypoint for the Atlas CLI."""
from __future__ import annotations
from ThematicAtlases.atlas import Atlas
from ThematicAtlases.stage_worker import TraceStageWorker
from ThematicAtlases.cli import atlas as _implementation


def main(argv: list[str] | None = None) -> int:
    return _implementation.main(argv, atlas_factory=Atlas, worker_factory=TraceStageWorker)


def __getattr__(name):
    return getattr(_implementation, name)


if __name__ == '__main__':
    raise SystemExit(main())

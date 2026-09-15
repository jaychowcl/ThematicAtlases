"""Read consistent checkpoint snapshots without initializing or mutating a run."""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import sqlite3


@dataclass(frozen=True)
class CheckpointSnapshot:
    metadata: dict[str, str]
    items: tuple[dict, ...]


def read_checkpoint_snapshot(directory: str | Path, *, stages: tuple[str, ...]) -> CheckpointSnapshot:
    database = Path(directory) / 'atlas_run.sqlite3'
    if not database.is_file():
        raise FileNotFoundError(f'trace does not contain atlas_run.sqlite3: {directory}')
    connection = sqlite3.connect(f'{database.resolve().as_uri()}?mode=ro', uri=True, timeout=30)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute('PRAGMA query_only=ON')
        connection.execute('BEGIN')
        tables = {row['name'] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for required in ('checkpoint_meta', 'checkpoint_items'):
            if required not in tables:
                raise ValueError(f'trace database is missing required table: {required}')
        metadata = {row['key']: row['value'] for row in connection.execute('SELECT key, value FROM checkpoint_meta')}
        if stages:
            placeholders = ','.join('?' for _ in stages)
            items = tuple(dict(row) for row in connection.execute(
                'SELECT stage, item_key, ordinal, status, payload, error FROM checkpoint_items '
                f'WHERE stage IN ({placeholders}) ORDER BY ordinal, item_key', stages,
            ))
        else:
            items = ()
        return CheckpointSnapshot(metadata, items)
    finally:
        connection.rollback()
        connection.close()

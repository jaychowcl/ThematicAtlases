from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import threading
import uuid


_WORKFLOW_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_LOCKS: dict[Path, "_WorkflowLock"] = {}
_LOCKS_GUARD = threading.RLock()


class _WorkflowLock:
    def __init__(self, path: Path, handle, *, exclusive: bool):
        self.path = path
        self.handle = handle
        self.exclusive = exclusive
        self.depth = 1

    def downgrade(self) -> None:
        if self.exclusive:
            fcntl.flock(self.handle.fileno(), fcntl.LOCK_SH)
            self.exclusive = False


@contextmanager
def workflow_activity_lock(
    dev_out_dir: str | Path,
    *,
    exclusive: bool,
    blocking: bool = False,
):
    """Hold the workflow lock, allowing concurrent workers but excluding archives."""
    root = Path(dev_out_dir)
    root.mkdir(parents=True, exist_ok=True)
    lock_path = (root / ".workflow_activity.lock").resolve()

    with _LOCKS_GUARD:
        existing = _LOCKS.get(lock_path)
        if existing is not None:
            if exclusive and not existing.exclusive:
                raise RuntimeError(f"workflow is active: {root}")
            existing.depth += 1
            nested = True
            held = existing
        else:
            nested = False
            handle = open(lock_path, "a+b")
            operation = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
            if not blocking:
                operation |= fcntl.LOCK_NB
            try:
                fcntl.flock(handle.fileno(), operation)
            except BlockingIOError as error:
                handle.close()
                raise RuntimeError(f"workflow is active: {root}") from error
            held = _WorkflowLock(lock_path, handle, exclusive=exclusive)
            _LOCKS[lock_path] = held

    try:
        yield held
    finally:
        with _LOCKS_GUARD:
            held.depth -= 1
            if held.depth == 0:
                _LOCKS.pop(lock_path, None)
                fcntl.flock(held.handle.fileno(), fcntl.LOCK_UN)
                held.handle.close()
            elif nested:
                # The outer owner controls mode changes and final release.
                pass


def archive_existing_runs(
    *,
    dev_out_dir: str | Path,
    archive_root: str | Path,
    workflow: str,
    artifact_paths: list[str | Path] | tuple[str | Path, ...] = (),
) -> list[Path]:
    """Move all inactive workflow traces and fixed artifacts into verified archives."""
    normalized_workflow = str(workflow).strip()
    if not _WORKFLOW_PATTERN.fullmatch(normalized_workflow):
        raise ValueError("workflow must be a filesystem-safe non-empty identifier")

    active_root = Path(dev_out_dir)
    destination_root = Path(archive_root) / normalized_workflow
    if _is_relative_to(destination_root.resolve(), active_root.resolve()):
        raise ValueError("archive_root must not be inside dev_out_dir")

    with workflow_activity_lock(active_root, exclusive=True, blocking=False):
        traces = sorted(
            path
            for path in active_root.iterdir()
            if path.is_dir() and (path / "00_run_manifest.json").is_file()
        )
        artifacts = _existing_artifacts(artifact_paths)
        if not traces and not artifacts:
            return []

        run_ids = [path.name for path in traces]
        if not traces:
            run_ids = [_orphan_run_id(destination_root)]
        destinations = [destination_root / run_id for run_id in run_ids]
        collisions = [path for path in destinations if path.exists()]
        if collisions:
            raise FileExistsError(
                f"archive destination already exists: {collisions[0]}"
            )

        destination_root.mkdir(parents=True, exist_ok=True)
        archived = []
        newest_index = len(destinations) - 1
        for index, destination in enumerate(destinations):
            source = traces[index] if traces else None
            assigned_artifacts = artifacts if index == newest_index else []
            _archive_one(
                source=source,
                destination=destination,
                workflow=normalized_workflow,
                artifacts=assigned_artifacts,
            )
            archived.append(destination)
        return archived


def _archive_one(
    *,
    source: Path | None,
    destination: Path,
    workflow: str,
    artifacts: list[Path],
) -> None:
    if source is not None:
        _prepare_checkpoint_database(source / "resume_state.sqlite")
        _reject_symlinks(source)

    staging = destination.with_name(f".{destination.name}.tmp-{uuid.uuid4().hex}")
    try:
        if source is None:
            staging.mkdir(parents=True)
        else:
            shutil.copytree(source, staging)
            _verify_tree(source, staging)

        artifact_records = []
        if artifacts:
            artifact_directory = staging / "artifacts"
            artifact_directory.mkdir()
            for artifact in artifacts:
                copied = artifact_directory / artifact.name
                shutil.copy2(artifact, copied)
                source_hash = _sha256(artifact)
                if source_hash != _sha256(copied):
                    raise OSError(f"archive checksum mismatch: {artifact}")
                artifact_records.append(
                    {
                        "source": str(artifact),
                        "path": str(Path("artifacts") / artifact.name),
                        "bytes": artifact.stat().st_size,
                        "sha256": source_hash,
                    }
                )

        if source is not None:
            _relocate_manifest_outputs(
                staging / "00_run_manifest.json",
                destination=destination,
                artifacts=artifacts,
            )
        archive_manifest = {
            "archive_version": 1,
            "archived_at": datetime.now(timezone.utc).isoformat(),
            "workflow": workflow,
            "run_id": destination.name,
            "source_trace": None if source is None else str(source),
            "resumable": source is not None,
            "artifacts": artifact_records,
        }
        _write_json(staging / "archive_manifest.json", archive_manifest)
        os.replace(staging, destination)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise

    if source is not None:
        shutil.rmtree(source)
    for artifact in artifacts:
        artifact.unlink()


def _existing_artifacts(paths: list[str | Path] | tuple[str | Path, ...]) -> list[Path]:
    artifacts = []
    names = set()
    for value in paths:
        path = Path(value)
        if not path.exists():
            continue
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"archive artifact must be a regular file: {path}")
        if path.name in names:
            raise ValueError(f"archive artifact basenames must be unique: {path.name}")
        names.add(path.name)
        artifacts.append(path)
    return artifacts


def _prepare_checkpoint_database(path: Path) -> None:
    if not path.exists():
        return
    with sqlite3.connect(path, timeout=30) as connection:
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        result = connection.execute("PRAGMA quick_check").fetchone()
    if result is None or result[0] != "ok":
        raise sqlite3.DatabaseError(f"checkpoint database failed quick_check: {path}")


def _verify_tree(source: Path, copied: Path) -> None:
    source_files = {
        path.relative_to(source): (path.stat().st_size, _sha256(path))
        for path in source.rglob("*")
        if path.is_file() and not path.is_symlink()
    }
    copied_files = {
        path.relative_to(copied): (path.stat().st_size, _sha256(path))
        for path in copied.rglob("*")
        if path.is_file() and not path.is_symlink()
    }
    if source_files != copied_files:
        raise OSError(f"archive trace verification failed: {source}")


def _reject_symlinks(root: Path) -> None:
    symlink = next((path for path in root.rglob("*") if path.is_symlink()), None)
    if symlink is not None:
        raise ValueError(f"archive trace must not contain symlinks: {symlink}")


def _relocate_manifest_outputs(
    path: Path,
    *,
    destination: Path,
    artifacts: list[Path],
) -> None:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    relocated = {str(artifact.resolve()): destination / "artifacts" / artifact.name for artifact in artifacts}
    for key in ("atlas_out", "harmonization_details_out"):
        value = manifest.get(key)
        if not value:
            continue
        replacement = relocated.get(str(Path(value).resolve()))
        if replacement is not None:
            manifest[key] = str(replacement)
    _write_json(path, manifest)


def _write_json(path: Path, value: dict) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    with open(temporary, "w", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _orphan_run_id(destination_root: Path) -> str:
    base = datetime.now(timezone.utc).strftime("orphan-%Y%m%dT%H%M%S")
    candidate = base
    suffix = 1
    while (destination_root / candidate).exists():
        suffix += 1
        candidate = f"{base}-{suffix}"
    return candidate


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True

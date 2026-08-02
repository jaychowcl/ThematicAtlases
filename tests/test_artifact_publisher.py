import json
import os

import pytest

from ThematicAtlases.artifact_publisher import (
    ArtifactRollbackError,
    JsonArtifactBundlePublisher,
)


def test_json_bundle_publisher_stages_validates_and_publishes_all_outputs(tmp_path):
    atlas = tmp_path / "nested" / "atlas.json"
    summary = tmp_path / "nested" / "atlas.summary.json"

    JsonArtifactBundlePublisher().publish(
        {atlas: {"schema_version": "1.0"}, summary: {"dataset_count": 1}}
    )

    assert json.loads(atlas.read_text()) == {"schema_version": "1.0"}
    assert json.loads(summary.read_text()) == {"dataset_count": 1}
    assert atlas.read_text().endswith("\n")
    assert not list((tmp_path / "nested").glob(".*.stage"))
    assert not list((tmp_path / "nested").glob(".*.backup"))


def test_json_bundle_publisher_restores_complete_prior_bundle_on_commit_failure(
    tmp_path,
):
    atlas = tmp_path / "atlas.json"
    summary = tmp_path / "atlas.summary.json"
    atlas.write_text('{"old": "atlas"}\n')
    summary.write_text('{"old": "summary"}\n')
    real_replace = os.replace

    def failing_replace(source, destination):
        if str(source).endswith(".stage") and os.fspath(destination) == os.fspath(summary):
            raise OSError("injected second publication failure")
        real_replace(source, destination)

    publisher = JsonArtifactBundlePublisher(replace=failing_replace)

    with pytest.raises(OSError, match="injected second publication failure"):
        publisher.publish({atlas: {"new": "atlas"}, summary: {"new": "summary"}})

    assert json.loads(atlas.read_text()) == {"old": "atlas"}
    assert json.loads(summary.read_text()) == {"old": "summary"}
    assert sorted(path.name for path in tmp_path.iterdir()) == [
        "atlas.json",
        "atlas.summary.json",
    ]


def test_json_bundle_publisher_leaves_no_first_run_artifacts_on_failure(tmp_path):
    atlas = tmp_path / "atlas.json"
    summary = tmp_path / "atlas.summary.json"
    real_replace = os.replace

    def failing_replace(source, destination):
        if str(source).endswith(".stage") and os.fspath(destination) == os.fspath(summary):
            raise OSError("injected failure")
        real_replace(source, destination)

    with pytest.raises(OSError, match="injected failure"):
        JsonArtifactBundlePublisher(replace=failing_replace).publish(
            {atlas: {"new": "atlas"}, summary: {"new": "summary"}}
        )

    assert not atlas.exists()
    assert not summary.exists()
    assert list(tmp_path.iterdir()) == []


def test_json_bundle_publisher_preserves_backup_when_rollback_itself_fails(
    tmp_path,
):
    atlas = tmp_path / "atlas.json"
    summary = tmp_path / "atlas.summary.json"
    atlas.write_text('{"old": "atlas"}\n')
    summary.write_text('{"old": "summary"}\n')
    real_replace = os.replace

    def doubly_failing_replace(source, destination):
        if str(source).endswith(".stage") and os.fspath(destination) == os.fspath(
            summary
        ):
            raise OSError("publication failed")
        if str(source).endswith(".backup") and os.fspath(destination) == os.fspath(
            atlas
        ):
            raise OSError("rollback failed")
        real_replace(source, destination)

    with pytest.raises(ArtifactRollbackError, match="rollback failed") as exc_info:
        JsonArtifactBundlePublisher(replace=doubly_failing_replace).publish(
            {atlas: {"new": "atlas"}, summary: {"new": "summary"}}
        )

    assert isinstance(exc_info.value.publication_error, OSError)
    assert exc_info.value.recovery_paths
    recovery_path = exc_info.value.recovery_paths[0]
    assert recovery_path.exists()
    assert json.loads(recovery_path.read_text()) == {"old": "atlas"}
    assert json.loads(summary.read_text()) == {"old": "summary"}

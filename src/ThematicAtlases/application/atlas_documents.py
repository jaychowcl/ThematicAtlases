"""Application service for the public Atlas v2 document boundary."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ThematicAtlases.artifact_publisher import JsonArtifactBundlePublisher
from ThematicAtlases.document_adapter import AtlasDocumentAdapter
from ThematicAtlases.domain import AtlasDocument, RunStatus
from ThematicAtlases.ports import ArtifactPublisherPort
from ThematicAtlases.summary import summary_path


class AtlasDocumentService:
    """Assemble, project, summarize, and publish Atlas v2 documents."""

    def __init__(
        self,
        *,
        adapter: AtlasDocumentAdapter | None = None,
        publisher: ArtifactPublisherPort | None = None,
    ) -> None:
        self._adapter = adapter or AtlasDocumentAdapter()
        self._publisher = publisher or JsonArtifactBundlePublisher()

    def assemble(
        self,
        stage_result: Mapping[str, Any],
        *,
        atlas_metadata: Mapping[str, Any],
        run_id: str,
        created_at: str,
        theme: str,
        config: Mapping[str, Any],
        run_status: RunStatus,
        harmonization_details: list[Mapping[str, Any]] | None = None,
    ) -> AtlasDocument:
        return self._adapter.assemble(
            stage_result,
            atlas_metadata=atlas_metadata,
            run_id=run_id,
            created_at=created_at,
            theme=theme,
            config=config,
            run_status=run_status,
            harmonization_details=harmonization_details,
        )

    def to_legacy(self, document: AtlasDocument) -> dict[str, Any]:
        return self._adapter.to_legacy(document)

    @staticmethod
    def summary(document: AtlasDocument, atlas_path: str | Path | None) -> dict:
        return {
            "schema_version": document.schema_version,
            "atlas_id": document.atlas.atlas_id,
            "run_id": document.run.run_id,
            "atlas_path": None if atlas_path is None else str(atlas_path),
            "dataset_count": document.summary.dataset_count,
            "publication_count": document.summary.publication_count,
            "completed_dataset_count": document.summary.completed_dataset_count,
            "failed_dataset_count": document.summary.failed_dataset_count,
        }

    def publish(
        self,
        document: AtlasDocument,
        out: str | Path,
        *,
        include_summary: bool,
    ) -> dict:
        destination = Path(out)
        summary = self.summary(document, destination)
        artifacts: dict[Path, Any] = {destination: document.to_mapping()}
        if include_summary:
            artifacts[summary_path(destination)] = summary
        self._publisher.publish(artifacts)
        return summary


__all__ = ["AtlasDocumentService"]

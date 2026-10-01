"""Assemble the canonical Atlas v1 document at the application boundary."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from ThematicAtlases.domain import (
    AtlasConfig,
    AtlasDocument,
    AtlasIdentity,
    AtlasRun,
    AtlasSummary,
    Dataset,
    DatasetStatus,
    Diagnostic,
    DiagnosticSeverity,
    HarmonizationResult,
    HarmonizationTarget,
    Judgement,
    OntologyMatch,
    Publication,
    PublicationReview,
    ReviewCriterion,
    RunStatus,
)
from ThematicAtlases.miniml_boundary import canonicalize_atlas_metadata
from meta_standards_converter.runtime_contracts import (
    ExecutionStatus,
    OperationStatusV2,
)


class AtlasDocumentAdapter:
    """Translate mature stage mappings into one validated public document."""

    def assemble(
        self,
        legacy: Mapping[str, Any],
        *,
        atlas_metadata: Mapping[str, Any],
        run_id: str,
        created_at: str,
        theme: str,
        config: Mapping[str, Any],
        run_status: RunStatus,
        harmonization_details: list[Mapping[str, Any]] | None = None,
    ) -> AtlasDocument:
        records = legacy.get("accessions", [])
        if not isinstance(records, list):
            raise ValueError("legacy accessions must be a list")
        text_map = legacy.get("publication_texts", {})
        if not isinstance(text_map, Mapping):
            raise ValueError("legacy publication_texts must be an object")

        publications, publication_by_reference = self._publications(records, text_map)
        detail_by_dataset = {
            str(item.get("datalink_id")): item
            for item in harmonization_details or []
            if isinstance(item, Mapping) and item.get("datalink_id")
        }
        datasets = tuple(
            self._dataset(
                record,
                ordinal,
                publication_by_reference,
                detail_by_dataset.get(str(record.get("datalink_id"))),
            )
            for ordinal, record in enumerate(records)
            if isinstance(record, Mapping)
        )
        options = {
            str(key): deepcopy(value)
            for key, value in config.items()
            if key not in {"queries", "metadata_repositories"}
        }
        atlas_id = str(
            atlas_metadata.get("atlas_id") or f"atlas-{run_id}"
        ).strip()
        title = str(
            atlas_metadata.get("title") or theme or "Thematic atlas"
        ).strip()
        queries = tuple(str(item).strip() for item in config.get("queries") or ())
        resolved_theme = str(
            theme
            or atlas_metadata.get("theme")
            or next((item for item in queries if item), "")
            or title
        ).strip()
        document = AtlasDocument(
            atlas=AtlasIdentity(
                atlas_id=atlas_id,
                title=title,
                theme=resolved_theme,
            ),
            run=AtlasRun(
                run_id=run_id,
                created_at=created_at,
                config=AtlasConfig(
                    queries=queries,
                    metadata_repositories=tuple(
                        config.get("metadata_repositories") or ()
                    ),
                    options=options,
                ),
                status=run_status,
            ),
            datasets=datasets,
            publications=publications,
            summary=AtlasSummary(
                dataset_count=len(datasets),
                publication_count=len(publications),
                completed_dataset_count=sum(
                    item.status == DatasetStatus.HARMONIZED for item in datasets
                ),
                failed_dataset_count=sum(
                    item.status == DatasetStatus.FAILED for item in datasets
                ),
            ),
        )
        document.validate()
        return document

    def to_legacy(self, document: AtlasDocument) -> dict[str, Any]:
        """Project v1 into the minimal internal shape used by harmonization."""
        document.validate()
        publications = {
            item.publication_id: item for item in document.publications
        }
        records = []
        for dataset in document.datasets:
            metadata = deepcopy(dict(dataset.metadata))
            if set(metadata) == {"packages"} and isinstance(
                metadata["packages"], list
            ):
                metadata = deepcopy(metadata["packages"])
            record: dict[str, Any] = {
                "datalink_id": dataset.dataset_id,
                "metadata_repository": dataset.source_repository,
                "metadata_status": (
                    "error"
                    if dataset.status == DatasetStatus.FAILED
                    else "available" if metadata else "unavailable"
                ),
                "accession_metadata": metadata or None,
                "publications": [
                    self._legacy_publication(publications[publication_id])
                    for publication_id in dataset.publication_ids
                ],
            }
            if dataset.harmonization is None:
                record["ontology_harmonization_run_status"] = "not_run"
            else:
                operation_status = dataset.harmonization.status
                record["ontology_harmonization_status"] = operation_status.to_dict()
                record["ontology_harmonization_run_status"] = (
                    "completed"
                    if operation_status.execution in {
                        ExecutionStatus.SUCCEEDED,
                        ExecutionStatus.DEGRADED,
                    }
                    else "error"
                    if operation_status.execution is ExecutionStatus.FAILED
                    else "not_run"
                )
                if operation_status.errors:
                    record["ontology_harmonization_error"] = (
                        operation_status.errors[0].to_dict()
                    )
            records.append(record)

        publication_texts = {
            item.publication_id: self._legacy_publication_text(item)
            for item in document.publications
        }
        return {"accessions": records, "publication_texts": publication_texts}

    def _dataset(
        self,
        record: Mapping[str, Any],
        ordinal: int,
        publication_by_reference: Mapping[str, str],
        details: Mapping[str, Any] | None,
    ) -> Dataset:
        dataset_id = str(record.get("datalink_id") or "").strip()
        if not dataset_id:
            raise ValueError("dataset record has no datalink_id")
        repository = str(
            record.get("metadata_repository")
            or record.get("datalink_id_scheme")
            or "unknown"
        ).lower()
        raw_metadata = record.get("accession_metadata")
        if isinstance(raw_metadata, Mapping):
            metadata: Mapping[str, Any] = canonicalize_atlas_metadata(raw_metadata)
        elif isinstance(raw_metadata, list) and all(
            isinstance(item, Mapping) for item in raw_metadata
        ):
            metadata = canonicalize_atlas_metadata({"packages": raw_metadata})
        else:
            metadata = {}

        publication_ids = []
        for publication in record.get("publications", []):
            if not isinstance(publication, Mapping):
                continue
            reference = self._publication_reference(publication)
            publication_id = publication_by_reference.get(reference)
            if publication_id and publication_id not in publication_ids:
                publication_ids.append(publication_id)

        operation_status = self._operation_status(record, details)
        status = self._dataset_status(
            record,
            metadata,
            publication_ids,
            operation_status,
        )
        diagnostics = self._diagnostics(record, operation_status)
        harmonization = self._harmonization(details, operation_status)
        return Dataset(
            dataset_id=dataset_id,
            source_repository=repository,
            source_ordinal=ordinal,
            status=status,
            metadata=metadata,
            publication_ids=tuple(publication_ids),
            harmonization=harmonization,
            diagnostics=diagnostics,
        )

    @staticmethod
    def _dataset_status(
        record: Mapping[str, Any],
        metadata: Mapping[str, Any],
        publication_ids: list[str],
        operation_status: OperationStatusV2 | None,
    ) -> DatasetStatus:
        metadata_status = str(record.get("metadata_status") or "").lower()
        if operation_status and operation_status.execution in {
            ExecutionStatus.SUCCEEDED,
            ExecutionStatus.DEGRADED,
        }:
            return DatasetStatus.HARMONIZED
        if (
            operation_status
            and operation_status.execution is ExecutionStatus.FAILED
        ) or metadata_status in {"error", "failed"}:
            return DatasetStatus.FAILED
        if metadata:
            return DatasetStatus.COLLECTED
        if publication_ids:
            return DatasetStatus.REVIEWED
        return DatasetStatus.DISCOVERED

    @staticmethod
    def _diagnostics(
        record: Mapping[str, Any],
        operation_status: OperationStatusV2 | None,
    ) -> tuple[Diagnostic, ...]:
        diagnostics = []
        for error in operation_status.errors if operation_status else ():
            location = f" at {error.stage}" if error.stage else ""
            item = f" (item {error.item_id})" if error.item_id else ""
            diagnostics.append(
                Diagnostic(
                    code="harmonization_failed",
                    message=(
                        f"harmonization failed: {error.error_type}{location}{item}"
                    ),
                )
            )
        metadata_status = str(record.get("metadata_status") or "").lower()
        if metadata_status in {"error", "failed", "unsupported"}:
            diagnostics.append(
                Diagnostic(
                    code="metadata_collection_status",
                    message=f"metadata status {metadata_status}",
                )
            )
        if metadata_status == "partial":
            repair = record.get("metadata_repair_summary")
            attempts = repair.get("attempt_count") if isinstance(repair, Mapping) else None
            failures = repair.get("failed_count") if isinstance(repair, Mapping) else None
            if (
                isinstance(attempts, int)
                and not isinstance(attempts, bool)
                and attempts >= 0
                and isinstance(failures, int)
                and not isinstance(failures, bool)
                and 0 <= failures <= attempts
            ):
                message = (
                    "metadata enrichment repair completed partially: "
                    f"{failures} of {attempts} attempts failed"
                )
            else:
                message = "metadata enrichment repair completed partially"
            conversion_partial = isinstance(record.get("metadata_conversion"), Mapping)
            diagnostics.append(
                Diagnostic(
                    code="metadata_conversion_partial" if conversion_partial else "metadata_repair_partial",
                    message="metadata conversion is partial; retaining valid metadata" if conversion_partial else message,
                    severity=DiagnosticSeverity.WARNING,
                )
            )
        if (
            operation_status
            and operation_status.execution is ExecutionStatus.DEGRADED
        ):
            diagnostics.append(
                Diagnostic(
                    code="harmonization_degraded",
                    message=(
                        "harmonization completed with degraded execution; "
                        f"reason={operation_status.terminal_reason}"
                    ),
                    severity=DiagnosticSeverity.WARNING,
                )
            )
        return tuple(diagnostics)

    def _publications(
        self,
        records: list[Any],
        text_map: Mapping[str, Any],
    ) -> tuple[tuple[Publication, ...], dict[str, str]]:
        candidates: dict[str, dict[str, Any]] = {}
        aliases: dict[str, str] = {}
        for raw_record in records:
            if not isinstance(raw_record, Mapping):
                continue
            for raw in raw_record.get("publications", []):
                if not isinstance(raw, Mapping):
                    continue
                reference = self._publication_reference(raw)
                if not reference:
                    continue
                publication_id = reference
                aliases[reference] = publication_id
                for identifier_field in ("pmid", "pmcid", "doi", "epmc_id"):
                    if raw.get(identifier_field):
                        aliases[str(raw[identifier_field])] = publication_id
                candidates.setdefault(publication_id, {}).update(dict(raw))
        for reference, raw in text_map.items():
            publication_id = aliases.get(str(reference), str(reference))
            aliases[str(reference)] = publication_id
            if isinstance(raw, Mapping):
                candidates.setdefault(publication_id, {}).update(dict(raw))

        publications = []
        for publication_id, candidate in candidates.items():
            abstract = (
                candidate.get("text")
                if candidate.get("text_source") == "abstract"
                else candidate.get("abstractText") or candidate.get("abstract")
            )
            publications.append(
                Publication(
                    publication_id=publication_id,
                    title=self._optional_text(candidate.get("title")),
                    abstract=self._optional_text(abstract),
                    review=self._publication_review(
                        candidate.get("agentic_curator")
                    ),
                )
            )
        return tuple(publications), aliases

    @staticmethod
    def _publication_reference(publication: Mapping[str, Any]) -> str:
        direct = publication.get("publication_text_ref")
        if direct:
            return str(direct)
        for field, prefix in (
            ("pmid", "PMID"),
            ("pmcid", "PMCID"),
            ("doi", "DOI"),
            ("epmc_id", "EPMC"),
        ):
            if publication.get(field):
                return f"{prefix}:{publication[field]}"
        return ""

    def _publication_review(self, value: Any) -> PublicationReview | None:
        if not isinstance(value, Mapping):
            return None
        normalized = "_".join(
            str(value.get("judgement") or "").lower().replace("-", " ").split()
        )
        if normalized not in {item.value for item in Judgement}:
            return None
        passed = {
            Judgement.RELEVANT.value: True,
            Judgement.NOT_RELEVANT.value: False,
            Judgement.UNSURE.value: None,
        }[normalized]
        reasoning = self._optional_text(value.get("reasoning"))
        criterion = ReviewCriterion(
            criterion="thematic_relevance",
            passed=passed,
            confidence=self._optional_text(value.get("confidence")),
            evidence=reasoning,
        )
        raw_evidence = value.get("evidences", []) or []
        if isinstance(raw_evidence, Mapping):
            raw_evidence = raw_evidence.get("evidences", [])
        if not isinstance(raw_evidence, (list, tuple)):
            raw_evidence = []
        evidence = []
        for item in raw_evidence:
            evidence.append(dict(item) if isinstance(item, Mapping) else {"text": str(item)})
        return PublicationReview(
            judgement=Judgement(normalized),
            criteria=(criterion,),
            evidence=tuple(evidence),
        )

    @staticmethod
    def _operation_status(
        record: Mapping[str, Any], details: Mapping[str, Any] | None
    ) -> OperationStatusV2 | None:
        raw_record = record.get("ontology_harmonization_status")
        raw_details = details.get("status") if isinstance(details, Mapping) else None
        record_status = (
            OperationStatusV2.from_dict(raw_record)
            if isinstance(raw_record, Mapping)
            else None
        )
        detail_status = (
            OperationStatusV2.from_dict(raw_details)
            if isinstance(raw_details, Mapping)
            else None
        )
        if (
            record_status is not None
            and detail_status is not None
            and record_status != detail_status
        ):
            raise ValueError("contradictory harmonization status payloads")
        return record_status or detail_status

    def _harmonization(
        self,
        details: Mapping[str, Any] | None,
        operation_status: OperationStatusV2 | None,
    ) -> HarmonizationResult | None:
        if operation_status is None:
            return None
        details = details if isinstance(details, Mapping) else {}
        targets = []
        for raw in details.get("harmonization_targets", []) or []:
            if not isinstance(raw, Mapping):
                continue
            path = str(
                raw.get("path")
                or raw.get("json_path")
                or raw.get("pre_hz_label_path")
                or raw.get("pre_hz_field_path")
                or ""
            ).strip()
            if not path:
                continue
            raw_value = str(
                raw.get("raw_value")
                or raw.get("pre_hz_label")
                or raw.get("value")
                or raw.get("label")
                or path
            )
            match = self._ontology_match(raw.get("match") or raw)
            targets.append(
                HarmonizationTarget(raw_value=raw_value, path=path, match=match)
            )
        return HarmonizationResult(
            targets=tuple(targets),
            status=operation_status,
        )

    @staticmethod
    def _ontology_match(value: Any) -> OntologyMatch | None:
        if not isinstance(value, Mapping):
            return None
        if value.get("ontology_match") is False:
            return None
        lookup = value.get("ontology_lookup")
        source = lookup if isinstance(lookup, Mapping) else value
        label = (
            source.get("title")
            or source.get("matched_label")
            or source.get("label")
            or value.get("hz_label")
        )
        accession = (
            source.get("accession")
            or source.get("id")
            or source.get("matched_accession")
            or value.get("ontology_term_id")
        )
        framework = (
            source.get("ontology_id")
            or source.get("framework")
            or source.get("ontology")
            or value.get("ontology_id")
        )
        if not all((label, accession, framework)):
            return None
        confidence = source.get("confidence") or value.get("confidence")
        if confidence is None:
            judgement = value.get("ontology_ols_result")
            if isinstance(judgement, Mapping):
                confidence = judgement.get("confidence")
        return OntologyMatch(
            label=str(label),
            accession=str(accession),
            framework=str(framework),
            confidence=AtlasDocumentAdapter._optional_text(confidence),
        )

    @staticmethod
    def _legacy_publication(publication: Publication) -> dict[str, Any]:
        result = {
            "publication_text_ref": publication.publication_id,
            "title": publication.title,
        }
        if publication.abstract:
            result["abstractText"] = publication.abstract
        return result

    @staticmethod
    def _legacy_publication_text(publication: Publication) -> dict[str, Any]:
        result: dict[str, Any] = {"title": publication.title}
        if publication.abstract:
            result.update(text=publication.abstract, text_source="abstract")
        if publication.review is not None:
            result["agentic_curator"] = {
                "judgement": publication.review.judgement.value,
                "evidences": [dict(item) for item in publication.review.evidence],
            }
        return result

    @staticmethod
    def _optional_text(value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None


__all__ = ["AtlasDocumentAdapter"]

from __future__ import annotations

import logging
from contextlib import nullcontext
from collections.abc import Mapping

from meta_standards_converter.converters.ae2json import ae2json
from meta_standards_converter.ae_handlers.ae_webfetcher import (
    AEWebFetcher,
    MAGETabInput,
    TextResource,
)
from meta_standards_converter.runtime_contracts import ResourceProfile, get_resource_profile

from ThematicAtlases.checkpoint import is_retryable_error
from ThematicAtlases.miniml_boundary import checkpoint_packages, checkpoint_payload, canonicalize_miniml_package
from ThematicAtlases.runtime_contracts import safe_error_json, safe_error_mapping
from ThematicAtlases.wrappers.metadata_evidence import (
    ARRAYEXPRESS_PRECANONICAL_STAGE,
    ARRAYEXPRESS_SOURCE_STAGE,
    VALIDATION_DIAGNOSTICS_STAGE,
    canonicalize_with_diagnostics,
    checkpoint_precanonical,
    compressed_text,
    restored_text,
)


logger = logging.getLogger(__name__)


class ArrayExpressWrapper:
    """Collect ArrayExpress/BioStudies MAGE-TAB through MSC in memory."""

    metadata_handler_status = "supported"
    STAGE = "arrayexpress_metadata"
    PREFIXES = ("E-MTAB-", "E-GEOD-", "E-MEXP-")

    def __init__(
        self,
        converter_factory=None,
        resource_profile: str | ResourceProfile = "standard",
        resource_overrides=None,
    ):
        self._converter_factory = converter_factory
        self.resource_profile = (
            resource_profile.with_overrides(resource_overrides)
            if isinstance(resource_profile, ResourceProfile) and resource_overrides
            else resource_profile
            if isinstance(resource_profile, ResourceProfile)
            else get_resource_profile(
                resource_profile,
                overrides=resource_overrides,
            )
        )

    def collect_accession_metadata(
        self,
        jsons: list[dict],
        checkpoint_store=None,
    ) -> list[dict]:
        records = []
        for index, record in enumerate(jsons, start=1):
            accession = self._normalize_accession(record.get("datalink_id"))
            if not accession:
                records.append(self._error_record(record))
                continue
            item_lock = (
                checkpoint_store.item_lock(self.STAGE, accession)
                if checkpoint_store is not None
                else nullcontext()
            )
            with item_lock:
                checkpoint = (
                    checkpoint_store.get(self.STAGE, accession)
                    if checkpoint_store is not None
                    else None
                )
                if checkpoint and checkpoint["status"] == "available" and checkpoint_packages(checkpoint.get("payload")) is not None:
                    records.append(self._record_from_checkpoint(record, checkpoint))
                    continue
                if checkpoint and checkpoint["status"] in {"no_data", "terminal_error"}:
                    records.append(self._record_from_checkpoint(record, checkpoint))
                    continue
                try:
                    converter = self._converter()
                    if (
                        checkpoint_store is not None
                        and hasattr(converter, "fetcher")
                        and hasattr(converter, "parser")
                    ):
                        packages = self._convert_with_evidence(
                            converter=converter,
                            accession=accession,
                            index=index,
                            checkpoint_store=checkpoint_store,
                        )
                    else:
                        converted = converter.convert(
                            source=accession,
                            out=None,
                            sdrf_sources=None,
                        )
                        packages = [
                            canonicalize_miniml_package(item)
                            for item in converted
                            if isinstance(item, Mapping)
                        ]
                except Exception as error:
                    logger.warning(
                        "ArrayExpress metadata failed accession=%s error_type=%s",
                        accession,
                        type(error).__name__,
                    )
                    status = (
                        "retryable_error" if is_retryable_error(error)
                        else "terminal_error"
                    )
                    if checkpoint_store is not None:
                        retryable = is_retryable_error(error)
                        safe_error = safe_error_mapping(
                            error,
                            provider="BioStudies ArrayExpress",
                            stage=self.STAGE,
                            item_id=accession,
                            retryable=retryable,
                        )
                        if checkpoint_store.get(
                            ARRAYEXPRESS_SOURCE_STAGE, accession
                        ) is None:
                            checkpoint_store.put(
                                ARRAYEXPRESS_SOURCE_STAGE,
                                accession,
                                index,
                                status,
                                payload={
                                    "contract_version": 1,
                                    "provider": "arrayexpress",
                                    "accession": accession,
                                    "failure_stage": "download",
                                    "correlation_id": safe_error.get("correlation_id"),
                                },
                                error_type=type(error).__name__,
                                failure_category="provider_retryable" if retryable else "provider_terminal",
                            )
                        elif checkpoint_store.get(
                            ARRAYEXPRESS_PRECANONICAL_STAGE, accession
                        ) is None and checkpoint_store.get(
                            VALIDATION_DIAGNOSTICS_STAGE,
                            f"arrayexpress:{accession}",
                        ) is None:
                            checkpoint_store.put(
                                VALIDATION_DIAGNOSTICS_STAGE,
                                f"arrayexpress:{accession}",
                                index,
                                status,
                                payload={
                                    "contract_version": 1,
                                    "provider": "arrayexpress",
                                    "accession": accession,
                                    "failure_stage": "parse",
                                    "correlation_id": safe_error.get("correlation_id"),
                                    "diagnostics": [],
                                },
                                error_type=type(error).__name__,
                                failure_category="provider_retryable" if retryable else "provider_terminal",
                            )
                        checkpoint_store.put(
                            self.STAGE,
                            accession,
                            index,
                            status,
                            payload=checkpoint_payload([], checkpoint_version=2),
                            error=safe_error_json(
                                error,
                                provider="BioStudies ArrayExpress",
                                stage=self.STAGE,
                                item_id=accession,
                                retryable=is_retryable_error(error),
                            ),
                        )
                    records.append(self._error_record(record))
                    continue
                package = next(iter(packages), None)
                status = "available" if package is not None else "no_data"
                payload = checkpoint_payload(
                    [package] if package is not None else [], checkpoint_version=2
                )
                if checkpoint_store is not None:
                    checkpoint_store.put(
                        self.STAGE, accession, index, status, payload=payload
                    )
                records.append(
                    self._available_record(record, package)
                    if package is not None
                    else self._unavailable_record(record)
                )
        return records

    def _convert_with_evidence(
        self,
        *,
        converter,
        accession: str,
        index: int,
        checkpoint_store,
    ) -> list[dict]:
        source_checkpoint = checkpoint_store.get(
            ARRAYEXPRESS_SOURCE_STAGE, accession
        )
        if source_checkpoint and source_checkpoint["status"] == "available":
            source = self._restore_source(source_checkpoint["payload"])
        else:
            source = converter.fetcher.resolve(accession, sdrf_sources=None)
            checkpoint_store.put(
                ARRAYEXPRESS_SOURCE_STAGE,
                accession,
                index,
                "available",
                payload=self._source_payload(source),
            )
        parsed = [converter.parser.parse(source)]
        precanonical = checkpoint_precanonical(
            checkpoint_store,
            ARRAYEXPRESS_PRECANONICAL_STAGE,
            accession,
            index,
            parsed,
        )
        return canonicalize_with_diagnostics(
            precanonical,
            store=checkpoint_store,
            provider="arrayexpress",
            key=accession,
            ordinal=index,
        )

    @staticmethod
    def _resource_payload(resource: TextResource) -> dict:
        return {
            "name": resource.name,
            "origin": resource.origin,
            "content": compressed_text(resource.text),
        }

    @classmethod
    def _source_payload(cls, source: MAGETabInput) -> dict:
        return {
            "contract_version": 1,
            "provider": "arrayexpress",
            "source": source.source,
            "source_kind": source.source_kind,
            "idf": cls._resource_payload(source.idf),
            "sdrfs": [cls._resource_payload(item) for item in source.sdrfs],
        }

    @staticmethod
    def _restore_resource(value: Mapping) -> TextResource:
        return TextResource(
            str(value.get("name") or ""),
            restored_text(value.get("content") or {}),
            str(value.get("origin") or ""),
        )

    @classmethod
    def _restore_source(cls, value: Mapping) -> MAGETabInput:
        return MAGETabInput(
            cls._restore_resource(value.get("idf") or {}),
            tuple(
                cls._restore_resource(item)
                for item in value.get("sdrfs", [])
                if isinstance(item, Mapping)
            ),
            str(value.get("source") or ""),
            str(value.get("source_kind") or ""),
        )

    def _converter(self):
        if self._converter_factory is not None:
            return self._converter_factory()
        return ae2json(
            fetcher=AEWebFetcher(resource_profile=self.resource_profile)
        )

    def available_accession_metadata(
        self,
        jsons: list[dict],
        checkpoint_store,
    ) -> list[dict]:
        records = []
        for record in jsons:
            accession = self._normalize_accession(record.get("datalink_id"))
            checkpoint = checkpoint_store.get(self.STAGE, accession) if accession else None
            if checkpoint and checkpoint["status"] == "available" and checkpoint_packages(checkpoint.get("payload")) is not None:
                records.append(self._record_from_checkpoint(record, checkpoint))
            elif checkpoint and checkpoint["status"] in {"no_data", "terminal_error"}:
                records.append(self._record_from_checkpoint(record, checkpoint))
            else:
                records.append(self._pending_record(record))
        return records

    def _record_from_checkpoint(self, record: dict, checkpoint: dict) -> dict:
        status = checkpoint.get("status")
        packages = checkpoint_packages(checkpoint.get("payload"))
        package = next(iter(packages or ()), None)
        if status == "available" and package is not None:
            return self._available_record(record, package)
        if status == "no_data":
            return self._unavailable_record(record)
        return self._error_record(record)

    @classmethod
    def _normalize_accession(cls, value) -> str:
        accession = str(value or "").strip().upper()
        return accession if accession.startswith(cls.PREFIXES) else ""

    @staticmethod
    def _base_record(record: dict) -> dict:
        return {
            **record,
            "metadata_repository": "arrayexpress",
            "metadata_source": "ae2json",
        }

    def _available_record(self, record: dict, package: dict) -> dict:
        return {
            **self._base_record(record),
            "metadata_status": "available",
            "accession_metadata": package,
        }

    def _unavailable_record(self, record: dict) -> dict:
        return {
            **self._base_record(record),
            "metadata_status": "unavailable",
            "accession_metadata": None,
        }

    def _error_record(self, record: dict) -> dict:
        return {
            **self._base_record(record),
            "metadata_status": "error",
            "accession_metadata": None,
        }

    def _pending_record(self, record: dict) -> dict:
        return {
            **self._base_record(record),
            "metadata_status": "pending",
            "accession_metadata": None,
        }

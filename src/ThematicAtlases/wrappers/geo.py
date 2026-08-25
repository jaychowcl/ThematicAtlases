import logging
import time
from contextlib import nullcontext
from dataclasses import dataclass
from typing import Any

from meta_standards_converter.converters.geo2json import geo2json
from meta_standards_converter.enrichers.miniml_enricher import MINiMLEnricher
from meta_standards_converter.miniml import MINiMLCodec
from meta_standards_converter.runtime_contracts import ResourceProfile, get_resource_profile
import requests
from meta_standards_converter.helpers.request_helper import NCBIApplicationIdentity

from ThematicAtlases.checkpoint import is_retryable_error
from ThematicAtlases.infrastructure import RequestPolicy
from ThematicAtlases.runtime_contracts import safe_error_json, safe_error_mapping
from ThematicAtlases.miniml_boundary import (
    canonicalize_miniml_packages,
    checkpoint_packages,
    checkpoint_payload,
)
from ThematicAtlases.wrappers.enrichment import (
    CheckpointedINSDCFetcher,
    CheckpointedPubmedFetcher,
    RetryTags,
)
from ThematicAtlases.wrappers.geo_records import GEORecordPolicy
from ThematicAtlases.wrappers.metadata_evidence import (
    GEO_PRECANONICAL_STAGE,
    GEO_SOURCE_STAGE,
    VALIDATION_DIAGNOSTICS_STAGE,
    canonicalize_with_diagnostics,
    checkpoint_precanonical,
    compressed_text,
    restored_text,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EnrichmentRepairOutcome:
    stage: str
    identifier: str
    package_index: int
    status: str
    error: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "identifier": self.identifier,
            "package_index": self.package_index,
            "status": self.status,
            "error": self.error,
        }


@dataclass(frozen=True)
class EnrichmentRepairSummary:
    selected: RetryTags
    outcomes: tuple[EnrichmentRepairOutcome, ...]
    contract_version: str = "1.0"

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_version": self.contract_version,
            "selected_identifiers": {
                "pubmed": list(self.selected.pubmed),
                "sra": list(self.selected.sra),
                "ena": list(self.selected.ena),
            },
            "attempt_count": len(self.outcomes),
            "succeeded_count": sum(
                outcome.status == "succeeded" for outcome in self.outcomes
            ),
            "failed_count": sum(
                outcome.status == "failed" for outcome in self.outcomes
            ),
            "outcomes": [outcome.to_dict() for outcome in self.outcomes],
        }


def _metadata_checkpoint_payload(_packages, **values):
    values = dict(values)
    for key in (
        "checkpoint_version",
        "miniml_checkpoint_payload_version",
        "miniml_schema_version",
        "packages",
    ):
        values.pop(key, None)
    return checkpoint_payload(_packages, checkpoint_version=4, **values)


class GEOWrapper:
    metadata_handler_status = "supported"

    def __init__(
        self,
        api_key: str | None = None,
        tool: str = "ThematicAtlases",
        email: str | None = None,
        timeout: int | float | tuple[int | float, int | float] | None = None,
        request_delay: float = 0.5,
        max_retries: int = 3,
        request_policy: RequestPolicy | None = None,
        resource_profile: str | ResourceProfile = "standard",
        resource_overrides=None,
        record_policy: GEORecordPolicy | None = None,
        enrich_metadata: bool = True,
    ):
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
        effective_timeout = timeout or (
            self.resource_profile.connect_timeout_seconds,
            self.resource_profile.read_timeout_seconds,
        )
        identity_options = {"tool": tool, "email": email}
        if api_key is not None:
            identity_options["api_key"] = api_key
        self._ncbi_identity = NCBIApplicationIdentity(**identity_options)
        self._request_settings = {
            "timeout": effective_timeout,
            "request_delay": request_delay,
            "max_retries": max_retries,
        }
        self._base_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
        self._retry_statuses = {403, 429, 500, 502, 503, 504}
        self._request_policy = request_policy or RequestPolicy(
            timeout=effective_timeout,
            max_retries=max_retries,
            retry_statuses=self._retry_statuses,
            sleep=time.sleep,
            logger=logger,
            name="GEO",
            resource_profile=self.resource_profile,
        )
        self._record_policy = record_policy or GEORecordPolicy()
        self._enrich_metadata = bool(enrich_metadata)

    def collect_accession_metadata(
        self,
        jsons: list[dict],
        checkpoint_store=None,
        retry_tags: RetryTags | None = None,
    ) -> list[dict]:
        records = []
        dropped_records = 0

        logger.info(
            "GEO accession metadata progress stage=resolve-accessions input_records=%s",
            len(jsons),
        )

        for index, record in enumerate(jsons, start=1):
            if index == 1 or index == len(jsons) or index % 10 == 0:
                logger.info(
                    "GEO accession resolution progress record_index=%s record_total=%s",
                    index,
                    len(jsons),
                )
            source_accession = self._normalize_accession(
                record.get("datalink_id", "")
            )
            item_lock = (
                checkpoint_store.item_lock("geo_resolution", source_accession)
                if checkpoint_store is not None
                else nullcontext()
            )
            with item_lock:
                checkpoint = (
                    checkpoint_store.get("geo_resolution", source_accession)
                    if checkpoint_store is not None
                    else None
                )
                if checkpoint and checkpoint["status"] in {"available", "no_data"}:
                    gse_accession = (checkpoint.get("payload") or {}).get("gse_accession")
                else:
                    try:
                        gse_accession = self.get_gse(source_accession)
                    except Exception as error:
                        if checkpoint_store is not None:
                            checkpoint_store.put(
                                "geo_resolution",
                                source_accession,
                                index,
                                "retryable_error"
                                if is_retryable_error(error)
                                else "terminal_error",
                                payload={
                                    "next_retry_at": retry_at
                                }
                                if (
                                    retry_at := getattr(
                                        error,
                                        "retry_at",
                                        getattr(
                                            getattr(error, "response", None),
                                            "_thematic_atlases_retry_at",
                                            None,
                                        ),
                                    )
                                )
                                else None,
                                error=safe_error_json(
                                    error,
                                    provider="NCBI GEO",
                                    stage="geo_resolution",
                                    item_id=source_accession,
                                    retryable=is_retryable_error(error),
                                ),
                            )
                        raise
                    if checkpoint_store is not None:
                        checkpoint_store.put(
                            "geo_resolution",
                            source_accession,
                            index,
                            "available" if gse_accession else "no_data",
                            payload={"gse_accession": gse_accession},
                        )

            if gse_accession is None:
                dropped_records += 1
                continue

            records.append(self._gse_record(record=record, gse_accession=gse_accession))

        deduplicated_records = self._deduplicate_gse_jsons(jsons=records)
        logger.info(
            "GEO accession resolution stats input_records=%s resolved_records=%s dropped_records=%s deduplicated_gse_records=%s",
            len(jsons),
            len(records),
            dropped_records,
            len(deduplicated_records),
        )
        logger.info(
            "GEO accession metadata progress stage=collect-gse-metadata gse_records=%s",
            len(deduplicated_records),
        )
        result = self._collect_gse_metadata_records(
            records=deduplicated_records,
            checkpoint_store=checkpoint_store,
            retry_tags=retry_tags,
        )
        logger.info(
            "GEO accession metadata stats input_records=%s output_records=%s dropped_records=%s",
            len(jsons),
            len(result),
            dropped_records,
        )
        return result

    def available_accession_metadata(
        self,
        jsons: list[dict],
        checkpoint_store,
    ) -> list[dict]:
        """Overlay completed metadata without issuing network requests."""
        resolved = []
        for record in jsons:
            source_accession = self._normalize_accession(record.get("datalink_id", ""))
            checkpoint = checkpoint_store.get("geo_resolution", source_accession)
            if checkpoint and checkpoint["status"] in {"available", "no_data"}:
                gse_accession = (checkpoint.get("payload") or {}).get("gse_accession")
            elif checkpoint and checkpoint["status"] == "terminal_error":
                resolved.append(self._metadata_error_record(record))
                continue
            elif source_accession.startswith("GSE"):
                gse_accession = source_accession
            else:
                gse_accession = None
            if gse_accession:
                resolved.append(self._gse_record(record, gse_accession))
            else:
                resolved.append(
                    {
                        **record,
                        "metadata_repository": "geo",
                        "metadata_status": "pending",
                        "accession_metadata": None,
                    }
                )

        gse_records = self._deduplicate_gse_jsons(
            [record for record in resolved if str(record.get("datalink_id", "")).upper().startswith("GSE")]
        )
        pending_non_gse = [
            record
            for record in resolved
            if not str(record.get("datalink_id", "")).upper().startswith("GSE")
        ]
        enriched = []
        for record in gse_records:
            checkpoint = checkpoint_store.get("geo_metadata", record.get("datalink_id", ""))
            if (
                checkpoint
                and checkpoint["status"] == "available"
                and checkpoint_packages(checkpoint.get("payload")) is not None
            ):
                enriched.extend(self._records_from_metadata_checkpoint(record, checkpoint))
            elif checkpoint and checkpoint["status"] in {"no_data", "terminal_error"}:
                enriched.extend(self._records_from_metadata_checkpoint(record, checkpoint))
            else:
                enriched.append(
                    {
                        **record,
                        "metadata_repository": "geo",
                        "metadata_status": "pending",
                        "accession_metadata": None,
                    }
                )
        return self._deduplicate_gse_jsons(enriched) + pending_non_gse

    def get_gse(self, accession: str) -> str | None:
        accession = self._normalize_accession(accession=accession)

        if not accession:
            logger.debug("GEO accession resolution decision accession=%r result=empty", accession)
            return None

        if accession.startswith("GSE"):
            logger.debug(
                "GEO accession resolution decision accession=%r result=direct_gse",
                accession,
            )
            return accession

        if accession.startswith("GPL"):
            logger.debug(
                "GEO accession resolution decision accession=%r result=drop_gpl",
                accession,
            )
            return None

        if not accession.startswith(("GDS", "GSM")):
            logger.debug(
                "GEO accession resolution decision accession=%r result=unsupported_prefix",
                accession,
            )
            return None

        uids = self._search(accession=accession)

        if not uids:
            logger.debug(
                "GEO accession resolution decision accession=%r result=no_uids",
                accession,
            )
            return None

        summaries = self._summary(uids=uids)
        summary = self._matching_summary(accession=accession, summaries=summaries)

        if summary is None:
            logger.debug(
                "GEO accession resolution decision accession=%r result=no_matching_summary uids=%s",
                accession,
                len(uids),
            )
            return None

        gse_accession = self._gse_from_summary(summary=summary)
        logger.debug(
            "GEO accession resolution decision accession=%r result=%r uids=%s",
            accession,
            gse_accession,
            len(uids),
        )
        return gse_accession

    def _search(self, accession: str) -> list[str]:
        params = self._params(
            {
                "db": "gds",
                "term": f"{accession}[ACCN]",
                "retmode": "json",
                "retmax": 20,
            }
        )
        logger.debug("GEO ESearch request accession=%r", accession)
        response = self._get(url=f"{self._base_url}/esearch.fcgi", params=params)
        uids = response.get("esearchresult", {}).get("idlist", [])
        logger.debug("GEO ESearch response accession=%r uid_count=%s", accession, len(uids))
        return uids

    def _summary(self, uids: list[str]) -> dict:
        params = self._params(
            {
                "db": "gds",
                "id": ",".join(uids),
                "retmode": "json",
            }
        )
        logger.debug("GEO ESummary request uid_count=%s", len(uids))
        return self._get(url=f"{self._base_url}/esummary.fcgi", params=params)

    def _get(self, url: str, params: dict) -> dict:
        started = time.monotonic()
        logger.debug(
            "GEO HTTP request endpoint=%s timeout=%s",
            url.rsplit("/", 1)[-1],
            self._request_settings["timeout"],
        )
        response = self._request_policy.get(url, params=params)
        logger.debug(
            "GEO HTTP response endpoint=%s status=%s elapsed_seconds=%.3f",
            url.rsplit("/", 1)[-1],
            response.status_code,
            time.monotonic() - started,
        )
        return response.json()

    def _params(self, params: dict) -> dict:
        params = dict(params)

        params.update(self._ncbi_identity.params())

        return params

    def _retry_delay(self, response: requests.Response, attempt: int) -> float:
        return RequestPolicy.retry_delay(response, attempt)

    def _matching_summary(self, accession: str, summaries: dict) -> dict | None:
        result = summaries.get("result", {})

        for uid in result.get("uids", []):
            summary = result.get(uid, {})

            if self._normalize_accession(summary.get("accession", "")) == accession:
                return summary

        return None

    def _gse_from_summary(self, summary: dict) -> str | None:
        for value in str(summary.get("gse", "")).split(";"):
            value = value.strip()

            if value:
                return self._normalize_accession(accession=f"GSE{value}")

        return None

    def _normalize_accession(self, accession: str) -> str:
        return str(accession or "").strip().upper()

    def _collect_gse_metadata_records(
        self,
        records: list[dict],
        checkpoint_store=None,
        retry_tags: RetryTags | None = None,
    ) -> list[dict]:
        metadata_records = []
        packages_returned = 0
        related_records = 0
        error_records = 0
        unavailable_records = 0

        for index, record in enumerate(records, start=1):
            gse_accession = record.get("datalink_id", "")
            logger.info(
                "GEO metadata progress gse_index=%s gse_total=%s gse_accession=%s",
                index,
                len(records),
                gse_accession,
            )
            item_lock = (
                checkpoint_store.item_lock("geo_metadata", gse_accession)
                if checkpoint_store is not None
                else nullcontext()
            )
            with item_lock:
                checkpoint = (
                    checkpoint_store.get("geo_metadata", gse_accession)
                    if checkpoint_store is not None
                    else None
                )
                cached_packages = (
                    checkpoint_packages(checkpoint.get("payload"))
                    if checkpoint and checkpoint["status"] == "available"
                    else None
                )
                if cached_packages is not None:
                    payload = checkpoint.get("payload") or {}
                    packages = cached_packages
                    mode = payload.get("enrichment_mode")
                    if (
                        self._enrich_metadata
                        and checkpoint_store is not None
                        and packages
                        and (mode in {"all", "selected"} or retry_tags is not None)
                    ):
                        packages, payload = self._repair_enrichment_packages(
                            packages=packages,
                            payload=payload,
                            checkpoint_store=checkpoint_store,
                            retry_tags=retry_tags,
                        )
                        checkpoint_store.put(
                            "geo_metadata",
                            gse_accession,
                            index,
                            "available",
                            payload=payload,
                        )
                        checkpoint = checkpoint_store.get(
                            "geo_metadata", gse_accession
                        )
                    metadata_records.extend(
                        self._records_from_metadata_checkpoint(record, checkpoint)
                    )
                    continue
                if checkpoint and checkpoint["status"] in {"no_data", "terminal_error"}:
                    metadata_records.extend(
                        self._records_from_metadata_checkpoint(record, checkpoint)
                    )
                    continue

                try:
                    pending_payload = (checkpoint or {}).get("payload") or {}
                    if (
                        checkpoint_store is not None
                        and checkpoint_packages(pending_payload)
                    ):
                        packages = checkpoint_packages(pending_payload) or []
                        if self._enrich_metadata:
                            packages, pending_payload = self._repair_enrichment_packages(
                                packages=packages,
                                payload=pending_payload,
                                checkpoint_store=checkpoint_store,
                                retry_tags=retry_tags,
                            )
                        else:
                            pending_payload = _metadata_checkpoint_payload(
                                packages,
                                enrichment_mode="none",
                                enrichment_state="complete",
                            )
                    elif checkpoint_store is not None:
                        if not self._enrich_metadata:
                            packages = self._gse_metadata_packages(
                                gse_accession=gse_accession
                            )
                            packages = canonicalize_miniml_packages(packages)
                            pending_payload = _metadata_checkpoint_payload(
                                packages,
                                enrichment_mode="none",
                                enrichment_state="complete",
                            )
                        elif (
                            type(self)._gse_metadata_packages
                            is not GEOWrapper._gse_metadata_packages
                        ):
                            packages = self._gse_metadata_packages(
                                gse_accession=gse_accession
                            )
                            packages = canonicalize_miniml_packages(packages)
                            pending_payload = _metadata_checkpoint_payload(packages)
                        else:
                            packages, pending_payload = self._checkpointed_gse_metadata_packages(
                                gse_accession=gse_accession,
                                index=index,
                                checkpoint_store=checkpoint_store,
                                retry_tags=retry_tags,
                            )
                    else:
                        packages = self._gse_metadata_packages(gse_accession=gse_accession)
                        packages = canonicalize_miniml_packages(packages)
                        pending_payload = _metadata_checkpoint_payload(packages)
                except Exception as error:
                    error_records += 1
                    logger.warning(
                        "GEO metadata failed gse_accession=%s error_type=%s",
                        gse_accession,
                        type(error).__name__,
                    )
                    error_record = self._metadata_error_record(record=record)
                    metadata_records.append(error_record)
                    if checkpoint_store is not None:
                        retryable = is_retryable_error(error)
                        safe_error = safe_error_mapping(
                            error,
                            provider="NCBI GEO",
                            stage="geo_metadata",
                            item_id=gse_accession,
                            retryable=retryable,
                        )
                        if checkpoint_store.get(GEO_SOURCE_STAGE, gse_accession) is None:
                            checkpoint_store.put(
                                GEO_SOURCE_STAGE,
                                gse_accession,
                                index,
                                "retryable_error" if retryable else "terminal_error",
                                payload={
                                    "contract_version": 1,
                                    "provider": "geo",
                                    "accession": gse_accession,
                                    "failure_stage": "download",
                                    "correlation_id": safe_error.get("correlation_id"),
                                },
                                error_type=type(error).__name__,
                                failure_category="provider_retryable" if retryable else "provider_terminal",
                            )
                        elif checkpoint_store.get(
                            GEO_PRECANONICAL_STAGE, gse_accession
                        ) is None and checkpoint_store.get(
                            VALIDATION_DIAGNOSTICS_STAGE, f"geo:{gse_accession}"
                        ) is None:
                            checkpoint_store.put(
                                VALIDATION_DIAGNOSTICS_STAGE,
                                f"geo:{gse_accession}",
                                index,
                                "retryable_error" if retryable else "terminal_error",
                                payload={
                                    "contract_version": 1,
                                    "provider": "geo",
                                    "accession": gse_accession,
                                    "failure_stage": "parse",
                                    "correlation_id": safe_error.get("correlation_id"),
                                    "diagnostics": [],
                                },
                                error_type=type(error).__name__,
                                failure_category="provider_retryable" if retryable else "provider_terminal",
                            )
                        checkpoint_store.put(
                            "geo_metadata",
                            gse_accession,
                            index,
                            "retryable_error" if retryable else "terminal_error",
                            payload={
                                **(
                                    (checkpoint or {}).get("payload")
                                    or _metadata_checkpoint_payload([])
                                ),
                                **(
                                    {"next_retry_at": retry_at}
                                    if (
                                        retry_at := getattr(
                                            error,
                                            "retry_at",
                                            getattr(
                                                getattr(error, "response", None),
                                                "_thematic_atlases_retry_at",
                                                None,
                                            ),
                                        )
                                    )
                                    else {}
                                ),
                            },
                            error=safe_error_json(
                                error,
                                provider="NCBI GEO",
                                stage="geo_metadata",
                                item_id=gse_accession,
                                retryable=retryable,
                            ),
                        )
                    continue

                if not packages:
                    unavailable_records += 1
                    metadata_records.append(self._metadata_unavailable_record(record=record))
                    if checkpoint_store is not None:
                        checkpoint_store.put(
                            "geo_metadata",
                            gse_accession,
                            index,
                            "no_data",
                            payload=_metadata_checkpoint_payload(
                                [],
                                enrichment_mode=(
                                    "all" if self._enrich_metadata else "none"
                                ),
                                enrichment_state="complete",
                            ),
                        )
                    continue

                packages_returned += len(packages)
                package_records = self._metadata_records_from_packages(record, packages)
                related_records += sum(
                    item.get("datalink_id") != gse_accession for item in package_records
                )
                metadata_records.extend(package_records)
                if checkpoint_store is not None:
                    completed_payload = {
                        **pending_payload,
                        "enrichment_state": "complete",
                    }
                    if not self._enrich_metadata:
                        completed_payload["enrichment_mode"] = "none"
                    checkpoint_store.put(
                        "geo_metadata",
                        gse_accession,
                        index,
                        "available",
                        payload=_metadata_checkpoint_payload(
                            packages,
                            **completed_payload,
                        ),
                    )

        result = self._deduplicate_gse_jsons(jsons=metadata_records)
        logger.info(
            "GEO metadata stats source_gse_records=%s metadata_packages=%s related_records=%s error_records=%s unavailable_records=%s output_records=%s",
            len(records),
            packages_returned,
            related_records,
            error_records,
            unavailable_records,
            len(result),
        )
        return result

    def _checkpointed_gse_metadata_packages(
        self,
        *,
        gse_accession: str,
        index: int,
        checkpoint_store,
        retry_tags: RetryTags | None,
    ) -> tuple[list[dict], dict]:
        enricher = self._checkpointed_enricher(checkpoint_store, retry_tags)
        converter = geo2json(enricher=enricher)
        if not hasattr(converter, "geo_fetcher") or not hasattr(converter, "parser"):
            parsed = converter.convert(
                gse=gse_accession,
                related_series=True,
                remove_empty=True,
                enrich=False,
                out=None,
            )
        else:
            source_checkpoint = checkpoint_store.get(GEO_SOURCE_STAGE, gse_accession)
            if source_checkpoint and source_checkpoint["status"] == "available":
                miniml = restored_text(source_checkpoint["payload"]["content"])
            else:
                logger.debug(
                    "GEO MINiML evidence request gse_accession=%s", gse_accession
                )
                miniml = converter.geo_fetcher.fetch_gse_miniml(gse=gse_accession)
                checkpoint_store.put(
                    GEO_SOURCE_STAGE,
                    gse_accession,
                    index,
                    "available",
                    payload={
                        "contract_version": 1,
                        "provider": "geo",
                        "accession": gse_accession,
                        "content_type": "application/xml",
                        "content": compressed_text(miniml),
                    },
                )
            parsed = converter.parser.parse(
                miniml=miniml,
                remove_empty=True,
                related_series=True,
            )
        precanonical = checkpoint_precanonical(
            checkpoint_store,
            GEO_PRECANONICAL_STAGE,
            gse_accession,
            index,
            parsed,
        )
        packages = canonicalize_with_diagnostics(
            precanonical,
            store=checkpoint_store,
            provider="geo",
            key=gse_accession,
            ordinal=index,
        )
        payload = _metadata_checkpoint_payload(
            packages, enrichment_mode="all", enrichment_state="pending"
        )
        checkpoint_store.put(
            "geo_metadata",
            gse_accession,
            index,
            "retryable_error",
            payload=payload,
            error="identifier enrichment pending",
        )
        for package_index, package in enumerate(packages):
            packages[package_index] = canonicalize_miniml_packages(
                [converter.enricher.enrich(data=package)]
            )[0]
            payload = _metadata_checkpoint_payload(
                packages, enrichment_mode="all", enrichment_state="pending"
            )
            checkpoint_store.put(
                "geo_metadata",
                gse_accession,
                index,
                "retryable_error",
                payload=payload,
                error="identifier enrichment pending",
            )
        return packages, payload

    def _checkpointed_enricher(
        self,
        checkpoint_store,
        retry_tags: RetryTags | None = None,
        *,
        ena_identifiers=None,
    ):
        return MINiMLEnricher(
            pubmed_fetcher=CheckpointedPubmedFetcher(
                checkpoint_store,
                forced_identifiers=() if retry_tags is None else retry_tags.pubmed,
                tag_id=None if retry_tags is None else retry_tags.tag_id,
                resource_profile=self.resource_profile,
            ),
            insdc_fetcher=CheckpointedINSDCFetcher(
                checkpoint_store,
                forced_sra=() if retry_tags is None else retry_tags.sra,
                forced_ena=() if retry_tags is None else retry_tags.ena,
                ena_identifiers=ena_identifiers,
                tag_id=None if retry_tags is None else retry_tags.tag_id,
                resource_profile=self.resource_profile,
            ),
        )

    def _repair_enrichment_packages(
        self,
        *,
        packages: list[dict],
        payload: dict,
        checkpoint_store,
        retry_tags: RetryTags | None,
    ) -> tuple[list[dict], dict]:
        mode = payload.get("enrichment_mode")
        if mode == "all":
            enricher = self._checkpointed_enricher(checkpoint_store, retry_tags)
            packages = canonicalize_miniml_packages(
                [enricher.enrich(data=package) for package in packages]
            )
            return packages, _metadata_checkpoint_payload(
                packages, **{**payload, "enrichment_state": "complete"}
            )

        tracked = payload.get("tracked_identifiers") or {
            "pubmed": [], "sra": [], "ena": []
        }
        tracked = {key: list(values) for key, values in tracked.items()}
        if retry_tags is not None:
            for key in ("pubmed", "sra", "ena"):
                for identifier in getattr(retry_tags, key):
                    if identifier not in tracked[key]:
                        tracked[key].append(identifier)
        selected = RetryTags(
            tag_id="" if retry_tags is None else retry_tags.tag_id,
            pubmed=tuple(tracked["pubmed"]),
            sra=tuple(tracked["sra"]),
            ena=tuple(tracked["ena"]),
        )
        packages, repair_summary = self._repair_selected_packages(
            packages,
            checkpoint_store,
            selected,
            retry_tags,
        )
        return packages, _metadata_checkpoint_payload(
            packages,
            **{
                **payload,
                "enrichment_mode": "selected",
                "enrichment_state": "complete",
                "tracked_identifiers": tracked,
                "repair_summary": repair_summary.to_dict(),
            },
        )

    def _repair_selected_packages(
        self,
        packages,
        checkpoint_store,
        selected: RetryTags,
        forced: RetryTags | None,
    ) -> tuple[list[dict], EnrichmentRepairSummary]:
        pubmed_fetcher = CheckpointedPubmedFetcher(
            checkpoint_store,
            forced_identifiers=() if forced is None else forced.pubmed,
            tag_id=None if forced is None else forced.tag_id,
            resource_profile=self.resource_profile,
        )
        insdc_fetcher = CheckpointedINSDCFetcher(
            checkpoint_store,
            forced_sra=() if forced is None else forced.sra,
            forced_ena=() if forced is None else forced.ena,
            ena_identifiers=selected.ena,
            tag_id=None if forced is None else forced.tag_id,
            resource_profile=self.resource_profile,
        )
        outcomes = []
        for package_index, package in enumerate(packages):
            series = package.get("series") if isinstance(package.get("series"), dict) else {}
            publications = series.get("pubmed_publication") or []
            publications = publications if isinstance(publications, list) else [publications]
            for publication in publications:
                identifier = str(publication.get("pubmed_id") or "")
                if identifier not in selected.pubmed:
                    continue
                try:
                    values = pubmed_fetcher.pubmed_summary(identifier)
                except Exception as error:
                    outcomes.append(EnrichmentRepairOutcome(
                        stage="pubmed_enrichment",
                        identifier=identifier,
                        package_index=package_index,
                        status="failed",
                        error=safe_error_mapping(
                            error,
                            provider="NCBI PubMed",
                            stage="pubmed_enrichment",
                            item_id=identifier,
                            retryable=is_retryable_error(error),
                        ),
                    ))
                    continue
                outcomes.append(EnrichmentRepairOutcome(
                    stage="pubmed_enrichment",
                    identifier=identifier,
                    package_index=package_index,
                    status="succeeded",
                ))
                for field, value in zip(
                    ("doi", "author_list", "title", "status", "status_term_source_ref", "status_term_accession_number"),
                    values,
                ):
                    publication[field] = value

            samples = package.get("sample") or []
            samples = samples if isinstance(samples, list) else [samples]
            for sample in samples:
                if not isinstance(sample, dict):
                    continue
                accessions = sample.get("sra_accession") or []
                accessions = accessions if isinstance(accessions, list) else [accessions]
                runs = list(sample.get("sra_run") or [])
                for identifier in accessions:
                    identifier = str(identifier).upper()
                    if identifier in selected.sra:
                        try:
                            runs = insdc_fetcher.fetch_sra_runs(identifier)
                        except Exception as error:
                            outcomes.append(EnrichmentRepairOutcome(
                                stage="sra_xml",
                                identifier=identifier,
                                package_index=package_index,
                                status="failed",
                                error=safe_error_mapping(
                                    error,
                                    provider="NCBI SRA",
                                    stage="sra_xml",
                                    item_id=identifier,
                                    retryable=is_retryable_error(error),
                                ),
                            ))
                            continue
                        outcomes.append(EnrichmentRepairOutcome(
                            stage="sra_xml",
                            identifier=identifier,
                            package_index=package_index,
                            status="succeeded",
                        ))
                    elif identifier in selected.ena:
                        try:
                            fastqs = insdc_fetcher.fetch_ena_fastq_files(identifier)
                        except Exception as error:
                            outcomes.append(EnrichmentRepairOutcome(
                                stage="ena_fastq",
                                identifier=identifier,
                                package_index=package_index,
                                status="failed",
                                error=safe_error_mapping(
                                    error,
                                    provider="ENA",
                                    stage="ena_fastq",
                                    item_id=identifier,
                                    retryable=is_retryable_error(error),
                                ),
                            ))
                            continue
                        outcomes.append(EnrichmentRepairOutcome(
                            stage="ena_fastq",
                            identifier=identifier,
                            package_index=package_index,
                            status="succeeded",
                        ))
                        for run in runs:
                            files = fastqs.get(run.get("run"))
                            if files:
                                run["fastq_files"] = files
                                run["submitted_file_name"] = files[0].get("filename")
                                run["md5"] = files[0].get("md5")
                sample["sra_run"] = runs
        return packages, EnrichmentRepairSummary(
            selected=selected,
            outcomes=tuple(outcomes),
        )

    def _metadata_records_from_packages(self, record: dict, packages: list[dict]) -> list[dict]:
        return self._record_policy.metadata_records_from_packages(record, packages)

    def _records_from_metadata_checkpoint(self, record: dict, checkpoint: dict) -> list[dict]:
        payload = checkpoint.get("payload") or {}
        status = checkpoint.get("status")
        packages = checkpoint_packages(payload)
        if status == "available" and packages:
            records = self._metadata_records_from_packages(record, packages)
            repair_summary = payload.get("repair_summary")
            if (
                isinstance(repair_summary, dict)
                and repair_summary.get("failed_count", 0) > 0
            ):
                for metadata_record in records:
                    metadata_record["metadata_status"] = "partial"
                    metadata_record["metadata_repair_summary"] = repair_summary
            return records
        if status == "no_data":
            return [self._metadata_unavailable_record(record)]
        return [self._metadata_error_record(record)]

    def _gse_metadata_packages(self, gse_accession: str) -> list[dict]:
        logger.debug("GEO geo2json request gse_accession=%s", gse_accession)
        packages = geo2json().convert(
            gse=gse_accession,
            related_series=True,
            remove_empty=True,
            enrich=self._enrich_metadata,
            out=None,
        )
        codec = MINiMLCodec()
        return [codec.encode(codec.decode(package, strict=True).package) for package in packages]

    def _package_gse_accession(self, package: dict) -> str:
        return self._record_policy.package_gse_accession(package)

    def _metadata_record(self, record: dict, package: dict, package_gse: str) -> dict:
        return self._record_policy.metadata_record(record, package, package_gse)

    def _metadata_error_record(self, record: dict) -> dict:
        return self._record_policy.metadata_error_record(record)

    def _metadata_unavailable_record(self, record: dict) -> dict:
        return self._record_policy.metadata_unavailable_record(record)

    def _gse_record(self, record: dict, gse_accession: str) -> dict:
        return self._record_policy.gse_record(record, gse_accession)

    def _deduplicate_gse_jsons(self, jsons: list[dict]) -> list[dict]:
        return self._record_policy.deduplicate_gse_jsons(jsons)

    def _original_datalink_key(self, original_datalink: dict) -> tuple:
        return self._record_policy.original_datalink_key(original_datalink)

    def _publication_key(self, publication: dict) -> tuple:
        return self._record_policy.publication_key(publication)

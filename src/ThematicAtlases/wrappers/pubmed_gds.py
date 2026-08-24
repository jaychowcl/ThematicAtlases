"""Checkpointed PubMed-to-GEO Series discovery through NCBI E-utilities."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from contextlib import contextmanager
import logging
import re
import time

from meta_standards_converter.runtime_contracts import (
    ResourceProfile,
    get_resource_profile,
)

from ThematicAtlases.checkpoint import (
    CheckpointItemLockTimeout,
    failure_category,
    is_retryable_error,
)
from ThematicAtlases.infrastructure import RequestPolicy
from ThematicAtlases.repository_capabilities import RepositoryCapabilityRegistry
from ThematicAtlases.runtime_contracts import safe_error_json
from ThematicAtlases.wrappers.publication_policy import PublicationRecordPolicy


logger = logging.getLogger(__name__)

PUBMED_GDS_DISCOVERY_CONTRACT_VERSION = "1.0"
PUBMED_GDS_LINK_STAGE = "pubmed_gds_links"
GDS_SUMMARY_STAGE = "gds_summaries"
PUBMED_GDS_LINK_NAME = "pubmed_gds"
DEFAULT_LINK_BATCH_SIZE = 100
DEFAULT_SUMMARY_BATCH_SIZE = 200
_PMID = re.compile(r"\d+")


class PubMedGDSLinkGraphWrapper:
    """Resolve exact PubMed→GDS links into production-supported GEO Series."""

    def __init__(
        self,
        *,
        timeout: int | float | tuple[int | float, int | float] | None = None,
        request_delay: float = 0.5,
        max_retries: int = 3,
        request_policy: RequestPolicy | None = None,
        resource_profile: str | ResourceProfile = "standard",
        resource_overrides=None,
        capability_registry: RepositoryCapabilityRegistry | None = None,
        link_batch_size: int = DEFAULT_LINK_BATCH_SIZE,
        summary_batch_size: int = DEFAULT_SUMMARY_BATCH_SIZE,
    ) -> None:
        if request_delay < 0:
            raise ValueError("request_delay must not be negative")
        if link_batch_size < 1 or link_batch_size > 200:
            raise ValueError("link_batch_size must be between 1 and 200")
        if summary_batch_size < 1 or summary_batch_size > 200:
            raise ValueError("summary_batch_size must be between 1 and 200")
        self.resource_profile = (
            resource_profile.with_overrides(resource_overrides)
            if isinstance(resource_profile, ResourceProfile) and resource_overrides
            else resource_profile
            if isinstance(resource_profile, ResourceProfile)
            else get_resource_profile(resource_profile, overrides=resource_overrides)
        )
        effective_timeout = timeout or (
            self.resource_profile.connect_timeout_seconds,
            self.resource_profile.read_timeout_seconds,
        )
        self._base_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
        self._request_delay = float(request_delay)
        self._request_policy = request_policy or RequestPolicy(
            timeout=effective_timeout,
            max_retries=max_retries,
            retry_statuses={403, 429, 500, 502, 503, 504},
            sleep=time.sleep,
            logger=logger,
            name="NCBI PubMed-GDS link graph",
            resource_profile=self.resource_profile,
        )
        self._capabilities = capability_registry or RepositoryCapabilityRegistry()
        self._link_batch_size = link_batch_size
        self._summary_batch_size = summary_batch_size
        self._publication_policy = PublicationRecordPolicy()

    def discover(
        self,
        publications: list[dict],
        *,
        checkpoint_store=None,
        cached_only: bool = False,
        continue_predicate=None,
    ) -> list[dict]:
        """Return ordered, deduplicated GSE records linked to exact PMIDs."""

        publication_map: dict[str, list[dict]] = defaultdict(list)
        ordered_pmids: list[str] = []
        for publication in publications:
            pmid = self._normalized_pmid(publication.get("pmid"))
            if pmid is None:
                continue
            if pmid not in publication_map:
                ordered_pmids.append(pmid)
            if publication not in publication_map[pmid]:
                publication_map[pmid].append(publication)

        links_by_pmid: dict[str, list[str]] = {}
        pmid_ordinals = {
            pmid: ordinal for ordinal, pmid in enumerate(ordered_pmids, start=1)
        }
        missing_pmids = []
        for pmid in ordered_pmids:
            checkpoint = self._completed_checkpoint(
                checkpoint_store, PUBMED_GDS_LINK_STAGE, pmid
            )
            if checkpoint is None:
                if not cached_only:
                    missing_pmids.append(pmid)
                continue
            links_by_pmid[pmid] = list(
                (checkpoint.get("payload") or {}).get("target_uids", [])
            )

        for batch in self._batches(missing_pmids, self._link_batch_size):
            if continue_predicate is not None and not continue_predicate():
                break
            claimed = list(batch)
            try:
                with self._locked_missing_batch(
                    checkpoint_store,
                    PUBMED_GDS_LINK_STAGE,
                    batch,
                ) as claimed:
                    if not claimed:
                        continue
                    if continue_predicate is not None and not continue_predicate():
                        continue
                    result = self._elink(
                        claimed,
                        checkpoint_store=checkpoint_store,
                    )
                    for pmid in claimed:
                        target_uids = result[pmid]
                        links_by_pmid[pmid] = target_uids
                        self._put(
                            checkpoint_store,
                            PUBMED_GDS_LINK_STAGE,
                            pmid,
                            pmid_ordinals[pmid],
                            "available" if target_uids else "no_data",
                            payload={
                                "contract_version": PUBMED_GDS_DISCOVERY_CONTRACT_VERSION,
                                "target_uids": target_uids,
                            },
                        )
            except CheckpointItemLockTimeout:
                logger.info(
                    "NCBI PubMed-GDS link batch deferred for busy checkpoint items pmids=%s",
                    len(batch),
                )
                continue
            except Exception as error:
                self._checkpoint_batch_failure(
                    checkpoint_store,
                    stage=PUBMED_GDS_LINK_STAGE,
                    keys=claimed,
                    ordinals=pmid_ordinals,
                    error=error,
                    provider="NCBI E-utilities",
                )
                logger.warning(
                    "NCBI PubMed-GDS link batch skipped pmids=%s error_type=%s",
                    len(batch),
                    type(error).__name__,
                )
                continue

        ordered_uids = list(dict.fromkeys(
            uid for pmid in ordered_pmids for uid in links_by_pmid.get(pmid, [])
        ))
        summaries: dict[str, dict] = {}
        uid_ordinals = {
            uid: ordinal for ordinal, uid in enumerate(ordered_uids, start=1)
        }
        missing_uids = []
        for uid in ordered_uids:
            checkpoint = self._completed_checkpoint(
                checkpoint_store, GDS_SUMMARY_STAGE, uid
            )
            if checkpoint is None:
                if not cached_only:
                    missing_uids.append(uid)
                continue
            summaries[uid] = dict(checkpoint.get("payload") or {})

        for batch in self._batches(missing_uids, self._summary_batch_size):
            if continue_predicate is not None and not continue_predicate():
                break
            claimed = list(batch)
            try:
                with self._locked_missing_batch(
                    checkpoint_store,
                    GDS_SUMMARY_STAGE,
                    batch,
                ) as claimed:
                    if not claimed:
                        continue
                    if continue_predicate is not None and not continue_predicate():
                        continue
                    result = self._esummary(
                        claimed,
                        checkpoint_store=checkpoint_store,
                    )
                    for uid in claimed:
                        payload = self._summary_payload(uid, result[uid])
                        summaries[uid] = payload
                        self._put(
                            checkpoint_store,
                            GDS_SUMMARY_STAGE,
                            uid,
                            uid_ordinals[uid],
                            "available" if payload["accepted"] else "no_data",
                            payload=payload,
                        )
            except CheckpointItemLockTimeout:
                logger.info(
                    "NCBI GDS summary batch deferred for busy checkpoint items uids=%s",
                    len(batch),
                )
                continue
            except Exception as error:
                self._checkpoint_batch_failure(
                    checkpoint_store,
                    stage=GDS_SUMMARY_STAGE,
                    keys=claimed,
                    ordinals=uid_ordinals,
                    error=error,
                    provider="NCBI E-utilities",
                )
                logger.warning(
                    "NCBI GDS summary batch skipped uids=%s error_type=%s",
                    len(batch),
                    type(error).__name__,
                )
                continue

        records = []
        for pmid in ordered_pmids:
            for uid in links_by_pmid.get(pmid, []):
                summary = summaries.get(uid) or {}
                if not summary.get("accepted"):
                    continue
                accession = summary["accession"]
                provenance = {
                    "provider": "NCBI E-utilities",
                    "origin_database": "pubmed",
                    "origin_id": pmid,
                    "link_name": PUBMED_GDS_LINK_NAME,
                    "target_database": "gds",
                    "target_uid": uid,
                    "accession": accession,
                    "contract_version": PUBMED_GDS_DISCOVERY_CONTRACT_VERSION,
                }
                records.append({
                    "datalink_id": accession,
                    "datalink_id_scheme": "GEO",
                    "datalink_url": (
                        "https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc="
                        f"{accession}"
                    ),
                    "datalink_category": "Functional Genomics Experiments",
                    "accession_repository": "geo",
                    "accession_object_type": "series",
                    "discovery_sources": ["ncbi_pubmed_gds"],
                    "link_graph_provenance": [provenance],
                    "publications": [{
                        **publication,
                        "accession_discovery_sources": ["ncbi_pubmed_gds"],
                        "link_graph_provenance": [provenance],
                    } for publication in publication_map[pmid]],
                })

        result = self._publication_policy.merge_accessions([], records)
        logger.info(
            "NCBI PubMed-GDS discovery stats publications=%s linked_uids=%s gse_records=%s",
            len(ordered_pmids),
            len(ordered_uids),
            len(result),
        )
        return result

    def _elink(self, pmids: list[str], *, checkpoint_store=None) -> dict[str, list[str]]:
        parameters = [
            ("dbfrom", "pubmed"),
            ("db", "gds"),
            ("linkname", PUBMED_GDS_LINK_NAME),
            ("retmode", "json"),
            *(("id", pmid) for pmid in pmids),
        ]
        self._wait_for_provider_slot(checkpoint_store)
        response = self._request_policy.get(
            f"{self._base_url}/elink.fcgi",
            params=parameters,
            retry_exceptions=True,
        )
        payload = self._response_json(response)
        self._request_policy.wait(self._request_delay)
        linksets = payload.get("linksets") if isinstance(payload, dict) else None
        if not isinstance(linksets, list):
            raise ValueError("NCBI ELink response omitted linksets")
        result: dict[str, list[str]] = {}
        requested = set(pmids)
        for linkset in linksets:
            ids = linkset.get("ids") if isinstance(linkset, dict) else None
            if not isinstance(ids, list) or len(ids) != 1:
                raise ValueError("NCBI ELink response did not preserve one-to-one IDs")
            pmid = str(ids[0])
            if pmid not in requested or pmid in result:
                raise ValueError("NCBI ELink response contained an unexpected PMID")
            links = []
            for linksetdb in linkset.get("linksetdbs", []) or []:
                if not isinstance(linksetdb, dict):
                    raise ValueError("NCBI ELink response contained an invalid link set")
                if (
                    linksetdb.get("dbto") != "gds"
                    or linksetdb.get("linkname") != PUBMED_GDS_LINK_NAME
                ):
                    continue
                raw_links = linksetdb.get("links", [])
                if not isinstance(raw_links, list):
                    raise ValueError("NCBI ELink GDS links must be a list")
                for uid in raw_links:
                    normalized = str(uid).strip()
                    if not normalized.isdigit():
                        raise ValueError("NCBI ELink returned a non-numeric GDS UID")
                    if normalized not in links:
                        links.append(normalized)
            result[pmid] = links
        if set(result) != requested:
            raise ValueError("NCBI ELink response omitted a requested PMID")
        return result

    def _esummary(self, uids: list[str], *, checkpoint_store=None) -> dict[str, dict]:
        self._wait_for_provider_slot(checkpoint_store)
        response = self._request_policy.get(
            f"{self._base_url}/esummary.fcgi",
            params={"db": "gds", "id": ",".join(uids), "retmode": "json"},
            retry_exceptions=True,
        )
        payload = self._response_json(response)
        self._request_policy.wait(self._request_delay)
        result_payload = payload.get("result") if isinstance(payload, dict) else None
        returned_uids = result_payload.get("uids") if isinstance(result_payload, dict) else None
        if not isinstance(returned_uids, list):
            raise ValueError("NCBI GDS ESummary response omitted UIDs")
        normalized_returned = [str(uid).strip() for uid in returned_uids]
        if set(normalized_returned) != set(uids):
            raise ValueError("NCBI GDS ESummary response did not match requested UIDs")
        result = {}
        for uid in uids:
            record = result_payload.get(uid)
            if not isinstance(record, dict) or str(record.get("uid", "")).strip() != uid:
                raise ValueError("NCBI GDS ESummary response omitted a requested record")
            result[uid] = record
        return result

    def _summary_payload(self, uid: str, record: dict) -> dict:
        accession = str(record.get("accession") or "").strip().upper()
        entrytype = str(record.get("entrytype") or "").strip().upper()
        accepted = (
            entrytype == "GSE"
            and re.fullmatch(r"GSE\d+", accession) is not None
            and self._capabilities.review_identity(accession) == accession
        )
        if accepted:
            rejection_reason = None
        elif entrytype != "GSE":
            rejection_reason = "non_gse_entrytype"
        elif re.fullmatch(r"GSE\d+", accession) is None:
            rejection_reason = "invalid_gse_accession"
        else:
            rejection_reason = "unsupported_repository_identity"
        return {
            "contract_version": PUBMED_GDS_DISCOVERY_CONTRACT_VERSION,
            "uid": uid,
            "accession": accession,
            "entrytype": entrytype,
            "accepted": accepted,
            **({"rejection_reason": rejection_reason} if rejection_reason else {}),
        }

    def _completed_checkpoint(self, store, stage: str, key: str) -> dict | None:
        if store is None:
            return None
        checkpoint = store.get(stage, key)
        payload = (checkpoint or {}).get("payload") or {}
        if (
            checkpoint
            and checkpoint["status"] in {
                "available",
                "no_data",
                "terminal_error",
            }
            and payload.get("contract_version")
            == PUBMED_GDS_DISCOVERY_CONTRACT_VERSION
        ):
            return checkpoint
        return None

    def _checkpoint_batch_failure(
        self,
        store,
        *,
        stage: str,
        keys: list[str],
        ordinals: dict[str, int],
        error: Exception,
        provider: str,
    ) -> None:
        for key in keys:
            self._put(
                store,
                stage,
                key,
                ordinals[key],
                "retryable_error" if is_retryable_error(error) else "terminal_error",
                payload={
                    "contract_version": PUBMED_GDS_DISCOVERY_CONTRACT_VERSION,
                },
                error=safe_error_json(
                    error,
                    provider=provider,
                    stage=stage,
                    item_id=key,
                    retryable=is_retryable_error(error),
                ),
                error_type=type(error).__name__,
                failure_category=failure_category(error),
            )

    def _wait_for_provider_slot(self, checkpoint_store) -> None:
        if checkpoint_store is not None:
            checkpoint_store.wait_for_provider_slot(
                "ncbi_eutils",
                min_interval_seconds=self._request_delay,
            )

    @contextmanager
    def _locked_missing_batch(self, store, stage: str, keys: list[str]):
        if store is None:
            yield keys
            return
        with store.item_locks(stage, keys):
            yield [
                key
                for key in keys
                if self._completed_checkpoint(store, stage, key) is None
            ]

    @staticmethod
    def _response_json(response):
        try:
            return response.json()
        finally:
            close = getattr(response, "close", None)
            if callable(close):
                close()

    @staticmethod
    def _put(store, stage, key, ordinal, status, **kwargs) -> None:
        if store is not None:
            store.put(stage, key, ordinal, status, **kwargs)

    @staticmethod
    def _normalized_pmid(value) -> str | None:
        normalized = str(value or "").strip()
        return normalized if _PMID.fullmatch(normalized) else None

    @staticmethod
    def _batches(values: list[str], size: int) -> Iterable[list[str]]:
        for offset in range(0, len(values), size):
            yield values[offset : offset + size]


__all__ = [
    "GDS_SUMMARY_STAGE",
    "PUBMED_GDS_DISCOVERY_CONTRACT_VERSION",
    "PUBMED_GDS_LINK_STAGE",
    "PubMedGDSLinkGraphWrapper",
]

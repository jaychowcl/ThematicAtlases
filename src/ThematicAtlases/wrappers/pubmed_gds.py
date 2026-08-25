"""Checkpointed PubMed-to-GEO Series discovery through NCBI E-utilities."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from contextlib import contextmanager
from http.client import IncompleteRead
import logging
import re
import time

import requests
from meta_standards_converter.helpers.request_helper import NCBIApplicationIdentity
from urllib3.exceptions import ProtocolError

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
_LEGACY_TRANSPORT_ERROR_TYPES = frozenset(
    {
        "chunkedencodingerror",
        "contentdecodingerror",
        "incompleteread",
        "protocolerror",
        "connectionerror",
        "connecttimeout",
        "readtimeout",
        "timeout",
    }
)


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
        api_key: str | None = None,
        tool: str = "ThematicAtlases",
        email: str | None = None,
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
        self._recommended_link_batch_size = link_batch_size
        self._recommended_summary_batch_size = summary_batch_size
        self._publication_policy = PublicationRecordPolicy()
        identity_options = {"tool": tool, "email": email}
        if api_key is not None:
            identity_options["api_key"] = api_key
        self._ncbi_identity = NCBIApplicationIdentity(**identity_options)

    def discover(
        self,
        publications: list[dict],
        *,
        checkpoint_store=None,
        cached_only: bool = False,
        continue_predicate=None,
    ) -> list[dict]:
        """Return ordered, deduplicated GSE records linked to exact PMIDs."""

        self._load_recommended_batch_sizes(checkpoint_store)
        self._link_split_available = True
        self._summary_split_available = True

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

        for batch in self._batches(
            missing_pmids, self._recommended_link_batch_size
        ):
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
                    self._resolve_link_batch(
                        claimed,
                        checkpoint_store=checkpoint_store,
                        ordinals=pmid_ordinals,
                        links_by_pmid=links_by_pmid,
                    )
            except CheckpointItemLockTimeout:
                logger.info(
                    "NCBI PubMed-GDS link batch deferred for busy checkpoint items pmids=%s",
                    len(batch),
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

        for batch in self._batches(
            missing_uids, self._recommended_summary_batch_size
        ):
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
                    self._resolve_summary_batch(
                        claimed,
                        checkpoint_store=checkpoint_store,
                        ordinals=uid_ordinals,
                        summaries=summaries,
                    )
            except CheckpointItemLockTimeout:
                logger.info(
                    "NCBI GDS summary batch deferred for busy checkpoint items uids=%s",
                    len(batch),
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
            *self._ncbi_identity.params().items(),
        ]
        response = self._request_policy.get(
            f"{self._base_url}/elink.fcgi",
            params=parameters,
            retry_exceptions=True,
        )
        payload = self._response_json(response)
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
        response = self._request_policy.get(
            f"{self._base_url}/esummary.fcgi",
            params={
                "db": "gds",
                "id": ",".join(uids),
                "retmode": "json",
                **self._ncbi_identity.params(),
            },
            retry_exceptions=True,
        )
        payload = self._response_json(response)
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
        legacy_transport_terminal = bool(
            checkpoint
            and checkpoint.get("status") == "terminal_error"
            and str(checkpoint.get("error_type") or "").casefold()
            in _LEGACY_TRANSPORT_ERROR_TYPES
        )
        if (
            checkpoint
            and checkpoint["status"] in {
                "available",
                "no_data",
                "terminal_error",
            }
            and payload.get("contract_version")
            == PUBMED_GDS_DISCOVERY_CONTRACT_VERSION
            and not legacy_transport_terminal
        ):
            return checkpoint
        return None

    def _resolve_link_batch(
        self,
        keys: list[str],
        *,
        checkpoint_store,
        ordinals: dict[str, int],
        links_by_pmid: dict[str, list[str]],
    ) -> None:
        try:
            result = self._elink(keys, checkpoint_store=checkpoint_store)
        except Exception as error:
            contract_failure = self._split_contract_failure(error)
            if (
                len(keys) > 1
                and contract_failure
                and self._link_split_available
            ):
                self._link_split_available = False
                midpoint = len(keys) // 2
                self._recommended_link_batch_size = min(
                    self._recommended_link_batch_size,
                    max(1, midpoint),
                )
                self._store_recommended_batch_size(
                    checkpoint_store,
                    "link",
                    self._recommended_link_batch_size,
                )
                self._resolve_link_batch(
                    keys[:midpoint],
                    checkpoint_store=checkpoint_store,
                    ordinals=ordinals,
                    links_by_pmid=links_by_pmid,
                )
                self._resolve_link_batch(
                    keys[midpoint:],
                    checkpoint_store=checkpoint_store,
                    ordinals=ordinals,
                    links_by_pmid=links_by_pmid,
                )
                return
            self._checkpoint_batch_failure(
                checkpoint_store,
                stage=PUBMED_GDS_LINK_STAGE,
                keys=keys,
                ordinals=ordinals,
                error=error,
                provider="NCBI E-utilities",
                recommended_batch_size=self._recommended_link_batch_size,
                force_retryable=contract_failure and len(keys) > 1,
            )
            logger.warning(
                "NCBI PubMed-GDS link batch skipped pmids=%s error_type=%s",
                len(keys),
                type(error).__name__,
            )
            return
        for pmid in keys:
            target_uids = result[pmid]
            links_by_pmid[pmid] = target_uids
            self._put(
                checkpoint_store,
                PUBMED_GDS_LINK_STAGE,
                pmid,
                ordinals[pmid],
                "available" if target_uids else "no_data",
                payload={
                    "contract_version": PUBMED_GDS_DISCOVERY_CONTRACT_VERSION,
                    "target_uids": target_uids,
                },
            )

    def _resolve_summary_batch(
        self,
        keys: list[str],
        *,
        checkpoint_store,
        ordinals: dict[str, int],
        summaries: dict[str, dict],
    ) -> None:
        try:
            result = self._esummary(keys, checkpoint_store=checkpoint_store)
        except Exception as error:
            contract_failure = self._split_contract_failure(error)
            if (
                len(keys) > 1
                and contract_failure
                and self._summary_split_available
            ):
                self._summary_split_available = False
                midpoint = len(keys) // 2
                self._recommended_summary_batch_size = min(
                    self._recommended_summary_batch_size,
                    max(1, midpoint),
                )
                self._store_recommended_batch_size(
                    checkpoint_store,
                    "summary",
                    self._recommended_summary_batch_size,
                )
                self._resolve_summary_batch(
                    keys[:midpoint],
                    checkpoint_store=checkpoint_store,
                    ordinals=ordinals,
                    summaries=summaries,
                )
                self._resolve_summary_batch(
                    keys[midpoint:],
                    checkpoint_store=checkpoint_store,
                    ordinals=ordinals,
                    summaries=summaries,
                )
                return
            self._checkpoint_batch_failure(
                checkpoint_store,
                stage=GDS_SUMMARY_STAGE,
                keys=keys,
                ordinals=ordinals,
                error=error,
                provider="NCBI E-utilities",
                recommended_batch_size=self._recommended_summary_batch_size,
                force_retryable=contract_failure and len(keys) > 1,
            )
            logger.warning(
                "NCBI GDS summary batch skipped uids=%s error_type=%s",
                len(keys),
                type(error).__name__,
            )
            return
        for uid in keys:
            payload = self._summary_payload(uid, result[uid])
            summaries[uid] = payload
            self._put(
                checkpoint_store,
                GDS_SUMMARY_STAGE,
                uid,
                ordinals[uid],
                "available" if payload["accepted"] else "no_data",
                payload=payload,
            )

    @staticmethod
    def _split_contract_failure(error: Exception) -> bool:
        return isinstance(
            error,
            (
                ValueError,
                IncompleteRead,
                ProtocolError,
                requests.exceptions.ChunkedEncodingError,
                requests.exceptions.ContentDecodingError,
            ),
        )

    def _checkpoint_batch_failure(
        self,
        store,
        *,
        stage: str,
        keys: list[str],
        ordinals: dict[str, int],
        error: Exception,
        provider: str,
        recommended_batch_size: int | None = None,
        force_retryable: bool = False,
    ) -> None:
        retryable = force_retryable or is_retryable_error(error)
        for key in keys:
            self._put(
                store,
                stage,
                key,
                ordinals[key],
                "retryable_error" if retryable else "terminal_error",
                payload={
                    "contract_version": PUBMED_GDS_DISCOVERY_CONTRACT_VERSION,
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
                    **(
                        {"recommended_batch_size": recommended_batch_size}
                        if recommended_batch_size is not None
                        else {}
                    ),
                },
                error=safe_error_json(
                    error,
                    provider=provider,
                    stage=stage,
                    item_id=key,
                    retryable=retryable,
                ),
                error_type=type(error).__name__,
                failure_category=(
                    "provider_retryable"
                    if retryable
                    else failure_category(error)
                ),
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

    def _load_recommended_batch_sizes(self, store) -> None:
        if store is None:
            return
        for kind, attribute in (
            ("link", "_recommended_link_batch_size"),
            ("summary", "_recommended_summary_batch_size"),
        ):
            value = store.get_meta(f"pubmed_gds_recommended_{kind}_batch_size")
            if isinstance(value, int) and value > 0:
                setattr(self, attribute, min(getattr(self, attribute), value))

    @staticmethod
    def _store_recommended_batch_size(store, kind: str, size: int) -> None:
        if store is not None:
            store.set_meta(
                f"pubmed_gds_recommended_{kind}_batch_size",
                int(size),
            )

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

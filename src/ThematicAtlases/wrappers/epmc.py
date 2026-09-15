from ThematicAtlases.stages.discovery import DiscoveryStage, DiscoveryRequest
import logging
import hashlib
import time
import xml.etree.ElementTree as ET
from urllib.parse import urlparse

import requests
from meta_standards_converter.helpers.request_helper import (
    HostRequestCooldownDeferred,
)
from meta_standards_converter.runtime_contracts import ResourceProfile, get_resource_profile
from meta_standards_converter.xml_safety import parse_xml

from ThematicAtlases.checkpoint import (
    CheckpointItemLockTimeout,
    failure_category,
    is_retryable_error,
)
from ThematicAtlases.infrastructure import RequestPolicy
from ThematicAtlases.runtime_contracts import safe_error_json
from ThematicAtlases.wrappers.publication_policy import PublicationRecordPolicy
from ThematicAtlases.wrappers.pubmed_gds import PubMedGDSLinkGraphWrapper
from ThematicAtlases.pipeline import AtlasStagePause, DISCOVERY_STOP_STAGES
from ThematicAtlases.accession_extraction import (
    extract_accessions_from_links,
    extract_accessions_from_text,
)

logger = logging.getLogger(__name__)

# Downstream parsers depend on this exact sentinel format in publication text.
SECTION_DELIMITER_TEMPLATE = "<<<THEMATIC_ATLASES_SECTION:title={title}>>>"

DATASET_DATALINK_CATEGORIES = {
    "GEO",
    "BioProject",
    "BioStudies",
    "Nucleotide Sequences",
    "BioStudies: supplemental material and supporting data",
    "Functional Genomics Experiments",
}

PREPRINT_API_URL = "https://api.biorxiv.org/details/{server}/{doi}/na/json"
PREPRINT_DOI_PREFIXES = ("10.1101/", "10.64898/")
PREPRINT_JATS_HOSTS = frozenset({"www.biorxiv.org", "www.medrxiv.org"})
PUBLICATION_TEXT_CONTRACT_VERSION = 3
FULLTEXT_ACCESSION_CONTRACT_VERSION = 2


def _periodic_progress(position: int, total: int) -> bool:
    return position == 1 or position == total or position % 10 == 0


class EuropePMCWrapper:
    def __init__(
        self,
        page_limit: int = 5,
        page_size: int = 1000,
        timeout: int | float | tuple[int | float, int | float] | None = None,
        request_delay: float = 0.5,
        max_retries: int = 3,
        request_policy: RequestPolicy | None = None,
        resource_profile: str | ResourceProfile = "standard",
        resource_overrides=None,
        publication_policy: PublicationRecordPolicy | None = None,
        link_graph_provider=None,
        ncbi_api_key: str | None = None,
        ncbi_tool: str = "ThematicAtlases",
        ncbi_email: str | None = None,
    ):
        if request_delay < 0:
            raise ValueError("request_delay must not be negative")
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
        self._request_settings = {
            "page_limit": page_limit,
            "page_size": page_size,
            "timeout": effective_timeout,
            "request_delay": request_delay,
            "max_retries": max_retries,
        }
        self._search_url = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
        self._datalinks_url = (
            "https://www.ebi.ac.uk/europepmc/webservices/rest/{source}/{epmc_id}/datalinks"
        )
        self._full_text_xml_url = (
            "https://www.ebi.ac.uk/europepmc/webservices/rest/{epmc_id}/fullTextXML"
        )
        self._retry_statuses = {403, 429, 500, 502, 503, 504}
        self._request_policy = request_policy or RequestPolicy(
            timeout=effective_timeout,
            max_retries=max_retries,
            retry_statuses=self._retry_statuses,
            sleep=time.sleep,
            logger=logger,
            name="EuropePMC",
            resource_profile=self.resource_profile,
        )
        self._publication_policy = publication_policy or PublicationRecordPolicy()
        self._link_graph_provider = link_graph_provider or PubMedGDSLinkGraphWrapper(
            timeout=effective_timeout,
            request_delay=request_delay,
            max_retries=max_retries,
            resource_profile=self.resource_profile,
            api_key=ncbi_api_key,
            tool=ncbi_tool,
            email=ncbi_email,
        )

    def collect_accessions(
        self,
        queries: list[str],
        max_publications: int | None = None,
        max_publications_per_query: list[int | None] | None = None,
        checkpoint_store=None,
        scrape_fulltext_accessions: bool = True,
        stop_after: str | None = None,
    ) -> list[dict]:
        return DiscoveryStage(self).run(DiscoveryRequest(
            queries=queries,
            max_publications=max_publications,
            max_publications_per_query=max_publications_per_query,
            checkpoint_store=checkpoint_store,
            scrape_fulltext_accessions=scrape_fulltext_accessions,
            stop_after=stop_after,
        )).records

    @staticmethod
    def _set_pipeline_stage(checkpoint_store, stage: str, state: str) -> None:
        if checkpoint_store is not None:
            checkpoint_store.set_meta(
                "main_pipeline_stage",
                {"stage": stage, "state": state, "contract_version": "1.0"},
            )

    def accessions_from_fulltexts(
        self,
        publications: list[dict],
        checkpoint_store=None,
    ) -> list[dict]:
        """Extract accession-shaped records from available full text."""

        records = []
        repository_counts: dict[str, int] = {}
        for index, publication in enumerate(publications, start=1):
            source = str(publication.get("source", ""))
            epmc_id = str(publication.get("epmc_id", ""))
            checkpoint_key = f"{source}:{epmc_id}"
            if checkpoint_store is not None:
                try:
                    with checkpoint_store.item_lock(
                        "fulltext_accession_discovery",
                        checkpoint_key,
                    ):
                        checkpoint = checkpoint_store.get(
                            "fulltext_accession_discovery",
                            checkpoint_key,
                        )
                        checkpoint_payload = (checkpoint or {}).get("payload") or {}
                        if checkpoint and checkpoint_payload.get(
                            "contract_version"
                        ) == FULLTEXT_ACCESSION_CONTRACT_VERSION and checkpoint[
                            "status"
                        ] in {"available", "no_data", "terminal_error"}:
                            records.extend(checkpoint_payload.get("records", []))
                            continue
                        item_records = self.accessions_from_fulltexts(
                            [publication],
                            checkpoint_store=None,
                        )
                        checkpoint_store.put(
                            "fulltext_accession_discovery",
                            checkpoint_key,
                            index,
                            "available" if item_records else "no_data",
                            payload={
                                "contract_version": FULLTEXT_ACCESSION_CONTRACT_VERSION,
                                "records": item_records,
                            },
                        )
                        records.extend(item_records)
                    continue
                except CheckpointItemLockTimeout:
                    logger.info(
                        "Europe PMC fulltext accession discovery deferred for busy item source=%r epmc_id=%r",
                        source,
                        epmc_id,
                    )
                    continue
            checkpoint = (
                checkpoint_store.get(
                    "fulltext_accession_discovery",
                    checkpoint_key,
                )
                if checkpoint_store is not None
                else None
            )
            checkpoint_payload = (checkpoint or {}).get("payload") or {}
            if checkpoint and checkpoint_payload.get(
                "contract_version"
            ) == FULLTEXT_ACCESSION_CONTRACT_VERSION and checkpoint["status"] in {
                "available",
                "no_data",
                "terminal_error",
            }:
                records.extend(checkpoint_payload.get("records", []))
                continue

            matches = []
            text_source = str(publication.get("text_source", ""))
            discovery_source = None
            if publication.get("full_text_status") == "available" and text_source in {
                "fullTextXML",
                "preprintJATSXML",
            }:
                discovery_source = "fulltext_regex"
            elif text_source == "abstractText":
                discovery_source = "abstract_regex"
            if discovery_source:
                matches = extract_accessions_from_text(
                    str(publication.get("text", ""))
                )
                link_matches = extract_accessions_from_links(
                    publication.get("full_text_links", []) or []
                )
                seen_matches = {match["accession"].upper() for match in matches}
                matches.extend(
                    match
                    for match in link_matches
                    if match["accession"].upper() not in seen_matches
                )
            publication_records = [
                {
                    "datalink_id": match["accession"],
                    "datalink_id_scheme": match["datalink_id_scheme"],
                    "datalink_url": match.get("datalink_url", ""),
                    "datalink_category": match["datalink_category"],
                    "accession_repository": match["repository"],
                    "accession_object_type": match["object_type"],
                    "discovery_sources": [discovery_source],
                    "publications": [
                        {
                            **publication,
                            "accession_discovery_sources": [discovery_source],
                        }
                    ],
                }
                for match in matches
            ]
            for match in matches:
                repository = match["repository"]
                repository_counts[repository] = (
                    repository_counts.get(repository, 0) + 1
                )
            records.extend(publication_records)
            if checkpoint_store is not None:
                checkpoint_store.put(
                    "fulltext_accession_discovery",
                    checkpoint_key,
                    index,
                    "available" if publication_records else "no_data",
                    payload={
                        "contract_version": FULLTEXT_ACCESSION_CONTRACT_VERSION,
                        "records": publication_records,
                    },
                )
        logger.info(
            "EuropePMC fulltext accession stats publications_checked=%s "
            "accessions_discovered=%s repositories=%s",
            len(publications),
            len(records),
            ",".join(
                f"{repository}:{count}"
                for repository, count in sorted(repository_counts.items())
            ),
        )
        return records

    def merge_accessions(
        self,
        datalink_accessions: list[dict],
        scraped_accessions: list[dict],
        link_graph_accessions: list[dict] | None = None,
    ) -> list[dict]:
        """Merge all publication discovery sources without losing provenance."""
        if link_graph_accessions is None:
            return self._publication_policy.merge_accessions(
                datalink_accessions,
                scraped_accessions,
            )
        return self._publication_policy.merge_accessions(
            datalink_accessions,
            scraped_accessions,
            link_graph_accessions,
        )

    def accessions_from_link_graph(
        self,
        publications: list[dict],
        *,
        checkpoint_store=None,
        cached_only: bool = False,
        continue_predicate=None,
    ) -> list[dict]:
        """Resolve exact PubMed→GDS links through the injected NCBI provider."""

        options = {
            "checkpoint_store": checkpoint_store,
            "cached_only": cached_only,
        }
        if continue_predicate is not None:
            options["continue_predicate"] = continue_predicate
        return self._link_graph_provider.discover(publications, **options)

    def _merge_accession_publications(
        self,
        current: dict,
        incoming: dict,
    ) -> None:
        self._publication_policy.merge_accession_publications(current, incoming)

    def _accessions_with_enriched_publications(
        self,
        accessions: list[dict],
        publications: list[dict],
    ) -> list[dict]:
        return self._publication_policy.accessions_with_enriched_publications(
            accessions,
            publications,
        )

    @staticmethod
    def _ordered_unique(values: list[str]) -> list[str]:
        return PublicationRecordPolicy.ordered_unique(values)

    def collect_publications(
        self,
        queries: list[str],
        max_publications: int | None = None,
        max_publications_per_query: list[int | None] | None = None,
        checkpoint_store=None,
    ) -> list[dict]:
        max_publications = self._normalized_max_publications(
            max_publications=max_publications
        )
        query_limits = self._normalized_query_limits(
            queries=queries,
            max_publications_per_query=max_publications_per_query,
        )
        publications = []
        raw_publication_count = 0

        for query_index, query in enumerate(queries):
            if (
                max_publications is not None
                and raw_publication_count >= max_publications
            ):
                break

            query_limit = query_limits[query_index]
            page_limit = self._request_settings["page_limit"]
            if query_limit is not None:
                required_pages = (
                    query_limit + self._request_settings["page_size"] - 1
                ) // self._request_settings["page_size"]
                page_limit = max(page_limit, required_pages)

            cursor = "*"
            page = 0
            total_hits = None
            collected_hits = 0
            page_limit_reached = False

            query_hash = hashlib.sha256(query.encode("utf-8")).hexdigest()
            if checkpoint_store is not None:
                query_checkpoint = checkpoint_store.get(
                    "search_queries", query_hash
                )
                if query_checkpoint and query_checkpoint["status"] == "terminal_error":
                    raise RuntimeError(
                        query_checkpoint.get("error") or "Europe PMC search failed"
                    )
                saved_pages = [
                    item
                    for item in checkpoint_store.items("search_pages")
                    if item["key"].startswith(f"{query_hash}:")
                    and item["status"] == "available"
                ]
                for item in saved_pages:
                    payload = item["payload"] or {}
                    page_publications = list(payload.get("publications", []))
                    remaining = self._remaining_publications(
                        query_limit=query_limit,
                        query_collected=collected_hits,
                        global_limit=max_publications,
                        global_collected=raw_publication_count,
                    )
                    publications.extend(page_publications[:remaining])
                    added = min(
                        len(page_publications),
                        len(page_publications) if remaining is None else remaining,
                    )
                    collected_hits += added
                    raw_publication_count += added
                    page += 1
                    total_hits = payload.get("total_hits", total_hits)
                    cursor = payload.get("next_cursor")
                    if self._limit_reached(
                        query_limit,
                        collected_hits,
                        max_publications,
                        raw_publication_count,
                    ):
                        break

                if saved_pages and (
                    cursor is None
                    or self._limit_reached(
                        query_limit,
                        collected_hits,
                        max_publications,
                        raw_publication_count,
                    )
                    or page >= page_limit
                ):
                    logger.info(
                        "EuropePMC search checkpoint reused query=%r pages=%s publications=%s",
                        query,
                        page,
                        collected_hits,
                    )
                    checkpoint_store.put(
                        "search_queries",
                        query_hash,
                        query_index,
                        "available" if collected_hits else "no_data",
                        payload={
                            "query": query,
                            "pages": page,
                            "next_cursor": cursor,
                            "collected_hits": collected_hits,
                        },
                    )
                    continue

            while cursor is not None and page < page_limit:
                logger.debug(
                    "EuropePMC search request query=%r cursor=%r page=%s",
                    query,
                    cursor,
                    page + 1,
                )
                if checkpoint_store is not None:
                    checkpoint_store.put(
                        "search_queries",
                        query_hash,
                        query_index,
                        "pending",
                        payload={
                            "query": query,
                            "pages": page,
                            "next_cursor": cursor,
                            "collected_hits": collected_hits,
                        },
                    )
                try:
                    response_data = self._search(query=query, cursor=cursor)
                except Exception as error:
                    if checkpoint_store is not None:
                        checkpoint_store.put(
                            "search_queries",
                            query_hash,
                            query_index,
                            "retryable_error"
                            if is_retryable_error(error)
                            else "terminal_error",
                            payload={
                                "query": query,
                                "pages": page,
                                "next_cursor": cursor,
                                "collected_hits": collected_hits,
                            },
                            error=safe_error_json(
                                error,
                                provider="Europe PMC",
                                stage="search_queries",
                                item_id=query_hash,
                                retryable=is_retryable_error(error),
                            ),
                            error_type=type(error).__name__,
                            failure_category=failure_category(error),
                        )
                    raise
                hits = response_data.get("resultList", {}).get("result", [])

                if total_hits is None:
                    total_hits = response_data.get("hitCount")

                page += 1

                if not hits:
                    break

                remaining_publications = self._remaining_publications(
                    query_limit=query_limit,
                    query_collected=collected_hits,
                    global_limit=max_publications,
                    global_collected=raw_publication_count,
                )
                page_hits = hits[:remaining_publications]

                for hit in page_hits:
                    publications.append(self._publication_from_hit(query=query, hit=hit))

                page_publications = [
                    self._publication_from_hit(query=query, hit=hit)
                    for hit in page_hits
                ]

                collected_hits += len(page_hits)
                raw_publication_count += len(page_hits)
                next_cursor = response_data.get("nextCursorMark")

                if checkpoint_store is not None:
                    checkpoint_store.put(
                        "search_pages",
                        f"{query_hash}:{page:06d}",
                        query_index * 1_000_000 + page,
                        "available",
                        payload={
                            "query": query,
                            "publications": page_publications,
                            "total_hits": total_hits,
                            "next_cursor": next_cursor,
                        },
                    )

                if self._limit_reached(
                    query_limit,
                    collected_hits,
                    max_publications,
                    raw_publication_count,
                ):
                    break

                if next_cursor == cursor:
                    break

                cursor = next_cursor

                if cursor is not None and page >= page_limit:
                    page_limit_reached = True
                elif cursor is not None:
                    time.sleep(self._request_settings["request_delay"])

            logger.info(
                "EuropePMC search stats query=%r total_hits=%s collected_hits=%s pages_fetched=%s page_limit=%s page_limit_reached=%s final_cursor=%r",
                query,
                total_hits,
                collected_hits,
                page,
                page_limit,
                page_limit_reached,
                cursor,
            )
            if checkpoint_store is not None:
                checkpoint_store.put(
                    "search_queries",
                    query_hash,
                    query_index,
                    "available" if collected_hits else "no_data",
                    payload={
                        "query": query,
                        "pages": page,
                        "next_cursor": cursor,
                        "collected_hits": collected_hits,
                    },
                )

        deduplicated = self._deduplicate_publications(
            publications,
            include_query_list=len(queries) > 1,
        )
        logger.info(
            "EuropePMC publication deduplication stats raw=%s unique=%s duplicates=%s queries=%s",
            len(publications),
            len(deduplicated),
            len(publications) - len(deduplicated),
            len(queries),
        )
        return deduplicated

    def _normalized_max_publications(
        self,
        max_publications: int | None,
    ) -> int | None:
        return self._publication_policy.normalized_max_publications(max_publications)

    def _normalized_query_limits(
        self,
        queries: list[str],
        max_publications_per_query: list[int | None] | None,
    ) -> list[int | None]:
        return self._publication_policy.normalized_query_limits(
            queries,
            max_publications_per_query,
        )

    @staticmethod
    def _remaining_publications(
        *,
        query_limit: int | None,
        query_collected: int,
        global_limit: int | None,
        global_collected: int,
    ) -> int | None:
        return PublicationRecordPolicy.remaining_publications(
            query_limit=query_limit,
            query_collected=query_collected,
            global_limit=global_limit,
            global_collected=global_collected,
        )

    @staticmethod
    def _limit_reached(
        query_limit: int | None,
        query_collected: int,
        global_limit: int | None,
        global_collected: int,
    ) -> bool:
        return PublicationRecordPolicy.limit_reached(
            query_limit,
            query_collected,
            global_limit,
            global_collected,
        )

    def _deduplicate_publications(
        self,
        publications: list[dict],
        *,
        include_query_list: bool,
    ) -> list[dict]:
        return self._publication_policy.deduplicate_publications(
            publications,
            include_query_list=include_query_list,
        )

    @staticmethod
    def _publication_identity_keys(publication: dict) -> list[tuple[str, str]]:
        return PublicationRecordPolicy.publication_identity_keys(publication)

    def publication_text_sections(self, text: str) -> list[dict]:
        normalized_text = self._normalize_text(text)

        if not normalized_text:
            return []

        delimiter_prefix = "<<<THEMATIC_ATLASES_SECTION:title="
        delimiter_suffix = ">>>"

        if delimiter_prefix not in normalized_text:
            return [{"title": "Text", "text": normalized_text}]

        sections = []
        chunks = normalized_text.split(delimiter_prefix)

        for chunk in chunks:
            if delimiter_suffix not in chunk:
                continue

            title, section_text = chunk.split(delimiter_suffix, 1)
            title = self._section_title(title=title, fallback="Text")
            section_text = self._normalize_text(section_text)

            if section_text:
                sections.append({"title": title, "text": section_text})

        return sections

    def collect_publication_texts(
        self,
        publications: list[dict],
        checkpoint_store=None,
    ) -> list[dict]:
        enriched_publications = []
        full_text_available = 0
        abstract_fallbacks = 0
        missing_text = 0

        locked_publications = self._publication_text_items(
            publications,
            checkpoint_store=checkpoint_store,
        )
        for index, publication in enumerate(locked_publications, start=1):
            source = str(publication.get("source", ""))
            epmc_id = str(publication.get("epmc_id", ""))
            checkpoint_key = f"{source}:{epmc_id}"
            checkpoint = (
                checkpoint_store.get("publication_text", checkpoint_key)
                if checkpoint_store is not None
                else None
            )
            checkpoint_payload = (checkpoint or {}).get("payload") or {}
            if checkpoint and checkpoint_payload.get(
                "contract_version"
            ) == PUBLICATION_TEXT_CONTRACT_VERSION and checkpoint["status"] in {
                "available",
                "no_data",
                "terminal_error",
            }:
                enriched_publication = checkpoint_payload.get(
                    "publication", publication
                )
                enriched_publications.append(enriched_publication)
                continue

            if _periodic_progress(index, len(publications)):
                logger.info(
                    "EuropePMC publication text progress publication_index=%s publication_total=%s",
                    index,
                    len(publications),
                )
            full_text_id = self._full_text_id(publication=publication)
            checkpoint_status = "available"
            checkpoint_error = None
            checkpoint_retry_at = None

            try:
                if full_text_id:
                    logger.debug(
                        "EuropePMC fullTextXML request epmc_id=%r",
                        full_text_id,
                    )
                    full_text_xml = self._full_text_xml(epmc_id=full_text_id)
                    text, links = self._text_and_links_from_xml(full_text_xml)
                    enriched_publication = {
                        **publication,
                        "text": text,
                        "full_text_links": links,
                        "text_source": "fullTextXML",
                        "full_text_status": "available",
                    }
                else:
                    preprint_text = self._preprint_full_text(publication)
                    enriched_publication = (
                        preprint_text
                        if preprint_text is not None
                        else self._publication_with_fallback_text(
                            publication=publication,
                            full_text_status="missing_pmcid",
                        )
                    )
            except requests.HTTPError as error:
                response = error.response
                status_code = response.status_code if response is not None else None
                full_text_status = "unavailable" if status_code == 404 else "error"
                enriched_publication = self._publication_with_fallback_text(
                    publication=publication,
                    full_text_status=full_text_status,
                )
                retryable = is_retryable_error(error)
                checkpoint_status = (
                    "retryable_error" if retryable else "terminal_error"
                )
                checkpoint_error = safe_error_json(
                    error,
                    provider="Europe PMC",
                    stage="publication_text",
                    item_id=checkpoint_key,
                    retryable=retryable,
                )
                if retryable:
                    checkpoint_retry_at = getattr(
                        response,
                        "_thematic_atlases_retry_at",
                        None,
                    )
            except (requests.RequestException, HostRequestCooldownDeferred) as error:
                enriched_publication = self._publication_with_fallback_text(
                    publication=publication,
                    full_text_status="error",
                )
                checkpoint_status = "retryable_error"
                checkpoint_error = safe_error_json(
                    error,
                    provider="Europe PMC",
                    stage="publication_text",
                    item_id=checkpoint_key,
                    retryable=True,
                )
                checkpoint_retry_at = getattr(error, "retry_at", None)
            except (ET.ParseError, ValueError) as error:
                enriched_publication = self._publication_with_fallback_text(
                    publication=publication,
                    full_text_status="error",
                )
                checkpoint_status = "terminal_error"
                checkpoint_error = safe_error_json(
                    error,
                    provider="Europe PMC",
                    stage="publication_text",
                    item_id=checkpoint_key,
                    retryable=False,
                )

            if enriched_publication["full_text_status"] == "available":
                full_text_available += 1
            elif enriched_publication["text_source"] == "abstractText":
                abstract_fallbacks += 1
            else:
                missing_text += 1

            enriched_publications.append(enriched_publication)
            if checkpoint_store is not None:
                if checkpoint_status == "available" and not enriched_publication.get(
                    "text"
                ):
                    checkpoint_status = "no_data"
                checkpoint_store.put(
                    "publication_text",
                    checkpoint_key,
                    index,
                    checkpoint_status,
                    payload={
                        "contract_version": PUBLICATION_TEXT_CONTRACT_VERSION,
                        "publication": enriched_publication,
                        **(
                            {"next_retry_at": checkpoint_retry_at}
                            if checkpoint_retry_at is not None
                            else {}
                        ),
                    },
                    error=checkpoint_error,
                    error_type=("HTTPError" if checkpoint_error is not None else None),
                    failure_category=(
                        "public_full_text_unavailable"
                        if enriched_publication["full_text_status"] == "unavailable"
                        else None
                    ),
                )
            time.sleep(self._request_settings["request_delay"])

        logger.info(
            "EuropePMC publication text stats publications_checked=%s full_text_available=%s abstract_fallbacks=%s missing_text=%s",
            len(publications),
            full_text_available,
            abstract_fallbacks,
            missing_text,
        )

        return enriched_publications

    @staticmethod
    def _publication_text_items(publications, *, checkpoint_store):
        """Yield each publication while holding its cross-process item lock."""

        for publication in publications:
            if checkpoint_store is None:
                yield publication
                continue
            source = str(publication.get("source", ""))
            epmc_id = str(publication.get("epmc_id", ""))
            try:
                with checkpoint_store.item_lock(
                    "publication_text",
                    f"{source}:{epmc_id}",
                ):
                    yield publication
            except CheckpointItemLockTimeout:
                logger.info(
                    "Europe PMC publication text deferred for busy item source=%r epmc_id=%r",
                    source,
                    epmc_id,
                )

    def collect_datalinks(
        self,
        publications: list[dict],
        checkpoint_store=None,
    ) -> list[dict]:
        datalinks = []
        failed_publications = 0
        skipped_categories = 0

        for index, publication in enumerate(publications, start=1):
            source = publication.get("source", "")
            epmc_id = publication.get("epmc_id", "")

            if not source or not epmc_id:
                continue

            checkpoint_key = f"{source}:{epmc_id}"
            checkpoint = (
                checkpoint_store.get("datalinks", checkpoint_key)
                if checkpoint_store is not None
                else None
            )
            if checkpoint and checkpoint["status"] in {"available", "no_data"}:
                datalinks.extend((checkpoint.get("payload") or {}).get("rows", []))
                continue

            if _periodic_progress(index, len(publications)):
                logger.info(
                    "EuropePMC datalink progress publication_index=%s publication_total=%s",
                    index,
                    len(publications),
                )

            logger.debug(
                "EuropePMC datalinks request source=%r epmc_id=%r",
                source,
                epmc_id,
            )
            started = time.monotonic()
            try:
                response_data = self._datalinks(source=source, epmc_id=epmc_id)
            except Exception as error:
                failed_publications += 1
                if checkpoint_store is not None:
                    checkpoint_store.put(
                        "datalinks",
                        checkpoint_key,
                        index,
                        "retryable_error"
                        if is_retryable_error(error)
                        else "terminal_error",
                        payload={
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
                            )
                        },
                        error=safe_error_json(
                            error,
                            provider="Europe PMC",
                            stage="datalinks",
                            item_id=checkpoint_key,
                            retryable=is_retryable_error(error),
                        ),
                        error_type=type(error).__name__,
                        failure_category=failure_category(error),
                    )
                logger.warning(
                    "EuropePMC datalinks skipped publication source=%r epmc_id=%r error_type=%s",
                    source,
                    epmc_id,
                    type(error).__name__,
                )
                continue
            logger.debug(
                "EuropePMC datalinks response source=%r epmc_id=%r categories=%s elapsed_seconds=%.3f",
                source,
                epmc_id,
                len(response_data.get("dataLinkList", {}).get("Category", [])),
                time.monotonic() - started,
            )

            categories = response_data.get("dataLinkList", {}).get("Category", [])

            publication_datalinks = []
            for category in categories:
                category_name = category.get("Name", "")

                if category_name not in DATASET_DATALINK_CATEGORIES:
                    skipped_categories += 1
                    continue

                publication_datalinks.extend(
                    self._datalinks_from_category(
                        publication=publication,
                        category=category,
                    )
                )

            datalinks.extend(publication_datalinks)
            if checkpoint_store is not None:
                checkpoint_store.put(
                    "datalinks",
                    checkpoint_key,
                    index,
                    "available" if publication_datalinks else "no_data",
                    payload={"rows": publication_datalinks},
                )

        logger.info(
            "EuropePMC datalink stats publications_checked=%s datalinks_collected=%s skipped_categories=%s failed_publications=%s",
            len(publications),
            len(datalinks),
            skipped_categories,
            failed_publications,
        )

        return self._deduplicate_accessions(datalinks=datalinks)

    def accessions_from_datalinks(self, datalinks: list[dict]) -> list[dict]:
        """Build deduplicated accession records from normalized datalink rows."""
        accessions = []
        accession_index = {}
        publication_keys = {}
        skipped_rows = 0
        duplicate_rows = 0

        for datalink in datalinks:
            datalink_id = str(datalink.get("datalink_id", "")).strip()

            if not datalink_id:
                skipped_rows += 1
                continue

            accession_key = datalink_id.upper()

            if accession_key not in accession_index:
                accession_index[accession_key] = len(accessions)
                publication_keys[accession_key] = set()
                accessions.append(
                    {
                        "datalink_id": datalink_id,
                        "datalink_id_scheme": datalink.get("datalink_id_scheme", ""),
                        "datalink_url": datalink.get("datalink_url", ""),
                        "datalink_category": datalink.get("datalink_category", ""),
                        "publications": [],
                    }
                )
            else:
                duplicate_rows += 1

            publication = self._publication_from_datalink(datalink=datalink)
            publication_key = self._publication_key(publication=publication)

            if publication_key not in publication_keys[accession_key]:
                publication_keys[accession_key].add(publication_key)
                accessions[accession_index[accession_key]]["publications"].append(
                    publication
                )

        logger.info(
            "EuropePMC accession dedupe stats input_datalinks=%s output_accessions=%s duplicate_rows_collapsed=%s skipped_rows=%s",
            len(datalinks),
            len(accessions),
            duplicate_rows,
            skipped_rows,
        )

        return accessions

    def _deduplicate_accessions(self, datalinks: list[dict]) -> list[dict]:
        """Compatibility wrapper for the former private transformation helper."""
        return self.accessions_from_datalinks(datalinks=datalinks)

    def _search(self, query: str, cursor: str) -> dict:
        params = {
            "query": query,
            "format": "json",
            "resultType": "core",
            "pageSize": self._request_settings["page_size"],
            "cursorMark": cursor,
            "synonym": "TRUE",
        }

        return self._request_policy.get(
            self._search_url,
            params=params,
        ).json()

    def _datalinks(self, source: str, epmc_id: str) -> dict:
        url = self._datalinks_url.format(source=source, epmc_id=epmc_id)
        retry_limit = self._request_policy.max_retries

        for attempt in range(retry_limit + 1):
            failures: list[Exception] = []
            try:
                return self._datalinks_from_xml(url=url)
            except (requests.RequestException, ET.ParseError) as error:
                failures.append(error)
                delay = self._wait_before_datalink_request(
                    url=url,
                    error=error,
                    attempt=attempt,
                )
                logger.debug(
                    "EuropePMC datalinks format fallback format=xml "
                    "next_format=json round=%s/%s delay=%s error_type=%s "
                    "source=%r epmc_id=%r",
                    attempt + 1,
                    retry_limit + 1,
                    delay,
                    type(error).__name__,
                    source,
                    epmc_id,
                )

            try:
                return self._datalinks_from_json(url=url)
            except requests.RequestException as error:
                failures.append(error)
                self._close_error_response(error)
                logger.debug(
                    "EuropePMC datalinks format failure format=json "
                    "round=%s/%s error_type=%s source=%r epmc_id=%r",
                    attempt + 1,
                    retry_limit + 1,
                    type(error).__name__,
                    source,
                    epmc_id,
                )

            retryable_failures = [
                error for error in failures if is_retryable_error(error)
            ]
            selected_error = (
                retryable_failures[-1] if retryable_failures else failures[-1]
            )
            if not retryable_failures or attempt >= retry_limit:
                raise selected_error

            delay = self._wait_before_datalink_request(
                url=url,
                error=selected_error,
                attempt=attempt,
                retry_backoff=True,
            )
            logger.debug(
                "EuropePMC datalinks retry round=%s/%s next_format=xml "
                "delay=%s error_type=%s source=%r epmc_id=%r",
                attempt + 2,
                retry_limit + 1,
                delay,
                type(selected_error).__name__,
                source,
                epmc_id,
            )

        raise RuntimeError("bounded Europe PMC Datalinks retry loop terminated")

    def _datalinks_from_xml(self, url: str) -> dict:
        response = self._request_policy.get(
            url,
            retry_exceptions=True,
            max_retries=0,
        )
        try:
            return self._datalinks_xml_to_json(response.text)
        finally:
            self._close_response(response)

    def _datalinks_from_json(self, url: str) -> dict:
        response = self._request_policy.get(
            url,
            params={"format": "json"},
            retry_exceptions=True,
            max_retries=0,
        )
        try:
            return response.json()
        finally:
            self._close_response(response)

    def _wait_before_datalink_request(
        self,
        *,
        url: str,
        error: Exception,
        attempt: int,
        retry_backoff: bool = False,
    ) -> float:
        response = getattr(error, "response", None)
        delay = 0.0
        status = getattr(response, "status_code", None)
        headers = getattr(response, "headers", {}) or {}
        retry_after = headers.get("Retry-After")
        if retry_backoff or status in {403, 429} or retry_after is not None:
            delay = self._request_policy.defer_retry(
                url,
                response=response,
                attempt=attempt,
            )
        self._close_response(response)
        return delay

    @staticmethod
    def _close_error_response(error: Exception) -> None:
        EuropePMCWrapper._close_response(getattr(error, "response", None))

    @staticmethod
    def _close_response(response) -> None:
        close = getattr(response, "close", None)
        if callable(close):
            close()

    def _datalinks_xml_to_json(self, text: str) -> dict:
        root = parse_xml(text, max_bytes=self.resource_profile.max_xml_bytes)
        categories = []

        for category_element in root.findall(".//{*}Category"):
            sections = []

            for section_element in category_element.findall("{*}Section"):
                links = []

                for link_element in section_element.findall(".//{*}Link"):
                    identifier_element = link_element.find(
                        "{*}Target/{*}Identifier"
                    )

                    if identifier_element is None:
                        continue

                    links.append(
                        {
                            "Target": {
                                "Identifier": {
                                    "ID": self._xml_child_text(
                                        element=identifier_element,
                                        tag="ID",
                                    ),
                                    "IDScheme": self._xml_child_text(
                                        element=identifier_element,
                                        tag="IDScheme",
                                    ),
                                    "IDURL": self._xml_child_text(
                                        element=identifier_element,
                                        tag="IDURL",
                                    ),
                                }
                            }
                        }
                    )

                sections.append({"Linklist": {"Link": links}})

            categories.append(
                {
                    "Name": self._xml_child_text(
                        element=category_element,
                        tag="Name",
                    ),
                    "Section": sections,
                }
            )

        return {"dataLinkList": {"Category": categories}}

    def _xml_child_text(self, element: ET.Element, tag: str) -> str:
        child = element.find(f"{{*}}{tag}")

        if child is None or child.text is None:
            return ""

        return child.text

    def _full_text_xml(self, epmc_id: str) -> str:
        url = self._full_text_xml_url.format(epmc_id=epmc_id)

        return self._request_policy.get(url).text

    def _retry_delay(self, response: requests.Response, attempt: int) -> float:
        return RequestPolicy.retry_delay(response, attempt)

    def _publication_from_hit(self, query: str, hit: dict) -> dict:
        return self._publication_policy.publication_from_hit(query, hit)

    def _full_text_urls(self, hit: dict) -> list[str]:
        return self._publication_policy.full_text_urls(hit)

    def _datalinks_from_category(self, publication: dict, category: dict) -> list[dict]:
        return self._publication_policy.datalinks_from_category(
            publication,
            category,
        )

    def _publication_from_datalink(self, datalink: dict) -> dict:
        return self._publication_policy.publication_from_datalink(datalink)

    def _publication_key(self, publication: dict) -> tuple:
        return self._publication_policy.publication_key(publication)

    def _full_text_id(self, publication: dict) -> str:
        pmcid = str(publication.get("pmcid", "")).strip()
        epmc_id = str(publication.get("epmc_id", "")).strip()

        if pmcid:
            return pmcid

        if epmc_id.upper().startswith("PMC"):
            return epmc_id

        return ""

    def _preprint_full_text(self, publication: dict) -> dict | None:
        source = str(publication.get("source", "")).strip().upper()
        doi = str(publication.get("doi", "")).strip().lower()
        doi = doi.removeprefix("https://doi.org/")
        if source != "PPR" or not doi.startswith(PREPRINT_DOI_PREFIXES):
            return None

        journal = str(publication.get("journalTitle", "")).strip().lower()
        if journal in {"biorxiv", "medrxiv"}:
            servers = [journal]
        else:
            servers = ["biorxiv", "medrxiv"]

        for server in servers:
            api_url = PREPRINT_API_URL.format(server=server, doi=doi)
            logger.debug(
                "Preprint details request server=%r doi=%r",
                server,
                doi,
            )
            response = self._request_policy.get(api_url)
            payload = response.json()
            collection = (
                payload.get("collection", [])
                if isinstance(payload, dict)
                else []
            )
            candidates = [
                item
                for item in collection
                if isinstance(item, dict) and item.get("jatsxml")
            ]
            if not candidates:
                continue
            latest = max(candidates, key=self._preprint_version)
            jats_url = str(latest["jatsxml"]).strip()
            self._validate_preprint_jats_url(jats_url)
            logger.debug(
                "Preprint JATS request server=%r doi=%r version=%r",
                server,
                doi,
                latest.get("version"),
            )
            full_text_xml = self._request_policy.get(jats_url).text
            text, links = self._text_and_links_from_xml(full_text_xml)
            return {
                **publication,
                "text": text,
                "full_text_links": links,
                "text_source": "preprintJATSXML",
                "full_text_status": "available",
            }
        return None

    @staticmethod
    def _preprint_version(item: dict) -> tuple[int, str]:
        value = str(item.get("version", "")).strip()
        try:
            return int(value), value
        except ValueError:
            return -1, value

    @staticmethod
    def _validate_preprint_jats_url(url: str) -> None:
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname not in PREPRINT_JATS_HOSTS:
            raise ValueError("untrusted preprint JATS URL")

    def _plain_text_from_xml(self, full_text_xml: str) -> str:
        return self._text_and_links_from_xml(full_text_xml)[0]

    def _text_and_links_from_xml(self, full_text_xml: str) -> tuple[str, list[str]]:
        root = parse_xml(
            full_text_xml,
            max_bytes=self.resource_profile.max_xml_bytes,
        )
        sections = []
        front = root.find(".//front")

        if front is not None:
            article_title = front.find(".//article-title")
            abstract = front.find(".//abstract")
            sections.extend(
                [
                    self._xml_section(element=article_title, title="Title"),
                    self._xml_section(element=abstract, title="Abstract"),
                ]
            )

        for selector in (".//body//sec", ".//back//sec"):
            for section in root.findall(selector):
                title_element = section.find("title")
                title = self._section_title(
                    title=self._text_from_xml_element(element=title_element),
                    fallback=section.tag,
                )
                sections.append(
                    self._xml_section(
                        element=section,
                        title=title,
                        excluded_children={title_element},
                    )
                )

        sections = [
            section
            for section in sections
            if section is not None and section["text"]
        ]

        if not sections:
            fallback_text = self._text_from_xml_element(element=root)
            sections = [{"title": "Text", "text": fallback_text}] if fallback_text else []

        text = "\n\n".join(
            [
                f"{SECTION_DELIMITER_TEMPLATE.format(title=section['title'])}\n{section['text']}"
                for section in sections
            ]
        )
        links = []
        for element in root.iter():
            for name, value in element.attrib.items():
                if name.rsplit("}", 1)[-1].lower() != "href":
                    continue
                link = str(value or "").strip()
                if link.startswith(("https://", "http://")) and link not in links:
                    links.append(link)
        return text, links

    def _publication_with_fallback_text(
        self,
        publication: dict,
        full_text_status: str,
    ) -> dict:
        abstract_text = publication.get("abstractText") or ""
        return {
            **publication,
            "text": abstract_text,
            "text_source": "abstractText" if abstract_text else "none",
            "full_text_status": full_text_status,
        }

    def _xml_section(
        self,
        element: ET.Element | None,
        title: str,
        excluded_children: set[ET.Element | None] | None = None,
    ) -> dict | None:
        if element is None:
            return None

        text = self._text_from_xml_element(
            element=element,
            excluded_children=excluded_children,
        )

        return {
            "title": self._section_title(title=title, fallback=element.tag),
            "text": text,
        }

    def _text_from_xml_element(
        self,
        element: ET.Element | None,
        excluded_children: set[ET.Element | None] | None = None,
    ) -> str:
        if element is None:
            return ""

        excluded_children = excluded_children or set()
        text_parts = []

        if element.text:
            text_parts.append(element.text)

        for child in element:
            if child not in excluded_children:
                text_parts.append(
                    self._text_from_xml_element(
                        element=child,
                        excluded_children=excluded_children,
                    )
                )

            if child.tail:
                text_parts.append(child.tail)

        return self._normalize_text(" ".join(text_parts))

    def _section_title(self, title: str, fallback: str) -> str:
        title = self._normalize_text(
            str(title or fallback)
            .replace("<<<", "")
            .replace(">>>", "")
        )
        return title or fallback

    def _normalize_text(self, text: str) -> str:
        return " ".join(str(text or "").split())

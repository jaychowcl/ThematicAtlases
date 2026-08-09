"""Pure Europe PMC publication identity, merge, and projection policy."""

from __future__ import annotations


class PublicationRecordPolicy:
    """Normalize and merge publication/accession records without performing I/O."""

    def merge_accessions(
        self,
        datalink_accessions: list[dict],
        scraped_accessions: list[dict],
    ) -> list[dict]:
        merged: list[dict] = []
        indexes: dict[str, int] = {}
        for record, source in (
            *((record, "europe_pmc_datalink") for record in datalink_accessions),
            *((record, None) for record in scraped_accessions),
        ):
            accession = str(record.get("datalink_id", "")).strip()
            if not accession:
                continue
            key = accession.upper()
            record_sources = list(record.get("discovery_sources", []))
            if source:
                record_sources.append(source)
            elif not record_sources:
                record_sources.append("fulltext_regex")
            normalized = {
                **record,
                "discovery_sources": self.ordered_unique(record_sources),
                "publications": [
                    {
                        **publication,
                        "accession_discovery_sources": self.ordered_unique(
                            [
                                *publication.get("accession_discovery_sources", []),
                                *(
                                    [source]
                                    if source
                                    else (
                                        []
                                        if publication.get(
                                            "accession_discovery_sources"
                                        )
                                        else ["fulltext_regex"]
                                    )
                                ),
                            ]
                        ),
                    }
                    for publication in record.get("publications", [])
                ],
            }
            if key not in indexes:
                indexes[key] = len(merged)
                merged.append(normalized)
                continue
            current = merged[indexes[key]]
            current["discovery_sources"] = self.ordered_unique(
                [
                    *current.get("discovery_sources", []),
                    *normalized.get("discovery_sources", []),
                ]
            )
            self.merge_accession_publications(current, normalized)
        return merged

    def merge_accession_publications(self, current: dict, incoming: dict) -> None:
        indexes = {
            self.publication_key(publication): index
            for index, publication in enumerate(current.get("publications", []))
        }
        for publication in incoming.get("publications", []):
            key = self.publication_key(publication)
            if key not in indexes:
                indexes[key] = len(current.setdefault("publications", []))
                current["publications"].append(publication)
                continue
            index = indexes[key]
            existing = current["publications"][index]
            sources = self.ordered_unique(
                [
                    *existing.get("accession_discovery_sources", []),
                    *publication.get("accession_discovery_sources", []),
                ]
            )
            current["publications"][index] = {
                **existing,
                **{
                    name: value
                    for name, value in publication.items()
                    if value
                },
                "accession_discovery_sources": sources,
            }

    def accessions_with_enriched_publications(
        self,
        accessions: list[dict],
        publications: list[dict],
    ) -> list[dict]:
        enriched = {
            self.publication_key(publication): publication
            for publication in publications
        }
        return [
            {
                **record,
                "publications": [
                    {
                        **publication,
                        **enriched.get(self.publication_key(publication), {}),
                    }
                    for publication in record.get("publications", [])
                ],
            }
            for record in accessions
        ]

    @staticmethod
    def ordered_unique(values: list[str]) -> list[str]:
        return list(dict.fromkeys(value for value in values if value))

    @staticmethod
    def normalized_max_publications(max_publications: int | None) -> int | None:
        if max_publications is None:
            return None
        if max_publications < 1:
            raise ValueError("max_publications must be a positive integer")
        return max_publications

    @staticmethod
    def normalized_query_limits(
        queries: list[str],
        max_publications_per_query: list[int | None] | None,
    ) -> list[int | None]:
        if max_publications_per_query is None:
            return [None] * len(queries)
        if len(max_publications_per_query) != len(queries):
            raise ValueError(
                "max_publications_per_query must contain one limit per query"
            )
        if any(
            limit is not None and limit < 1
            for limit in max_publications_per_query
        ):
            raise ValueError(
                "max_publications_per_query limits must be positive integers or None"
            )
        return list(max_publications_per_query)

    @staticmethod
    def remaining_publications(
        *,
        query_limit: int | None,
        query_collected: int,
        global_limit: int | None,
        global_collected: int,
    ) -> int | None:
        remaining = []
        if query_limit is not None:
            remaining.append(max(0, query_limit - query_collected))
        if global_limit is not None:
            remaining.append(max(0, global_limit - global_collected))
        return min(remaining) if remaining else None

    @staticmethod
    def limit_reached(
        query_limit: int | None,
        query_collected: int,
        global_limit: int | None,
        global_collected: int,
    ) -> bool:
        return (
            query_limit is not None and query_collected >= query_limit
        ) or (
            global_limit is not None and global_collected >= global_limit
        )

    def deduplicate_publications(
        self,
        publications: list[dict],
        *,
        include_query_list: bool,
    ) -> list[dict]:
        unique = []
        aliases: dict[tuple[str, str], int] = {}
        for publication in publications:
            keys = self.publication_identity_keys(publication)
            matched = next((aliases[key] for key in keys if key in aliases), None)
            if matched is None:
                merged = dict(publication)
                if include_query_list:
                    merged["queries"] = [publication.get("query")]
                unique.append(merged)
                matched = len(unique) - 1
            else:
                merged = unique[matched]
                for key, value in publication.items():
                    if key != "query" and value and not merged.get(key):
                        merged[key] = value
                if include_query_list:
                    query = publication.get("query")
                    if query and query not in merged["queries"]:
                        merged["queries"].append(query)
            for key in keys:
                aliases[key] = matched
        return unique

    @staticmethod
    def publication_identity_keys(publication: dict) -> list[tuple[str, str]]:
        keys = []
        source = str(publication.get("source") or "").strip().upper()
        epmc_id = str(publication.get("epmc_id") or "").strip().upper()
        if source and epmc_id:
            keys.append(("epmc", f"{source}:{epmc_id}"))
        for field in ("pmid", "pmcid"):
            value = str(publication.get(field) or "").strip().upper()
            if value:
                keys.append((field, value))
        doi = str(publication.get("doi") or "").strip().lower()
        if doi:
            keys.append(("doi", doi.removeprefix("https://doi.org/")))
        return keys

    @staticmethod
    def publication_from_hit(query: str, hit: dict) -> dict:
        return {
            "query": query,
            "epmc_id": hit.get("id", ""),
            "source": hit.get("source", ""),
            "pmid": hit.get("pmid", ""),
            "pmcid": hit.get("pmcid", ""),
            "doi": hit.get("doi", ""),
            "title": hit.get("title", ""),
            "authorString": hit.get("authorString", ""),
            "abstractText": hit.get("abstractText", ""),
            "affiliation": hit.get("affiliation", ""),
            "fullTextUrls": PublicationRecordPolicy.full_text_urls(hit),
            "firstPublicationDate": hit.get("firstPublicationDate", ""),
        }

    @staticmethod
    def full_text_urls(hit: dict) -> list[str]:
        full_text_urls = hit.get("fullTextUrlList", {}).get("fullTextUrl", [])
        return [item.get("url", "") for item in full_text_urls if item.get("url")]

    @staticmethod
    def datalinks_from_category(publication: dict, category: dict) -> list[dict]:
        datalinks = []
        category_name = category.get("Name", "")
        for section in category.get("Section", []):
            for link in section.get("Linklist", {}).get("Link", []):
                identifier = link.get("Target", {}).get("Identifier", {})
                datalink_id = identifier.get("ID", "")
                if not datalink_id:
                    continue
                datalinks.append(
                    {
                        "query": publication.get("query", ""),
                        "epmc_id": publication.get("epmc_id", ""),
                        "source": publication.get("source", ""),
                        "pmid": publication.get("pmid", ""),
                        "pmcid": publication.get("pmcid", ""),
                        "doi": publication.get("doi", ""),
                        "title": publication.get("title", ""),
                        "abstractText": publication.get("abstractText", ""),
                        "text": publication.get("text", ""),
                        "text_source": publication.get("text_source", ""),
                        "full_text_status": publication.get("full_text_status", ""),
                        "datalink_id": datalink_id,
                        "datalink_id_scheme": identifier.get("IDScheme", ""),
                        "datalink_url": identifier.get("IDURL", ""),
                        "datalink_category": category_name,
                    }
                )
        return datalinks

    @staticmethod
    def publication_from_datalink(datalink: dict) -> dict:
        return {
            "query": datalink.get("query", ""),
            "epmc_id": datalink.get("epmc_id", ""),
            "source": datalink.get("source", ""),
            "pmid": datalink.get("pmid", ""),
            "pmcid": datalink.get("pmcid", ""),
            "doi": datalink.get("doi", ""),
            "title": datalink.get("title", ""),
            "abstractText": datalink.get("abstractText", ""),
            "text": datalink.get("text", ""),
            "text_source": datalink.get("text_source", ""),
            "full_text_status": datalink.get("full_text_status", ""),
        }

    @staticmethod
    def publication_key(publication: dict) -> tuple:
        return (
            publication.get("source", ""),
            publication.get("epmc_id", ""),
            publication.get("pmid", ""),
            publication.get("pmcid", ""),
            publication.get("doi", ""),
        )

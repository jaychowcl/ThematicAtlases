import logging
import time
import xml.etree.ElementTree as ET

import requests

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


class EuropePMCWrapper:
    def __init__(
        self,
        page_limit: int = 5,
        page_size: int = 1000,
        timeout: int = 30,
        request_delay: float = 0.1,
        max_retries: int = 3,
    ):
        self._request_settings = {
            "page_limit": page_limit,
            "page_size": page_size,
            "timeout": timeout,
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
        self._retry_statuses = {429, 500, 502, 503, 504}

    def collect_accessions(self, queries: list[str]) -> list[dict]:
        publications = self.collect_publications(queries=queries)
        return self.collect_datalinks(publications=publications)

    def collect_publications(self, queries: list[str]) -> list[dict]:
        publications = []

        for query in queries:
            cursor = "*"
            page = 0
            total_hits = None
            collected_hits = 0
            page_limit_reached = False

            while cursor is not None and page < self._request_settings["page_limit"]:
                logger.debug(
                    "EuropePMC search request query=%r cursor=%r page=%s",
                    query,
                    cursor,
                    page + 1,
                )
                response_data = self._search(query=query, cursor=cursor)
                hits = response_data.get("resultList", {}).get("result", [])

                if total_hits is None:
                    total_hits = response_data.get("hitCount")

                page += 1

                if not hits:
                    break

                for hit in hits:
                    publications.append(self._publication_from_hit(query=query, hit=hit))

                collected_hits += len(hits)
                next_cursor = response_data.get("nextCursorMark")

                if next_cursor == cursor:
                    break

                cursor = next_cursor

                if cursor is not None and page >= self._request_settings["page_limit"]:
                    page_limit_reached = True
                elif cursor is not None:
                    time.sleep(self._request_settings["request_delay"])

            logger.info(
                "EuropePMC search stats query=%r total_hits=%s collected_hits=%s pages_fetched=%s page_limit=%s page_limit_reached=%s final_cursor=%r",
                query,
                total_hits,
                collected_hits,
                page,
                self._request_settings["page_limit"],
                page_limit_reached,
                cursor,
            )

        return publications

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

    def collect_publication_texts(self, publications: list[dict]) -> list[dict]:
        enriched_publications = []
        full_text_available = 0
        abstract_fallbacks = 0
        missing_text = 0

        for publication in publications:
            full_text_id = self._full_text_id(publication=publication)

            if not full_text_id:
                enriched_publication = self._publication_with_fallback_text(
                    publication=publication,
                    full_text_status="missing_pmcid",
                )
            else:
                try:
                    logger.debug(
                        "EuropePMC fullTextXML request epmc_id=%r",
                        full_text_id,
                    )
                    full_text_xml = self._full_text_xml(epmc_id=full_text_id)
                    enriched_publication = {
                        **publication,
                        "text": self._plain_text_from_xml(full_text_xml),
                        "text_source": "fullTextXML",
                        "full_text_status": "available",
                    }
                except requests.HTTPError as error:
                    response = error.response
                    status_code = response.status_code if response is not None else None
                    full_text_status = (
                        "unavailable" if status_code == 404 else "error"
                    )
                    enriched_publication = self._publication_with_fallback_text(
                        publication=publication,
                        full_text_status=full_text_status,
                    )
                except (requests.RequestException, ET.ParseError):
                    enriched_publication = self._publication_with_fallback_text(
                        publication=publication,
                        full_text_status="error",
                    )

            if enriched_publication["full_text_status"] == "available":
                full_text_available += 1
            elif enriched_publication["text_source"] == "abstractText":
                abstract_fallbacks += 1
            else:
                missing_text += 1

            enriched_publications.append(enriched_publication)
            time.sleep(self._request_settings["request_delay"])

        logger.info(
            "EuropePMC publication text stats publications_checked=%s full_text_available=%s abstract_fallbacks=%s missing_text=%s",
            len(publications),
            full_text_available,
            abstract_fallbacks,
            missing_text,
        )

        return enriched_publications

    def collect_datalinks(self, publications: list[dict]) -> list[dict]:
        datalinks = []
        failed_publications = 0
        skipped_categories = 0

        for publication in publications:
            source = publication.get("source", "")
            epmc_id = publication.get("epmc_id", "")

            if not source or not epmc_id:
                continue

            logger.debug(
                "EuropePMC datalinks request source=%r epmc_id=%r",
                source,
                epmc_id,
            )
            try:
                response_data = self._datalinks(source=source, epmc_id=epmc_id)
            except requests.RequestException as error:
                failed_publications += 1
                logger.warning(
                    "EuropePMC datalinks skipped publication source=%r epmc_id=%r error=%r",
                    source,
                    epmc_id,
                    error,
                )
                continue

            categories = response_data.get("dataLinkList", {}).get("Category", [])

            for category in categories:
                category_name = category.get("Name", "")

                if category_name not in DATASET_DATALINK_CATEGORIES:
                    skipped_categories += 1
                    continue

                datalinks.extend(
                    self._datalinks_from_category(
                        publication=publication,
                        category=category,
                    )
                )

            time.sleep(self._request_settings["request_delay"])

        logger.info(
            "EuropePMC datalink stats publications_checked=%s datalinks_collected=%s skipped_categories=%s failed_publications=%s",
            len(publications),
            len(datalinks),
            skipped_categories,
            failed_publications,
        )

        return self._deduplicate_accessions(datalinks=datalinks)

    def _deduplicate_accessions(self, datalinks: list[dict]) -> list[dict]:
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

    def _search(self, query: str, cursor: str) -> dict:
        params = {
            "query": query,
            "format": "json",
            "resultType": "core",
            "pageSize": self._request_settings["page_size"],
            "cursorMark": cursor,
            "synonym": "TRUE",
        }

        for attempt in range(self._request_settings["max_retries"] + 1):
            response = requests.get(
                self._search_url,
                params=params,
                timeout=self._request_settings["timeout"],
            )

            if (
                response.status_code in self._retry_statuses
                and attempt < self._request_settings["max_retries"]
            ):
                retry_delay = self._retry_delay(response=response, attempt=attempt)
                logger.debug(
                    "EuropePMC retry status=%s attempt=%s delay=%s",
                    response.status_code,
                    attempt + 1,
                    retry_delay,
                )
                time.sleep(retry_delay)
                continue

            response.raise_for_status()
            return response.json()

        return {}

    def _datalinks(self, source: str, epmc_id: str) -> dict:
        params = {"format": "json"}
        url = self._datalinks_url.format(source=source, epmc_id=epmc_id)

        for attempt in range(self._request_settings["max_retries"] + 1):
            try:
                response = requests.get(
                    url,
                    params=params,
                    timeout=self._request_settings["timeout"],
                )
            except requests.RequestException as error:
                if attempt < self._request_settings["max_retries"]:
                    retry_delay = min(0.5 * (2 ** attempt), 8.0)
                    logger.debug(
                        "EuropePMC datalinks retry error=%r attempt=%s delay=%s",
                        error,
                        attempt + 1,
                        retry_delay,
                    )
                    time.sleep(retry_delay)
                    continue

                logger.debug(
                    "EuropePMC datalinks XML fallback error=%r source=%r epmc_id=%r",
                    error,
                    source,
                    epmc_id,
                )
                return self._datalinks_from_xml(url=url)

            if (
                response.status_code in self._retry_statuses
                and attempt < self._request_settings["max_retries"]
            ):
                retry_delay = self._retry_delay(response=response, attempt=attempt)
                logger.debug(
                    "EuropePMC datalinks retry status=%s attempt=%s delay=%s",
                    response.status_code,
                    attempt + 1,
                    retry_delay,
                )
                time.sleep(retry_delay)
                continue

            if response.status_code >= 500:
                logger.debug(
                    "EuropePMC datalinks XML fallback status=%s source=%r epmc_id=%r",
                    response.status_code,
                    source,
                    epmc_id,
                )
                return self._datalinks_from_xml(url=url)

            response.raise_for_status()
            return response.json()

        return {}

    def _datalinks_from_xml(self, url: str) -> dict:
        response = requests.get(
            url,
            timeout=self._request_settings["timeout"],
        )
        response.raise_for_status()
        return self._datalinks_xml_to_json(response.text)

    def _datalinks_xml_to_json(self, text: str) -> dict:
        root = ET.fromstring(text)
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

        for attempt in range(self._request_settings["max_retries"] + 1):
            response = requests.get(
                url,
                timeout=self._request_settings["timeout"],
            )

            if (
                response.status_code in self._retry_statuses
                and attempt < self._request_settings["max_retries"]
            ):
                retry_delay = self._retry_delay(response=response, attempt=attempt)
                logger.debug(
                    "EuropePMC fullTextXML retry status=%s attempt=%s delay=%s",
                    response.status_code,
                    attempt + 1,
                    retry_delay,
                )
                time.sleep(retry_delay)
                continue

            response.raise_for_status()
            return response.text

        return ""

    def _retry_delay(self, response: requests.Response, attempt: int) -> float:
        retry_after = response.headers.get("Retry-After")

        if retry_after is not None:
            try:
                return float(retry_after)
            except ValueError:
                pass

        return min(0.5 * (2 ** attempt), 8.0)

    def _publication_from_hit(self, query: str, hit: dict) -> dict:
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
            "fullTextUrls": self._full_text_urls(hit=hit),
            "firstPublicationDate": hit.get("firstPublicationDate", ""),
        }

    def _full_text_urls(self, hit: dict) -> list[str]:
        full_text_urls = hit.get("fullTextUrlList", {}).get("fullTextUrl", [])
        return [item.get("url", "") for item in full_text_urls if item.get("url")]

    def _datalinks_from_category(self, publication: dict, category: dict) -> list[dict]:
        datalinks = []
        category_name = category.get("Name", "")

        for section in category.get("Section", []):
            for link in section.get("Linklist", {}).get("Link", []):
                identifier = link.get("Target", {}).get("Identifier", {})
                datalink_id = identifier.get("ID", "")
                datalink_id_scheme = identifier.get("IDScheme", "")
                datalink_url = identifier.get("IDURL", "")

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
                        "datalink_id_scheme": datalink_id_scheme,
                        "datalink_url": datalink_url,
                        "datalink_category": category_name,
                    }
                )

        return datalinks

    def _publication_from_datalink(self, datalink: dict) -> dict:
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

    def _publication_key(self, publication: dict) -> tuple:
        return (
            publication.get("source", ""),
            publication.get("epmc_id", ""),
            publication.get("pmid", ""),
            publication.get("pmcid", ""),
            publication.get("doi", ""),
        )

    def _full_text_id(self, publication: dict) -> str:
        pmcid = str(publication.get("pmcid", "")).strip()
        epmc_id = str(publication.get("epmc_id", "")).strip()

        if pmcid:
            return pmcid

        if epmc_id.upper().startswith("PMC"):
            return epmc_id

        return ""

    def _plain_text_from_xml(self, full_text_xml: str) -> str:
        root = ET.fromstring(full_text_xml)
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

        for section in root.findall(".//body//sec"):
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

        return "\n\n".join(
            [
                f"{SECTION_DELIMITER_TEMPLATE.format(title=section['title'])}\n{section['text']}"
                for section in sections
            ]
        )

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

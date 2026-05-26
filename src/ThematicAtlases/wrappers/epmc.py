import logging
import time

import requests

logger = logging.getLogger(__name__)


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
        self._retry_statuses = {429, 500, 502, 503, 504}

    def collect_accessions(self, queries: list[str]) -> list[dict]:
        return self.collect_publications(queries=queries)

    def collect_publications(self, queries: list[str]) -> list[dict]:
        publications = []

        for query in queries:
            cursor = "*"
            page = 0
            total_hits = None
            collected_hits = 0
            page_limit_reached = False

            while cursor is not None and page < self._request_settings["page_limit"]:
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
                time.sleep(self._retry_delay(response=response, attempt=attempt))
                continue

            response.raise_for_status()
            return response.json()

        return {}

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

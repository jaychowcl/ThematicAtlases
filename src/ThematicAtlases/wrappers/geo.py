import time

import requests


class GEOWrapper:
    def __init__(
        self,
        api_key: str | None = None,
        tool: str = "ThematicAtlases",
        email: str | None = None,
        timeout: int = 30,
        request_delay: float = 0.34,
        max_retries: int = 3,
    ):
        self._api_key = api_key
        self._tool = tool
        self._email = email
        self._request_settings = {
            "timeout": timeout,
            "request_delay": request_delay,
            "max_retries": max_retries,
        }
        self._base_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
        self._retry_statuses = {429, 500, 502, 503, 504}

    def collect_accession_metadata(self, jsons: list[dict]) -> list[dict]:
        records = []

        for record in jsons:
            gse_accession = self.get_gse(record.get("datalink_id", ""))

            if gse_accession is None:
                continue

            records.append(self._gse_record(record=record, gse_accession=gse_accession))

        return self._deduplicate_gse_jsons(jsons=records)

    def get_gse(self, accession: str) -> str | None:
        accession = self._normalize_accession(accession=accession)

        if not accession:
            return None

        if accession.startswith("GSE"):
            return accession

        if accession.startswith("GPL"):
            return None

        if not accession.startswith(("GDS", "GSM")):
            return None

        uids = self._search(accession=accession)

        if not uids:
            return None

        summaries = self._summary(uids=uids)
        summary = self._matching_summary(accession=accession, summaries=summaries)

        if summary is None:
            return None

        return self._gse_from_summary(summary=summary)

    def _search(self, accession: str) -> list[str]:
        params = self._params(
            {
                "db": "gds",
                "term": f"{accession}[ACCN]",
                "retmode": "json",
                "retmax": 20,
            }
        )
        response = self._get(url=f"{self._base_url}/esearch.fcgi", params=params)
        return response.get("esearchresult", {}).get("idlist", [])

    def _summary(self, uids: list[str]) -> dict:
        params = self._params(
            {
                "db": "gds",
                "id": ",".join(uids),
                "retmode": "json",
            }
        )
        return self._get(url=f"{self._base_url}/esummary.fcgi", params=params)

    def _get(self, url: str, params: dict) -> dict:
        for attempt in range(self._request_settings["max_retries"] + 1):
            response = requests.get(
                url,
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

    def _params(self, params: dict) -> dict:
        params = dict(params)

        if self._tool:
            params["tool"] = self._tool

        if self._email:
            params["email"] = self._email

        if self._api_key:
            params["api_key"] = self._api_key

        return params

    def _retry_delay(self, response: requests.Response, attempt: int) -> float:
        retry_after = response.headers.get("Retry-After")

        if retry_after is not None:
            try:
                return float(retry_after)
            except ValueError:
                pass

        return min(0.5 * (2 ** attempt), 8.0)

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

    def _gse_record(self, record: dict, gse_accession: str) -> dict:
        return {
            **record,
            "datalink_id": gse_accession,
            "original_datalinks": [
                {
                    "datalink_id": record.get("datalink_id", ""),
                    "datalink_id_scheme": record.get("datalink_id_scheme", ""),
                    "datalink_url": record.get("datalink_url", ""),
                    "datalink_category": record.get("datalink_category", ""),
                }
            ],
        }

    def _deduplicate_gse_jsons(self, jsons: list[dict]) -> list[dict]:
        records = []
        record_index = {}
        publication_keys = {}
        original_datalink_keys = {}

        for record in jsons:
            gse_accession = str(record.get("datalink_id", "")).strip().upper()

            if not gse_accession:
                continue

            if gse_accession not in record_index:
                record_index[gse_accession] = len(records)
                publication_keys[gse_accession] = set()
                original_datalink_keys[gse_accession] = set()
                records.append({**record, "publications": [], "original_datalinks": []})

            target_record = records[record_index[gse_accession]]

            for original_datalink in record.get("original_datalinks", []):
                original_datalink_key = self._original_datalink_key(
                    original_datalink=original_datalink
                )

                if original_datalink_key not in original_datalink_keys[gse_accession]:
                    original_datalink_keys[gse_accession].add(original_datalink_key)
                    target_record["original_datalinks"].append(original_datalink)

            for publication in record.get("publications", []):
                publication_key = self._publication_key(publication=publication)

                if publication_key not in publication_keys[gse_accession]:
                    publication_keys[gse_accession].add(publication_key)
                    target_record["publications"].append(publication)

        return records

    def _original_datalink_key(self, original_datalink: dict) -> tuple:
        return (
            original_datalink.get("datalink_id", ""),
            original_datalink.get("datalink_id_scheme", ""),
            original_datalink.get("datalink_url", ""),
            original_datalink.get("datalink_category", ""),
        )

    def _publication_key(self, publication: dict) -> tuple:
        return (
            publication.get("source", ""),
            publication.get("epmc_id", ""),
            publication.get("pmid", ""),
            publication.get("pmcid", ""),
            publication.get("doi", ""),
        )

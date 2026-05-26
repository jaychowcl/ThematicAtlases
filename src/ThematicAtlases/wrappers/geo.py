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

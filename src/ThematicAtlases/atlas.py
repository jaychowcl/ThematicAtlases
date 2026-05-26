import json

from ThematicAtlases.wrappers.epmc import EuropePMCWrapper

GEO_ACCESSION_PREFIXES = ("GSE", "GSM", "GPL", "GDS")


class Atlas():
    def __init__(self, metadata: dict):
        pass

    def _load_queries(self, file: str) -> list[str]:
        with open(file, encoding="utf-8") as handle:
            return [
                line.strip()
                for line in handle
                if line.strip() and not line.strip().startswith("#")
            ]

    def _filter_jsons(self, jsons: list[dict]) -> list[dict]:
        return [
            record
            for record in jsons
            if self._is_geo_accession(record=record)
        ]

    def _is_geo_accession(self, record: dict) -> bool:
        datalink_id_scheme = str(record.get("datalink_id_scheme", "")).upper()
        datalink_id = str(record.get("datalink_id", "")).upper()

        return datalink_id_scheme == "GEO" or datalink_id.startswith(
            GEO_ACCESSION_PREFIXES
        )

    def collect_jsons(
        self,
        query: list[str] | None = None,
        file: str | None = None,
        out: str | None = None,
    ) -> list[dict]:
        queries = list(query or [])

        if file is not None:
            queries.extend(self._load_queries(file))

        result = self._filter_jsons(
            EuropePMCWrapper().collect_accessions(queries=queries)
        )

        if out is not None:
            with open(out, "w", encoding="utf-8") as handle:
                json.dump(result, handle, indent=2)

        return result

    def filter_jsons(self,) -> list[dict]:
        pass

    def harmonize_jsons(self, ) -> list[dict]:
        pass

import json

from ThematicAtlases.wrappers.epmc import EuropePMCWrapper


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

    def collect_jsons(
        self,
        query: list[str] | None = None,
        file: str | None = None,
        out: str | None = None,
    ) -> list[dict]:
        queries = list(query or [])

        if file is not None:
            queries.extend(self._load_queries(file))

        result = EuropePMCWrapper().collect_accessions(queries=queries)

        if out is not None:
            with open(out, "w", encoding="utf-8") as handle:
                json.dump(result, handle, indent=2)

        return result

    def filter_jsons(self,) -> list[dict]:
        pass

    def harmonize_jsons(self, ) -> list[dict]:
        pass

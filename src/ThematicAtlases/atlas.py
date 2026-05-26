import json

from ThematicAtlases.wrappers.epmc import EuropePMCWrapper

DEFAULT_QUERY_FILE = ".dev/queries.txt"


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

        query_file = file
        if not queries and query_file is None:
            query_file = DEFAULT_QUERY_FILE

        if query_file is not None:
            queries.extend(self._load_queries(query_file))

        result = EuropePMCWrapper().collect_accessions(queries=queries)

        if out is not None:
            with open(out, "w", encoding="utf-8") as handle:
                json.dump(result, handle, indent=2)

        return result

    def filter_jsons(self,) -> list[dict]:
        pass

    def harmonize_jsons(self, ) -> list[dict]:
        pass

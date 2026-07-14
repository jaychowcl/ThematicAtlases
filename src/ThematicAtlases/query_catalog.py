from __future__ import annotations

import json
from pathlib import Path


def load_query_catalog(path: str | Path) -> dict:
    """Load and validate an ordered, versioned query catalog."""
    path = Path(path)
    with path.open(encoding="utf-8") as handle:
        catalog = json.load(handle)
    if (
        not isinstance(catalog, dict)
        or catalog.get("schema_version") != "1.0"
        or not isinstance(catalog.get("id"), str)
        or not catalog["id"].strip()
        or not isinstance(catalog.get("queries"), list)
        or not catalog["queries"]
    ):
        raise ValueError(f"invalid query catalog: {path}")
    query_ids = []
    for item in catalog["queries"]:
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("id"), str)
            or not item["id"].strip()
            or not isinstance(item.get("query"), str)
            or not item["query"].strip()
            or not isinstance(item.get("max_publications"), int)
            or isinstance(item.get("max_publications"), bool)
            or item["max_publications"] < 1
        ):
            raise ValueError(f"invalid query catalog entry: {path}")
        query_ids.append(item["id"])
    if len(query_ids) != len(set(query_ids)):
        raise ValueError(f"invalid query catalog duplicate query id: {path}")
    return catalog

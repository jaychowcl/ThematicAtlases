import json

import pytest

from ThematicAtlases.query_catalog import load_query_catalog


def test_load_query_catalog_returns_ordered_queries_and_limits(tmp_path) -> None:
    path = tmp_path / "queries.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "id": "fibrosis",
                "queries": [
                    {"id": "original", "query": "first", "max_publications": 5000},
                    {"id": "expanded", "query": "second", "max_publications": 15000},
                ],
            }
        ),
        encoding="utf-8",
    )

    catalog = load_query_catalog(path)

    assert catalog["id"] == "fibrosis"
    assert [item["query"] for item in catalog["queries"]] == ["first", "second"]
    assert [item["max_publications"] for item in catalog["queries"]] == [
        5000,
        15000,
    ]


@pytest.mark.parametrize(
    "value",
    [
        {},
        {"schema_version": "1.0", "id": "x", "queries": []},
        {
            "schema_version": "1.0",
            "id": "x",
            "queries": [{"id": "q", "query": "", "max_publications": 1}],
        },
        {
            "schema_version": "1.0",
            "id": "x",
            "queries": [
                {"id": "q", "query": "one", "max_publications": 1},
                {"id": "q", "query": "two", "max_publications": 1},
            ],
        },
    ],
)
def test_load_query_catalog_rejects_invalid_catalogs(tmp_path, value) -> None:
    path = tmp_path / "queries.json"
    path.write_text(json.dumps(value), encoding="utf-8")

    with pytest.raises(ValueError, match="query catalog"):
        load_query_catalog(path)

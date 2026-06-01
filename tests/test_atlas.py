import json
import logging

from ThematicAtlases import atlas as atlas_module
from ThematicAtlases.atlas import Atlas


class FakeEuropePMCWrapper:
    queries: list[str] | None = None
    publications: list[dict] | None = None

    def collect_accessions(self, queries: list[str]) -> list[dict]:
        self.__class__.queries = queries
        return [
            {
                "datalink_id": "GSE1",
                "datalink_id_scheme": "GEO",
                "datalink_url": "https://example.org/GSE1",
                "datalink_category": "GEO",
                "publications": [{"source": "MED", "epmc_id": "1"}],
            },
            {"datalink_id": "ERR1", "datalink_id_scheme": "ENA", "publications": []},
        ]

    def collect_publication_texts(self, publications: list[dict]) -> list[dict]:
        self.__class__.publications = publications
        return [
            {
                **publication,
                "text": f"Text {publication.get('epmc_id', '')}",
                "text_source": "abstractText",
                "full_text_status": "missing_pmcid",
            }
            for publication in publications
        ]


class FakeGEOWrapper:
    accessions: list[str] = []
    jsons: list[dict] | None = None
    accessions_to_gse: dict[str, str | None] = {
        "GSE1": "GSE1",
        "GSM1": "GSE1",
        "GDS1": "GSE1",
        "GPL1": None,
    }

    def collect_accession_metadata(self, jsons: list[dict]) -> list[dict]:
        self.__class__.jsons = jsons
        return [
            {
                **record,
                "original_datalinks": [
                    {
                        "datalink_id": record.get("datalink_id", ""),
                        "datalink_id_scheme": record.get("datalink_id_scheme", ""),
                        "datalink_url": record.get("datalink_url", ""),
                        "datalink_category": record.get("datalink_category", ""),
                    }
                ],
            }
            for record in jsons
            if self.get_gse(record.get("datalink_id", "")) is not None
        ]

    def get_gse(self, accession: str) -> str | None:
        self.__class__.accessions.append(accession)
        return self.accessions_to_gse.get(accession)


def test_collect_jsons_passes_queries_to_epmc_wrapper(monkeypatch) -> None:
    monkeypatch.setattr(atlas_module, "EuropePMCWrapper", FakeEuropePMCWrapper)
    monkeypatch.setattr(atlas_module, "GEOWrapper", FakeGEOWrapper)
    FakeGEOWrapper.accessions = []
    FakeGEOWrapper.jsons = None
    FakeEuropePMCWrapper.publications = None

    assert Atlas(metadata={}).collect_jsons(query=["a", "b"]) == [
        {
            "datalink_id": "GSE1",
            "datalink_id_scheme": "GEO",
            "datalink_url": "https://example.org/GSE1",
            "datalink_category": "GEO",
            "publications": [
                {
                    "source": "MED",
                    "epmc_id": "1",
                }
            ],
            "original_datalinks": [
                {
                    "datalink_id": "GSE1",
                    "datalink_id_scheme": "GEO",
                    "datalink_url": "https://example.org/GSE1",
                    "datalink_category": "GEO",
                }
            ],
        }
    ]
    assert FakeEuropePMCWrapper.queries == ["a", "b"]
    assert FakeEuropePMCWrapper.publications is None
    assert FakeGEOWrapper.accessions == ["GSE1"]
    assert FakeGEOWrapper.jsons == [
        {
            "datalink_id": "GSE1",
            "datalink_id_scheme": "GEO",
            "datalink_url": "https://example.org/GSE1",
            "datalink_category": "GEO",
            "publications": [{"source": "MED", "epmc_id": "1"}],
        }
    ]


def test_collect_jsons_combines_query_and_file_lines(monkeypatch, tmp_path) -> None:
    query_file = tmp_path / "queries.txt"
    query_file.write_text(" c \n\n# skip me\n d\n", encoding="utf-8")
    monkeypatch.setattr(atlas_module, "EuropePMCWrapper", FakeEuropePMCWrapper)
    monkeypatch.setattr(atlas_module, "GEOWrapper", FakeGEOWrapper)
    FakeGEOWrapper.accessions = []
    FakeGEOWrapper.jsons = None
    FakeEuropePMCWrapper.publications = None

    Atlas(metadata={}).collect_jsons(query=["a", "b"], file=str(query_file))

    assert FakeEuropePMCWrapper.queries == ["a", "b", "c", "d"]


def test_collect_jsons_passes_empty_queries_without_inputs(monkeypatch) -> None:
    monkeypatch.setattr(atlas_module, "EuropePMCWrapper", FakeEuropePMCWrapper)
    monkeypatch.setattr(atlas_module, "GEOWrapper", FakeGEOWrapper)
    FakeGEOWrapper.accessions = []
    FakeGEOWrapper.jsons = None
    FakeEuropePMCWrapper.publications = None

    Atlas(metadata={}).collect_jsons()

    assert FakeEuropePMCWrapper.queries == []


def test_collect_jsons_writes_result_to_outfile(monkeypatch, tmp_path) -> None:
    outfile = tmp_path / "atlas.json"
    monkeypatch.setattr(atlas_module, "EuropePMCWrapper", FakeEuropePMCWrapper)
    monkeypatch.setattr(atlas_module, "GEOWrapper", FakeGEOWrapper)
    FakeGEOWrapper.accessions = []
    FakeGEOWrapper.jsons = None
    FakeEuropePMCWrapper.publications = None

    Atlas(metadata={}).collect_jsons(query=["a"], out=str(outfile))

    assert outfile.read_text(encoding="utf-8") == '[\n  {\n    "datalink_id": "GSE1",\n    "datalink_id_scheme": "GEO",\n    "datalink_url": "https://example.org/GSE1",\n    "datalink_category": "GEO",\n    "publications": [\n      {\n        "source": "MED",\n        "epmc_id": "1"\n      }\n    ],\n    "original_datalinks": [\n      {\n        "datalink_id": "GSE1",\n        "datalink_id_scheme": "GEO",\n        "datalink_url": "https://example.org/GSE1",\n        "datalink_category": "GEO"\n      }\n    ]\n  }\n]'


def test_create_atlas_collects_then_filters_and_returns_final_object() -> None:
    class RecordingAtlas(Atlas):
        calls: list[tuple[str, object]] = []

        def collect_jsons(self, query=None, file=None, out=None):
            self.calls.append(
                (
                    "collect",
                    {
                        "query": query,
                        "file": file,
                        "out": out,
                    },
                )
            )
            return [{"datalink_id": "GSE1", "publications": []}]

        def filter_jsons(self, jsons=None):
            self.calls.append(("filter", jsons))
            return {
                "accessions": list(jsons or []),
                "publication_texts": {},
            }

    atlas = RecordingAtlas(metadata={})

    assert atlas.create_atlas(query=["a"], file="queries.txt") == {
        "accessions": [{"datalink_id": "GSE1", "publications": []}],
        "publication_texts": {},
    }
    assert atlas.calls == [
        (
            "collect",
            {
                "query": ["a"],
                "file": "queries.txt",
                "out": None,
            },
        ),
        ("filter", [{"datalink_id": "GSE1", "publications": []}]),
    ]


def test_create_atlas_writes_final_filtered_object(tmp_path) -> None:
    class RecordingAtlas(Atlas):
        def collect_jsons(self, query=None, file=None, out=None):
            return [{"datalink_id": "GSE1"}]

        def filter_jsons(self, jsons=None):
            return {
                "accessions": [{"datalink_id": "GSE1", "publication_text_ref": "1"}],
                "publication_texts": {"1": {"text": "full text"}},
            }

    outfile = tmp_path / "atlas.json"

    RecordingAtlas(metadata={}).create_atlas(query=["a"], out=str(outfile))

    assert outfile.read_text(encoding="utf-8") == '{\n  "accessions": [\n    {\n      "datalink_id": "GSE1",\n      "publication_text_ref": "1"\n    }\n  ],\n  "publication_texts": {\n    "1": {\n      "text": "full text"\n    }\n  }\n}'


def test_filter_accessions_keeps_handled_geo_scheme() -> None:
    records = [
        {"datalink_id": "ERR1", "datalink_id_scheme": "GEO"},
        {"datalink_id": "ERR2", "datalink_id_scheme": "ENA"},
    ]

    assert Atlas(metadata={})._filter_accessions(records) == [
        {"datalink_id": "ERR1", "datalink_id_scheme": "GEO"}
    ]


def test_filter_accessions_keeps_handled_geo_prefixes() -> None:
    records = [
        {"datalink_id": "GSE1", "datalink_id_scheme": ""},
        {"datalink_id": "GSM1", "datalink_id_scheme": "URL"},
        {"datalink_id": "GPL1", "datalink_id_scheme": "ArrayExpress"},
        {"datalink_id": "GDS1", "datalink_id_scheme": "BioProject"},
    ]

    assert Atlas(metadata={})._filter_accessions(records) == records


def test_filter_accessions_drops_unhandled_records() -> None:
    records = [
        {"datalink_id": "ERR1", "datalink_id_scheme": "ENA"},
        {"datalink_id": "PRJ1", "datalink_id_scheme": "BioProject"},
        {"datalink_id": "E-MTAB-1", "datalink_id_scheme": "ArrayExpress"},
        {"datalink_id": "https://example.org", "datalink_id_scheme": "URL"},
        {"datalink_id": "ABC1", "datalink_id_scheme": ""},
    ]

    assert Atlas(metadata={})._filter_accessions(records) == []


def test_filter_accessions_is_case_insensitive() -> None:
    records = [
        {"datalink_id": "gse1", "datalink_id_scheme": ""},
        {"datalink_id": "ERR1", "datalink_id_scheme": "geo"},
    ]

    assert Atlas(metadata={})._filter_accessions(records) == records


def test_is_handled_accession_uses_current_geo_rules() -> None:
    assert Atlas(metadata={})._is_handled_accession(
        {"datalink_id": "GSE1", "datalink_id_scheme": ""}
    )
    assert not Atlas(metadata={})._is_handled_accession(
        {"datalink_id": "ERR1", "datalink_id_scheme": "ENA"}
    )


def test_metadata_repository_detects_geo_records() -> None:
    assert (
        Atlas(metadata={})._metadata_repository(
            {
                "datalink_id": "GSE1",
                "datalink_id_scheme": "",
            }
        )
        == "geo"
    )


def test_metadata_repository_returns_none_for_unhandled_records() -> None:
    assert (
        Atlas(metadata={})._metadata_repository(
            {
                "datalink_id": "ERR1",
                "datalink_id_scheme": "ENA",
            }
        )
        is None
    )


def test_collect_accession_metadata_routes_geo_records(monkeypatch) -> None:
    monkeypatch.setattr(atlas_module, "GEOWrapper", FakeGEOWrapper)
    FakeGEOWrapper.accessions = []
    FakeGEOWrapper.jsons = None
    records = [
        {
            "datalink_id": "GSE1",
            "datalink_id_scheme": "GEO",
            "datalink_url": "https://example.org/GSE1",
            "datalink_category": "GEO",
            "publications": [{"source": "MED", "epmc_id": "1"}],
        }
    ]

    assert Atlas(metadata={})._collect_accession_metadata(jsons=records) == [
        {
            "datalink_id": "GSE1",
            "datalink_id_scheme": "GEO",
            "datalink_url": "https://example.org/GSE1",
            "datalink_category": "GEO",
            "publications": [{"source": "MED", "epmc_id": "1"}],
            "original_datalinks": [
                {
                    "datalink_id": "GSE1",
                    "datalink_id_scheme": "GEO",
                    "datalink_url": "https://example.org/GSE1",
                    "datalink_category": "GEO",
                }
            ],
        }
    ]
    assert FakeGEOWrapper.accessions == ["GSE1"]
    assert FakeGEOWrapper.jsons == records


def test_collect_publication_texts_returns_shared_text_map(monkeypatch) -> None:
    monkeypatch.setattr(atlas_module, "EuropePMCWrapper", FakeEuropePMCWrapper)
    FakeEuropePMCWrapper.publications = None
    records = [
        {
            "datalink_id": "GSE1",
            "publications": [
                {
                    "source": "MED",
                    "epmc_id": "1",
                    "pmid": "1",
                    "pmcid": "PMC1",
                    "doi": "10.1/one",
                }
            ],
        },
        {
            "datalink_id": "GSE2",
            "publications": [
                {
                    "source": "MED",
                    "epmc_id": "1",
                    "pmid": "1",
                    "pmcid": "PMC1",
                    "doi": "10.1/one",
                }
            ],
        },
    ]

    result = Atlas(metadata={})._collect_publication_texts(jsons=records)

    assert FakeEuropePMCWrapper.publications == [
        {
            "source": "MED",
            "epmc_id": "1",
            "pmid": "1",
            "pmcid": "PMC1",
            "doi": "10.1/one",
        }
    ]
    assert result == {
        "1": {
            "text": "Text 1",
            "text_source": "abstractText",
            "full_text_status": "missing_pmcid",
        }
    }


def test_collect_publication_texts_skips_empty_publication_lists(monkeypatch) -> None:
    monkeypatch.setattr(atlas_module, "EuropePMCWrapper", FakeEuropePMCWrapper)
    FakeEuropePMCWrapper.publications = None
    records = [{"datalink_id": "GSE1", "publications": []}]

    assert Atlas(metadata={})._collect_publication_texts(jsons=records) == {}
    assert FakeEuropePMCWrapper.publications is None


def test_filter_jsons_returns_accessions_and_publication_texts(monkeypatch) -> None:
    monkeypatch.setattr(atlas_module, "EuropePMCWrapper", FakeEuropePMCWrapper)
    FakeEuropePMCWrapper.publications = None
    records = [
        {
            "datalink_id": "GSE1",
            "publications": [
                {
                    "source": "MED",
                    "epmc_id": "1",
                    "pmid": "1",
                    "pmcid": "PMC1",
                    "doi": "10.1/one",
                }
            ],
        },
        {
            "datalink_id": "GSE2",
            "publications": [
                {
                    "source": "MED",
                    "epmc_id": "1",
                    "pmid": "1",
                    "pmcid": "PMC1",
                    "doi": "10.1/one",
                }
            ],
        },
    ]

    assert Atlas(metadata={}).filter_jsons(jsons=records) == {
        "accessions": [
            {
                "datalink_id": "GSE1",
                "publications": [
                    {
                        "source": "MED",
                        "epmc_id": "1",
                        "pmid": "1",
                        "pmcid": "PMC1",
                        "doi": "10.1/one",
                        "publication_text_ref": "1",
                    }
                ],
            },
            {
                "datalink_id": "GSE2",
                "publications": [
                    {
                        "source": "MED",
                        "epmc_id": "1",
                        "pmid": "1",
                        "pmcid": "PMC1",
                        "doi": "10.1/one",
                        "publication_text_ref": "1",
                    }
                ],
            },
        ],
        "publication_texts": {
            "1": {
                "text": "Text 1",
                "text_source": "abstractText",
                "full_text_status": "missing_pmcid",
            }
        },
    }
    assert FakeEuropePMCWrapper.publications == [
        {
            "source": "MED",
            "epmc_id": "1",
            "pmid": "1",
            "pmcid": "PMC1",
            "doi": "10.1/one",
        }
    ]


def test_publication_text_ref_prefers_pmid_then_fallbacks() -> None:
    atlas = Atlas(metadata={})

    assert atlas._publication_text_ref({"pmid": "1", "pmcid": "PMC1"}) == "1"
    assert atlas._publication_text_ref({"pmcid": "PMC1", "doi": "10.1/one"}) == "PMC1"
    assert atlas._publication_text_ref({"doi": "10.1/one"}) == "10.1/one"
    assert atlas._publication_text_ref({"source": "MED", "epmc_id": "1"}) == "MED:1"


def test_filter_jsons_strips_duplicate_text_from_publications(monkeypatch) -> None:
    monkeypatch.setattr(atlas_module, "EuropePMCWrapper", FakeEuropePMCWrapper)
    records = [
        {
            "datalink_id": "GSE1",
            "publications": [
                {
                    "source": "MED",
                    "epmc_id": "1",
                    "pmid": "1",
                    "text": "Old text",
                    "text_source": "fullTextXML",
                    "full_text_status": "available",
                }
            ],
        }
    ]

    publication = Atlas(metadata={}).filter_jsons(jsons=records)["accessions"][0][
        "publications"
    ][0]

    assert publication == {
        "source": "MED",
        "epmc_id": "1",
        "pmid": "1",
        "publication_text_ref": "1",
    }


def test_filter_jsons_empty_input_returns_empty_shape(monkeypatch) -> None:
    monkeypatch.setattr(atlas_module, "EuropePMCWrapper", FakeEuropePMCWrapper)
    FakeEuropePMCWrapper.publications = None

    assert Atlas(metadata={}).filter_jsons() == {
        "accessions": [],
        "publication_texts": {},
    }
    assert FakeEuropePMCWrapper.publications is None


def test_filter_jsons_reuses_existing_publication_texts_from_file(
    monkeypatch,
    tmp_path,
) -> None:
    class FailingEuropePMCWrapper:
        def collect_publication_texts(self, publications: list[dict]) -> list[dict]:
            raise AssertionError("existing publication text should be reused")

    input_file = tmp_path / "atlas.json"
    input_file.write_text(
        json.dumps(
            {
                "accessions": [
                    {
                        "datalink_id": "GSE1",
                        "publications": [
                            {
                                "source": "MED",
                                "epmc_id": "1",
                                "pmid": "1",
                                "publication_text_ref": "1",
                            }
                        ],
                    }
                ],
                "publication_texts": {
                    "1": {
                        "text": "Existing full text",
                        "text_source": "fullTextXML",
                        "full_text_status": "available",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(atlas_module, "EuropePMCWrapper", FailingEuropePMCWrapper)

    assert Atlas(metadata={}).filter_jsons(file=str(input_file)) == {
        "accessions": [
            {
                "datalink_id": "GSE1",
                "publications": [
                    {
                        "source": "MED",
                        "epmc_id": "1",
                        "pmid": "1",
                        "publication_text_ref": "1",
                    }
                ],
            }
        ],
        "publication_texts": {
            "1": {
                "text": "Existing full text",
                "text_source": "fullTextXML",
                "full_text_status": "available",
            }
        },
    }


def test_filter_jsons_appends_file_accessions_to_jsons(tmp_path) -> None:
    input_file = tmp_path / "collected.json"
    input_file.write_text(
        json.dumps(
            [
                {
                    "datalink_id": "GSE2",
                    "publications": [],
                }
            ]
        ),
        encoding="utf-8",
    )

    assert Atlas(metadata={}).filter_jsons(
        jsons=[
            {
                "datalink_id": "GSE1",
                "publications": [],
            }
        ],
        file=str(input_file),
    ) == {
        "accessions": [
            {
                "datalink_id": "GSE1",
                "publications": [],
            },
            {
                "datalink_id": "GSE2",
                "publications": [],
            },
        ],
        "publication_texts": {},
    }


def test_filter_jsons_fetches_only_missing_publication_texts(
    monkeypatch,
    tmp_path,
) -> None:
    class RecordingEuropePMCWrapper:
        publications: list[dict] | None = None

        def collect_publication_texts(self, publications: list[dict]) -> list[dict]:
            self.__class__.publications = publications
            return [
                {
                    **publication,
                    "text": f"Fetched text {publication.get('pmid', '')}",
                    "text_source": "abstractText",
                    "full_text_status": "missing_pmcid",
                }
                for publication in publications
            ]

    input_file = tmp_path / "atlas.json"
    input_file.write_text(
        json.dumps(
            {
                "accessions": [
                    {
                        "datalink_id": "GSE1",
                        "publications": [
                            {
                                "source": "MED",
                                "epmc_id": "1",
                                "pmid": "1",
                            },
                            {
                                "source": "MED",
                                "epmc_id": "2",
                                "pmid": "2",
                            },
                        ],
                    }
                ],
                "publication_texts": {
                    "1": {
                        "text": "Existing text 1",
                        "text_source": "fullTextXML",
                        "full_text_status": "available",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(atlas_module, "EuropePMCWrapper", RecordingEuropePMCWrapper)

    result = Atlas(metadata={}).filter_jsons(file=str(input_file))

    assert RecordingEuropePMCWrapper.publications == [
        {
            "source": "MED",
            "epmc_id": "2",
            "pmid": "2",
        }
    ]
    assert result["accessions"][0]["publications"] == [
        {
            "source": "MED",
            "epmc_id": "1",
            "pmid": "1",
            "publication_text_ref": "1",
        },
        {
            "source": "MED",
            "epmc_id": "2",
            "pmid": "2",
            "publication_text_ref": "2",
        },
    ]
    assert result["publication_texts"] == {
        "1": {
            "text": "Existing text 1",
            "text_source": "fullTextXML",
            "full_text_status": "available",
        },
        "2": {
            "text": "Fetched text 2",
            "text_source": "abstractText",
            "full_text_status": "missing_pmcid",
        },
    }


def test_filter_jsons_enriches_only_surviving_publications(monkeypatch) -> None:
    class LocalEuropePMCWrapper:
        publications: list[dict] | None = None

        def collect_accessions(self, queries: list[str]) -> list[dict]:
            return [
                {
                    "datalink_id": "GSE1",
                    "datalink_id_scheme": "GEO",
                    "publications": [
                        {
                            "source": "MED",
                            "epmc_id": "1",
                            "abstractText": "Kept abstract",
                        }
                    ],
                },
                {
                    "datalink_id": "ERR1",
                    "datalink_id_scheme": "ENA",
                    "publications": [
                        {
                            "source": "MED",
                            "epmc_id": "2",
                            "abstractText": "Dropped abstract",
                        }
                    ],
                },
                {
                    "datalink_id": "GPL1",
                    "datalink_id_scheme": "GEO",
                    "publications": [
                        {
                            "source": "MED",
                            "epmc_id": "3",
                            "abstractText": "Unresolved abstract",
                        }
                    ],
                },
            ]

        def collect_publication_texts(self, publications: list[dict]) -> list[dict]:
            self.__class__.publications = publications
            return [
                {
                    **publication,
                    "text": publication.get("abstractText", ""),
                    "text_source": "abstractText",
                    "full_text_status": "missing_pmcid",
                }
                for publication in publications
            ]

    monkeypatch.setattr(atlas_module, "EuropePMCWrapper", LocalEuropePMCWrapper)
    monkeypatch.setattr(atlas_module, "GEOWrapper", FakeGEOWrapper)

    jsons = Atlas(metadata={}).collect_jsons(query=["fibrosis"])
    result = Atlas(metadata={}).filter_jsons(jsons=jsons)

    assert LocalEuropePMCWrapper.publications == [
        {"source": "MED", "epmc_id": "1", "abstractText": "Kept abstract"}
    ]
    assert result["accessions"][0]["publications"][0]["publication_text_ref"] == "MED:1"
    assert result["publication_texts"]["MED:1"] == {
        "text": "Kept abstract",
        "text_source": "abstractText",
        "full_text_status": "missing_pmcid",
    }


def test_collect_jsons_logs_progress_and_stats(monkeypatch, caplog) -> None:
    monkeypatch.setattr(atlas_module, "EuropePMCWrapper", FakeEuropePMCWrapper)
    monkeypatch.setattr(atlas_module, "GEOWrapper", FakeGEOWrapper)
    caplog.set_level(logging.INFO, logger=atlas_module.__name__)

    Atlas(metadata={}).collect_jsons(query=["a", "b"])

    assert "stage=query-loading" in caplog.text
    assert "stage=collect-accessions" in caplog.text
    assert "query_count=2" in caplog.text
    assert "raw_accessions=2" in caplog.text
    assert "metadata_records=1" in caplog.text


def test_create_atlas_logs_progress_and_stats(monkeypatch, caplog) -> None:
    monkeypatch.setattr(atlas_module, "EuropePMCWrapper", FakeEuropePMCWrapper)
    monkeypatch.setattr(atlas_module, "GEOWrapper", FakeGEOWrapper)
    caplog.set_level(logging.INFO, logger=atlas_module.__name__)

    Atlas(metadata={}).create_atlas(query=["a"])

    assert "Atlas create_atlas progress stage=collect-jsons" in caplog.text
    assert "Atlas create_atlas progress stage=filter-jsons" in caplog.text
    assert "collected_accessions=1" in caplog.text
    assert "final_accessions=1" in caplog.text
    assert "publication_texts=1" in caplog.text


def test_filter_accessions_logs_stats(caplog) -> None:
    caplog.set_level(logging.INFO, logger=atlas_module.__name__)

    Atlas(metadata={})._filter_accessions(
        [
            {"datalink_id": "GSE1", "datalink_id_scheme": "GEO"},
            {"datalink_id": "ERR1", "datalink_id_scheme": "ENA"},
        ]
    )

    assert "Atlas accession filter stats" in caplog.text
    assert "input_accessions=2" in caplog.text
    assert "output_accessions=1" in caplog.text
    assert "dropped_accessions=1" in caplog.text


def test_collect_accession_metadata_logs_repository_stats(monkeypatch, caplog) -> None:
    monkeypatch.setattr(atlas_module, "GEOWrapper", FakeGEOWrapper)
    caplog.set_level(logging.INFO, logger=atlas_module.__name__)

    Atlas(metadata={})._collect_accession_metadata(
        jsons=[
            {"datalink_id": "GSE1", "datalink_id_scheme": "GEO"},
            {"datalink_id": "ERR1", "datalink_id_scheme": "ENA"},
        ]
    )

    assert "Atlas metadata collection progress repository=geo records=1" in caplog.text
    assert "input_records=2" in caplog.text
    assert "repositories=geo:1" in caplog.text
    assert "skipped_records=1" in caplog.text


def test_filter_jsons_logs_publication_text_stats(monkeypatch, caplog) -> None:
    monkeypatch.setattr(atlas_module, "EuropePMCWrapper", FakeEuropePMCWrapper)
    caplog.set_level(logging.INFO, logger=atlas_module.__name__)

    Atlas(metadata={}).filter_jsons(
        jsons=[
            {
                "datalink_id": "GSE1",
                "publications": [{"source": "MED", "epmc_id": "1", "pmid": "1"}],
            }
        ]
    )

    assert "stage=collect-publication-texts" in caplog.text
    assert "publication_texts=1" in caplog.text
    assert "accessions_with_text_refs=1" in caplog.text

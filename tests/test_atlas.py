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
    accessions_to_gse: dict[str, str | None] = {
        "GSE1": "GSE1",
        "GSM1": "GSE1",
        "GDS1": "GSE1",
        "GPL1": None,
    }

    def get_gse(self, accession: str) -> str | None:
        self.__class__.accessions.append(accession)
        return self.accessions_to_gse.get(accession)


def test_collect_jsons_passes_queries_to_epmc_wrapper(monkeypatch) -> None:
    monkeypatch.setattr(atlas_module, "EuropePMCWrapper", FakeEuropePMCWrapper)
    monkeypatch.setattr(atlas_module, "GEOWrapper", FakeGEOWrapper)
    FakeGEOWrapper.accessions = []
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
                    "text": "Text 1",
                    "text_source": "abstractText",
                    "full_text_status": "missing_pmcid",
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
    assert FakeEuropePMCWrapper.publications == [{"source": "MED", "epmc_id": "1"}]
    assert FakeGEOWrapper.accessions == ["GSE1"]


def test_collect_jsons_combines_query_and_file_lines(monkeypatch, tmp_path) -> None:
    query_file = tmp_path / "queries.txt"
    query_file.write_text(" c \n\n# skip me\n d\n", encoding="utf-8")
    monkeypatch.setattr(atlas_module, "EuropePMCWrapper", FakeEuropePMCWrapper)
    monkeypatch.setattr(atlas_module, "GEOWrapper", FakeGEOWrapper)
    FakeGEOWrapper.accessions = []
    FakeEuropePMCWrapper.publications = None

    Atlas(metadata={}).collect_jsons(query=["a", "b"], file=str(query_file))

    assert FakeEuropePMCWrapper.queries == ["a", "b", "c", "d"]


def test_collect_jsons_passes_empty_queries_without_inputs(monkeypatch) -> None:
    monkeypatch.setattr(atlas_module, "EuropePMCWrapper", FakeEuropePMCWrapper)
    monkeypatch.setattr(atlas_module, "GEOWrapper", FakeGEOWrapper)
    FakeGEOWrapper.accessions = []
    FakeEuropePMCWrapper.publications = None

    Atlas(metadata={}).collect_jsons()

    assert FakeEuropePMCWrapper.queries == []


def test_collect_jsons_writes_result_to_outfile(monkeypatch, tmp_path) -> None:
    outfile = tmp_path / "atlas.json"
    monkeypatch.setattr(atlas_module, "EuropePMCWrapper", FakeEuropePMCWrapper)
    monkeypatch.setattr(atlas_module, "GEOWrapper", FakeGEOWrapper)
    FakeGEOWrapper.accessions = []
    FakeEuropePMCWrapper.publications = None

    Atlas(metadata={}).collect_jsons(query=["a"], out=str(outfile))

    assert outfile.read_text(encoding="utf-8") == '[\n  {\n    "datalink_id": "GSE1",\n    "datalink_id_scheme": "GEO",\n    "datalink_url": "https://example.org/GSE1",\n    "datalink_category": "GEO",\n    "publications": [\n      {\n        "source": "MED",\n        "epmc_id": "1",\n        "text": "Text 1",\n        "text_source": "abstractText",\n        "full_text_status": "missing_pmcid"\n      }\n    ],\n    "original_datalinks": [\n      {\n        "datalink_id": "GSE1",\n        "datalink_id_scheme": "GEO",\n        "datalink_url": "https://example.org/GSE1",\n        "datalink_category": "GEO"\n      }\n    ]\n  }\n]'


def test_filter_jsons_keeps_geo_scheme() -> None:
    records = [
        {"datalink_id": "ERR1", "datalink_id_scheme": "GEO"},
        {"datalink_id": "ERR2", "datalink_id_scheme": "ENA"},
    ]

    assert Atlas(metadata={})._filter_jsons(records) == [
        {"datalink_id": "ERR1", "datalink_id_scheme": "GEO"}
    ]


def test_filter_jsons_keeps_geo_prefixes() -> None:
    records = [
        {"datalink_id": "GSE1", "datalink_id_scheme": ""},
        {"datalink_id": "GSM1", "datalink_id_scheme": "URL"},
        {"datalink_id": "GPL1", "datalink_id_scheme": "ArrayExpress"},
        {"datalink_id": "GDS1", "datalink_id_scheme": "BioProject"},
    ]

    assert Atlas(metadata={})._filter_jsons(records) == records


def test_filter_jsons_drops_non_geo_records() -> None:
    records = [
        {"datalink_id": "ERR1", "datalink_id_scheme": "ENA"},
        {"datalink_id": "PRJ1", "datalink_id_scheme": "BioProject"},
        {"datalink_id": "E-MTAB-1", "datalink_id_scheme": "ArrayExpress"},
        {"datalink_id": "https://example.org", "datalink_id_scheme": "URL"},
        {"datalink_id": "ABC1", "datalink_id_scheme": ""},
    ]

    assert Atlas(metadata={})._filter_jsons(records) == []


def test_filter_jsons_is_case_insensitive() -> None:
    records = [
        {"datalink_id": "gse1", "datalink_id_scheme": ""},
        {"datalink_id": "ERR1", "datalink_id_scheme": "geo"},
    ]

    assert Atlas(metadata={})._filter_jsons(records) == records


def test_collect_gse_jsons_keeps_gse_and_publications(monkeypatch) -> None:
    monkeypatch.setattr(atlas_module, "GEOWrapper", FakeGEOWrapper)
    FakeGEOWrapper.accessions = []
    records = [
        {
            "datalink_id": "GSE1",
            "datalink_id_scheme": "GEO",
            "datalink_url": "https://example.org/GSE1",
            "datalink_category": "GEO",
            "publications": [{"source": "MED", "epmc_id": "1"}],
        }
    ]

    assert Atlas(metadata={})._collect_gse_jsons(jsons=records) == [
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


def test_collect_gse_jsons_resolves_gsm_and_preserves_original_metadata(
    monkeypatch,
) -> None:
    monkeypatch.setattr(atlas_module, "GEOWrapper", FakeGEOWrapper)
    FakeGEOWrapper.accessions = []
    records = [
        {
            "datalink_id": "GSM1",
            "datalink_id_scheme": "GEO",
            "datalink_url": "https://example.org/GSM1",
            "datalink_category": "GEO",
            "publications": [{"source": "MED", "epmc_id": "1"}],
        }
    ]

    result = Atlas(metadata={})._collect_gse_jsons(jsons=records)

    assert result[0]["datalink_id"] == "GSE1"
    assert result[0]["original_datalinks"] == [
        {
            "datalink_id": "GSM1",
            "datalink_id_scheme": "GEO",
            "datalink_url": "https://example.org/GSM1",
            "datalink_category": "GEO",
        }
    ]
    assert result[0]["publications"] == [{"source": "MED", "epmc_id": "1"}]


def test_collect_gse_jsons_resolves_gds(monkeypatch) -> None:
    monkeypatch.setattr(atlas_module, "GEOWrapper", FakeGEOWrapper)
    records = [
        {
            "datalink_id": "GDS1",
            "datalink_id_scheme": "GEO",
            "publications": [],
        }
    ]

    assert Atlas(metadata={})._collect_gse_jsons(jsons=records)[0]["datalink_id"] == (
        "GSE1"
    )


def test_collect_gse_jsons_drops_gpl_and_unresolved(monkeypatch) -> None:
    monkeypatch.setattr(atlas_module, "GEOWrapper", FakeGEOWrapper)
    records = [
        {"datalink_id": "GPL1", "datalink_id_scheme": "GEO", "publications": []},
        {"datalink_id": "GSM404", "datalink_id_scheme": "GEO", "publications": []},
    ]

    assert Atlas(metadata={})._collect_gse_jsons(jsons=records) == []


def test_collect_gse_jsons_collapses_same_gse_and_merges_metadata(
    monkeypatch,
) -> None:
    monkeypatch.setattr(atlas_module, "GEOWrapper", FakeGEOWrapper)
    records = [
        {
            "datalink_id": "GSE1",
            "datalink_id_scheme": "GEO",
            "datalink_url": "https://example.org/GSE1",
            "datalink_category": "GEO",
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
            "datalink_id": "GSM1",
            "datalink_id_scheme": "GEO",
            "datalink_url": "https://example.org/GSM1",
            "datalink_category": "GEO",
            "publications": [
                {
                    "source": "MED",
                    "epmc_id": "1",
                    "pmid": "1",
                    "pmcid": "PMC1",
                    "doi": "10.1/one",
                },
                {
                    "source": "MED",
                    "epmc_id": "2",
                    "pmid": "2",
                    "pmcid": "PMC2",
                    "doi": "10.1/two",
                },
            ],
        },
    ]

    result = Atlas(metadata={})._collect_gse_jsons(jsons=records)

    assert len(result) == 1
    assert result[0]["datalink_id"] == "GSE1"
    assert result[0]["datalink_url"] == "https://example.org/GSE1"
    assert result[0]["original_datalinks"] == [
        {
            "datalink_id": "GSE1",
            "datalink_id_scheme": "GEO",
            "datalink_url": "https://example.org/GSE1",
            "datalink_category": "GEO",
        },
        {
            "datalink_id": "GSM1",
            "datalink_id_scheme": "GEO",
            "datalink_url": "https://example.org/GSM1",
            "datalink_category": "GEO",
        },
    ]
    assert result[0]["publications"] == [
        {
            "source": "MED",
            "epmc_id": "1",
            "pmid": "1",
            "pmcid": "PMC1",
            "doi": "10.1/one",
        },
        {
            "source": "MED",
            "epmc_id": "2",
            "pmid": "2",
            "pmcid": "PMC2",
            "doi": "10.1/two",
        },
    ]


def test_collect_publication_texts_enriches_unique_publications(monkeypatch) -> None:
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
    assert result[0]["publications"][0]["text"] == "Text 1"
    assert result[1]["publications"][0]["text"] == "Text 1"


def test_collect_publication_texts_skips_empty_publication_lists(monkeypatch) -> None:
    monkeypatch.setattr(atlas_module, "EuropePMCWrapper", FakeEuropePMCWrapper)
    FakeEuropePMCWrapper.publications = None
    records = [{"datalink_id": "GSE1", "publications": []}]

    assert Atlas(metadata={})._collect_publication_texts(jsons=records) == records
    assert FakeEuropePMCWrapper.publications is None


def test_collect_jsons_enriches_only_surviving_publications(monkeypatch) -> None:
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

    result = Atlas(metadata={}).collect_jsons(query=["fibrosis"])

    assert LocalEuropePMCWrapper.publications == [
        {"source": "MED", "epmc_id": "1", "abstractText": "Kept abstract"}
    ]
    assert result[0]["publications"][0]["text"] == "Kept abstract"

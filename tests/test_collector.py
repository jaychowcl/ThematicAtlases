import logging

from ThematicAtlases.collector import AtlasCollector
from ThematicAtlases.collector import collector as collector_module


class FakeEuropePMCWrapper:
    queries: list[str] | None = None
    max_publications: int | None = None

    def collect_accessions(
        self,
        queries: list[str],
        max_publications: int | None = None,
    ) -> list[dict]:
        self.__class__.queries = queries
        self.__class__.max_publications = max_publications
        return [
            {
                "datalink_id": "GSE1",
                "datalink_id_scheme": "GEO",
                "datalink_url": "https://example.org/GSE1",
                "datalink_category": "GEO",
                "publications": [{"source": "MED", "epmc_id": "1"}],
            },
            {
                "datalink_id": "E-MTAB-1",
                "datalink_id_scheme": "ArrayExpress",
                "datalink_url": "https://example.org/E-MTAB-1",
                "datalink_category": "Functional Genomics Experiments",
                "publications": [{"source": "MED", "epmc_id": "2"}],
            },
            {"datalink_id": "ERR1", "datalink_id_scheme": "ENA", "publications": []},
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


class FakeArrayExpressWrapper:
    jsons: list[dict] | None = None

    def collect_accession_metadata(self, jsons: list[dict]) -> list[dict]:
        self.__class__.jsons = jsons
        return [
            {
                **record,
                "metadata_repository": "arrayexpress",
                "metadata_source": "placeholder",
                "metadata_status": "placeholder",
                "accession_metadata": None,
            }
            for record in jsons
        ]


def test_collect_jsons_passes_queries_to_epmc_wrapper(monkeypatch) -> None:
    monkeypatch.setattr(collector_module, "EuropePMCWrapper", FakeEuropePMCWrapper)
    monkeypatch.setattr(collector_module, "GEOWrapper", FakeGEOWrapper)
    FakeGEOWrapper.accessions = []
    FakeGEOWrapper.jsons = None

    assert AtlasCollector().collect_jsons(query=["a", "b"]) == [
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
    assert FakeEuropePMCWrapper.queries == ["a", "b"]
    assert FakeEuropePMCWrapper.max_publications is None
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


def test_collect_jsons_passes_max_publications_to_epmc_wrapper(monkeypatch) -> None:
    monkeypatch.setattr(collector_module, "EuropePMCWrapper", FakeEuropePMCWrapper)
    monkeypatch.setattr(collector_module, "GEOWrapper", FakeGEOWrapper)
    FakeEuropePMCWrapper.max_publications = None

    AtlasCollector().collect_jsons(query=["a"], max_publications=25)

    assert FakeEuropePMCWrapper.queries == ["a"]
    assert FakeEuropePMCWrapper.max_publications == 25


def test_collect_jsons_can_keep_geo_and_arrayexpress(monkeypatch) -> None:
    monkeypatch.setattr(collector_module, "EuropePMCWrapper", FakeEuropePMCWrapper)
    monkeypatch.setattr(collector_module, "GEOWrapper", FakeGEOWrapper)
    monkeypatch.setattr(
        collector_module,
        "ArrayExpressWrapper",
        FakeArrayExpressWrapper,
    )
    FakeGEOWrapper.accessions = []
    FakeGEOWrapper.jsons = None
    FakeArrayExpressWrapper.jsons = None

    result = AtlasCollector(metadata_repositories=["geo", "arrayexpress"]).collect_jsons(
        query=["a"]
    )

    assert [record["datalink_id"] for record in result] == ["GSE1", "E-MTAB-1"]
    assert result[1]["metadata_repository"] == "arrayexpress"
    assert FakeGEOWrapper.jsons == [
        {
            "datalink_id": "GSE1",
            "datalink_id_scheme": "GEO",
            "datalink_url": "https://example.org/GSE1",
            "datalink_category": "GEO",
            "publications": [{"source": "MED", "epmc_id": "1"}],
        }
    ]
    assert FakeArrayExpressWrapper.jsons == [
        {
            "datalink_id": "E-MTAB-1",
            "datalink_id_scheme": "ArrayExpress",
            "datalink_url": "https://example.org/E-MTAB-1",
            "datalink_category": "Functional Genomics Experiments",
            "publications": [{"source": "MED", "epmc_id": "2"}],
        }
    ]


def test_collect_jsons_can_keep_only_arrayexpress(monkeypatch) -> None:
    monkeypatch.setattr(collector_module, "EuropePMCWrapper", FakeEuropePMCWrapper)
    monkeypatch.setattr(
        collector_module,
        "ArrayExpressWrapper",
        FakeArrayExpressWrapper,
    )
    FakeArrayExpressWrapper.jsons = None

    result = AtlasCollector(metadata_repositories=["arrayexpress"]).collect_jsons(
        query=["a"]
    )

    assert result == [
        {
            "datalink_id": "E-MTAB-1",
            "datalink_id_scheme": "ArrayExpress",
            "datalink_url": "https://example.org/E-MTAB-1",
            "datalink_category": "Functional Genomics Experiments",
            "publications": [{"source": "MED", "epmc_id": "2"}],
            "metadata_repository": "arrayexpress",
            "metadata_source": "placeholder",
            "metadata_status": "placeholder",
            "accession_metadata": None,
        }
    ]


def test_collect_jsons_combines_query_and_file_lines(monkeypatch, tmp_path) -> None:
    query_file = tmp_path / "queries.txt"
    query_file.write_text(" c \n\n# skip me\n d\n", encoding="utf-8")
    monkeypatch.setattr(collector_module, "EuropePMCWrapper", FakeEuropePMCWrapper)
    monkeypatch.setattr(collector_module, "GEOWrapper", FakeGEOWrapper)

    AtlasCollector().collect_jsons(query=["a", "b"], file=str(query_file))

    assert FakeEuropePMCWrapper.queries == ["a", "b", "c", "d"]


def test_collect_jsons_passes_empty_queries_without_inputs(monkeypatch) -> None:
    monkeypatch.setattr(collector_module, "EuropePMCWrapper", FakeEuropePMCWrapper)
    monkeypatch.setattr(collector_module, "GEOWrapper", FakeGEOWrapper)

    AtlasCollector().collect_jsons()

    assert FakeEuropePMCWrapper.queries == []


def test_collect_jsons_writes_result_to_outfile(monkeypatch, tmp_path) -> None:
    outfile = tmp_path / "atlas.json"
    monkeypatch.setattr(collector_module, "EuropePMCWrapper", FakeEuropePMCWrapper)
    monkeypatch.setattr(collector_module, "GEOWrapper", FakeGEOWrapper)

    AtlasCollector().collect_jsons(query=["a"], out=str(outfile))

    assert '"datalink_id": "GSE1"' in outfile.read_text(encoding="utf-8")


def test_filter_accessions_keeps_handled_geo_scheme() -> None:
    records = [
        {"datalink_id": "ERR1", "datalink_id_scheme": "GEO"},
        {"datalink_id": "ERR2", "datalink_id_scheme": "ENA"},
    ]

    assert AtlasCollector().filter_accessions(records) == [
        {"datalink_id": "ERR1", "datalink_id_scheme": "GEO"}
    ]


def test_filter_accessions_keeps_handled_geo_prefixes() -> None:
    records = [
        {"datalink_id": "GSE1", "datalink_id_scheme": ""},
        {"datalink_id": "GSM1", "datalink_id_scheme": "URL"},
        {"datalink_id": "GPL1", "datalink_id_scheme": "ArrayExpress"},
        {"datalink_id": "GDS1", "datalink_id_scheme": "BioProject"},
    ]

    assert AtlasCollector().filter_accessions(records) == records


def test_filter_accessions_drops_unhandled_records() -> None:
    records = [
        {"datalink_id": "ERR1", "datalink_id_scheme": "ENA"},
        {"datalink_id": "PRJ1", "datalink_id_scheme": "BioProject"},
        {"datalink_id": "E-MTAB-1", "datalink_id_scheme": "ArrayExpress"},
        {"datalink_id": "https://example.org", "datalink_id_scheme": "URL"},
        {"datalink_id": "ABC1", "datalink_id_scheme": ""},
    ]

    assert AtlasCollector().filter_accessions(records) == []


def test_filter_accessions_keeps_arrayexpress_when_selected() -> None:
    records = [
        {"datalink_id": "GSE1", "datalink_id_scheme": "GEO"},
        {"datalink_id": "E-MTAB-1", "datalink_id_scheme": "ArrayExpress"},
        {"datalink_id": "E-GEOD-1", "datalink_id_scheme": ""},
        {"datalink_id": "E-MEXP-1", "datalink_id_scheme": ""},
        {"datalink_id": "ERR1", "datalink_id_scheme": "ENA"},
    ]

    assert AtlasCollector(metadata_repositories=["arrayexpress"]).filter_accessions(
        records
    ) == [
        {"datalink_id": "E-MTAB-1", "datalink_id_scheme": "ArrayExpress"},
        {"datalink_id": "E-GEOD-1", "datalink_id_scheme": ""},
        {"datalink_id": "E-MEXP-1", "datalink_id_scheme": ""},
    ]


def test_filter_accessions_is_case_insensitive() -> None:
    records = [
        {"datalink_id": "gse1", "datalink_id_scheme": ""},
        {"datalink_id": "ERR1", "datalink_id_scheme": "geo"},
    ]

    assert AtlasCollector().filter_accessions(records) == records


def test_is_handled_accession_uses_current_geo_rules() -> None:
    assert AtlasCollector().is_handled_accession(
        {"datalink_id": "GSE1", "datalink_id_scheme": ""}
    )
    assert not AtlasCollector().is_handled_accession(
        {"datalink_id": "ERR1", "datalink_id_scheme": "ENA"}
    )


def test_metadata_repository_detects_geo_records() -> None:
    assert (
        AtlasCollector().metadata_repository(
            {
                "datalink_id": "GSE1",
                "datalink_id_scheme": "",
            }
        )
        == "geo"
    )


def test_metadata_repository_returns_none_for_unhandled_records() -> None:
    assert (
        AtlasCollector().metadata_repository(
            {
                "datalink_id": "ERR1",
                "datalink_id_scheme": "ENA",
            }
        )
        is None
    )


def test_metadata_repository_detects_arrayexpress_records() -> None:
    collector = AtlasCollector(metadata_repositories=["arrayexpress"])

    assert (
        collector.metadata_repository(
            {
                "datalink_id": "E-MTAB-1",
                "datalink_id_scheme": "ArrayExpress",
            }
        )
        == "arrayexpress"
    )


def test_metadata_repository_raises_for_unsupported_option() -> None:
    try:
        AtlasCollector(metadata_repositories=["unknown"])
    except ValueError as error:
        assert "Unsupported metadata repositories" in str(error)
    else:
        raise AssertionError("unsupported repository should fail")


def test_collect_accession_metadata_routes_geo_records(monkeypatch) -> None:
    monkeypatch.setattr(collector_module, "GEOWrapper", FakeGEOWrapper)
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

    assert AtlasCollector().collect_accession_metadata(jsons=records)[0][
        "original_datalinks"
    ] == [
        {
            "datalink_id": "GSE1",
            "datalink_id_scheme": "GEO",
            "datalink_url": "https://example.org/GSE1",
            "datalink_category": "GEO",
        }
    ]
    assert FakeGEOWrapper.accessions == ["GSE1"]
    assert FakeGEOWrapper.jsons == records


def test_collect_jsons_logs_progress_and_stats(monkeypatch, caplog) -> None:
    monkeypatch.setattr(collector_module, "EuropePMCWrapper", FakeEuropePMCWrapper)
    monkeypatch.setattr(collector_module, "GEOWrapper", FakeGEOWrapper)
    caplog.set_level(logging.INFO, logger=collector_module.__name__)

    AtlasCollector().collect_jsons(query=["a", "b"])

    assert "stage=query-loading" in caplog.text
    assert "stage=collect-accessions" in caplog.text
    assert "query_count=2" in caplog.text
    assert "raw_accessions=3" in caplog.text
    assert "metadata_records=1" in caplog.text


def test_filter_accessions_logs_stats(caplog) -> None:
    caplog.set_level(logging.INFO, logger=collector_module.__name__)

    AtlasCollector().filter_accessions(
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
    monkeypatch.setattr(collector_module, "GEOWrapper", FakeGEOWrapper)
    caplog.set_level(logging.INFO, logger=collector_module.__name__)

    AtlasCollector().collect_accession_metadata(
        jsons=[
            {"datalink_id": "GSE1", "datalink_id_scheme": "GEO"},
            {"datalink_id": "ERR1", "datalink_id_scheme": "ENA"},
        ]
    )

    assert "Atlas metadata collection progress repository=geo records=1" in caplog.text
    assert "input_records=2" in caplog.text
    assert "repositories=geo:1" in caplog.text
    assert "skipped_records=1" in caplog.text

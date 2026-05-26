from ThematicAtlases import atlas as atlas_module
from ThematicAtlases.atlas import Atlas


class FakeEuropePMCWrapper:
    queries: list[str] | None = None

    def collect_accessions(self, queries: list[str]) -> list[dict]:
        self.__class__.queries = queries
        return [
            {"datalink_id": "GSE1", "datalink_id_scheme": "GEO", "publications": []},
            {"datalink_id": "ERR1", "datalink_id_scheme": "ENA", "publications": []},
        ]


def test_collect_jsons_passes_queries_to_epmc_wrapper(monkeypatch) -> None:
    monkeypatch.setattr(atlas_module, "EuropePMCWrapper", FakeEuropePMCWrapper)

    assert Atlas(metadata={}).collect_jsons(query=["a", "b"]) == [
        {"datalink_id": "GSE1", "datalink_id_scheme": "GEO", "publications": []}
    ]
    assert FakeEuropePMCWrapper.queries == ["a", "b"]


def test_collect_jsons_combines_query_and_file_lines(monkeypatch, tmp_path) -> None:
    query_file = tmp_path / "queries.txt"
    query_file.write_text(" c \n\n# skip me\n d\n", encoding="utf-8")
    monkeypatch.setattr(atlas_module, "EuropePMCWrapper", FakeEuropePMCWrapper)

    Atlas(metadata={}).collect_jsons(query=["a", "b"], file=str(query_file))

    assert FakeEuropePMCWrapper.queries == ["a", "b", "c", "d"]


def test_collect_jsons_passes_empty_queries_without_inputs(monkeypatch) -> None:
    monkeypatch.setattr(atlas_module, "EuropePMCWrapper", FakeEuropePMCWrapper)

    Atlas(metadata={}).collect_jsons()

    assert FakeEuropePMCWrapper.queries == []


def test_collect_jsons_writes_result_to_outfile(monkeypatch, tmp_path) -> None:
    outfile = tmp_path / "atlas.json"
    monkeypatch.setattr(atlas_module, "EuropePMCWrapper", FakeEuropePMCWrapper)

    Atlas(metadata={}).collect_jsons(query=["a"], out=str(outfile))

    assert outfile.read_text(encoding="utf-8") == '[\n  {\n    "datalink_id": "GSE1",\n    "datalink_id_scheme": "GEO",\n    "publications": []\n  }\n]'


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

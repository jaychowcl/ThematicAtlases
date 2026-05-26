from ThematicAtlases import atlas as atlas_module
from ThematicAtlases.atlas import Atlas


class FakeEuropePMCWrapper:
    queries: list[str] | None = None

    def collect_accessions(self, queries: list[str]) -> list[dict]:
        self.__class__.queries = queries
        return [{"accession": "GSE1"}]


def test_collect_jsons_passes_queries_to_epmc_wrapper(monkeypatch) -> None:
    monkeypatch.setattr(atlas_module, "EuropePMCWrapper", FakeEuropePMCWrapper)

    assert Atlas(metadata={}).collect_jsons(query=["a", "b"]) == [{"accession": "GSE1"}]
    assert FakeEuropePMCWrapper.queries == ["a", "b"]


def test_collect_jsons_combines_query_and_file_lines(monkeypatch, tmp_path) -> None:
    query_file = tmp_path / "queries.txt"
    query_file.write_text(" c \n\n# skip me\n d\n", encoding="utf-8")
    monkeypatch.setattr(atlas_module, "EuropePMCWrapper", FakeEuropePMCWrapper)

    Atlas(metadata={}).collect_jsons(query=["a", "b"], file=str(query_file))

    assert FakeEuropePMCWrapper.queries == ["a", "b", "c", "d"]


def test_collect_jsons_uses_default_query_file(monkeypatch, tmp_path) -> None:
    query_file = tmp_path / "queries.txt"
    query_file.write_text("# old\nfibrosis\n\ntranscriptomics\n", encoding="utf-8")
    monkeypatch.setattr(atlas_module, "EuropePMCWrapper", FakeEuropePMCWrapper)
    monkeypatch.setattr(atlas_module, "DEFAULT_QUERY_FILE", str(query_file))

    Atlas(metadata={}).collect_jsons()

    assert FakeEuropePMCWrapper.queries == ["fibrosis", "transcriptomics"]


def test_collect_jsons_writes_result_to_outfile(monkeypatch, tmp_path) -> None:
    outfile = tmp_path / "atlas.json"
    monkeypatch.setattr(atlas_module, "EuropePMCWrapper", FakeEuropePMCWrapper)

    Atlas(metadata={}).collect_jsons(query=["a"], out=str(outfile))

    assert outfile.read_text(encoding="utf-8") == '[\n  {\n    "accession": "GSE1"\n  }\n]'

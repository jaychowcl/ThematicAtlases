from ThematicAtlases import atlas as atlas_module
from ThematicAtlases.atlas import Atlas


class FakeEuropePMCWrapper:
    def collect_accessions(self) -> list[dict]:
        return [{"accession": "GSE1"}]


def test_collect_jsons_returns_accessions_from_epmc_wrapper(monkeypatch) -> None:
    monkeypatch.setattr(atlas_module, "EuropePMCWrapper", FakeEuropePMCWrapper)

    assert Atlas(metadata={}).collect_jsons() == [{"accession": "GSE1"}]

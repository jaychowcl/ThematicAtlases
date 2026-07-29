from ThematicAtlases.collector.accession_extraction import (
    extract_accessions_from_text,
)
from ThematicAtlases.wrappers.epmc import EuropePMCWrapper


def test_extract_accessions_from_text_recognizes_all_registered_object_levels() -> None:
    text = """
    GEO: GSE123, GSM456, GPL789, GDS10.
    ArrayExpress: E-MTAB-1234, E-GEOD-5678, E-MEXP-90, A-MEXP-72.
    BioStudies: S-BSST12345, S-EPMC3521001, S-BIAD300.
    BioProject: PRJNA123, PRJEB456, PRJDB789.
    INSDC: SRP1 ERP2 DRP3 SRS4 ERS5 DRS6 SRX7 ERX8 DRX9
    SRR10 ERR11 DRR12 SRZ13 ERZ14 DRZ15 SRA16 ERA17 DRA18.
    BioSample: SAMN19, SAMEA20, SAMD21.
    """

    matches = extract_accessions_from_text(text)

    assert [match["accession"] for match in matches] == [
        "GSE123",
        "GSM456",
        "GPL789",
        "GDS10",
        "E-MTAB-1234",
        "E-GEOD-5678",
        "E-MEXP-90",
        "A-MEXP-72",
        "S-BSST12345",
        "S-EPMC3521001",
        "S-BIAD300",
        "PRJNA123",
        "PRJEB456",
        "PRJDB789",
        "SRP1",
        "ERP2",
        "DRP3",
        "SRS4",
        "ERS5",
        "DRS6",
        "SRX7",
        "ERX8",
        "DRX9",
        "SRR10",
        "ERR11",
        "DRR12",
        "SRZ13",
        "ERZ14",
        "DRZ15",
        "SRA16",
        "ERA17",
        "DRA18",
        "SAMN19",
        "SAMEA20",
        "SAMD21",
    ]
    assert matches[0] == {
        "accession": "GSE123",
        "datalink_id_scheme": "GEO",
        "datalink_category": "GEO",
        "repository": "geo",
        "object_type": "series",
    }
    assert matches[7]["object_type"] == "array_design"
    assert matches[13]["object_type"] == "study"
    assert matches[22]["object_type"] == "run"
    assert matches[31]["object_type"] == "submission"
    assert matches[-1]["object_type"] == "biosample"


def test_extract_accessions_normalizes_case_deduplicates_and_rejects_near_matches() -> None:
    matches = extract_accessions_from_text(
        "gse123, GSE123; xGSE999 GSE 456 GSEabc E-MTAB-7suffix."
    )

    assert [match["accession"] for match in matches] == ["GSE123"]


def test_collect_accessions_scrapes_all_fulltexts_by_default_and_merges_provenance(
    monkeypatch,
) -> None:
    wrapper = EuropePMCWrapper(request_delay=0)
    publications = [
        {"query": "q", "source": "MED", "epmc_id": "1", "pmid": "1"},
        {"query": "q", "source": "MED", "epmc_id": "2", "pmid": "2"},
    ]
    datalink_accessions = [
        {
            "datalink_id": "GSE1",
            "datalink_id_scheme": "GEO",
            "datalink_url": "https://example.org/GSE1",
            "datalink_category": "GEO",
            "publications": [publications[0]],
        }
    ]
    text_calls = []

    monkeypatch.setattr(
        wrapper,
        "collect_publications",
        lambda **kwargs: publications,
    )
    monkeypatch.setattr(
        wrapper,
        "collect_datalinks",
        lambda **kwargs: datalink_accessions,
    )

    def collect_publication_texts(**kwargs):
        text_calls.extend(kwargs["publications"])
        return [
            {
                **publications[0],
                "text": "GSE1 and PRJNA10",
                "text_source": "fullTextXML",
                "full_text_status": "available",
            },
            {
                **publications[1],
                "text": "GSM2 and ERR3",
                "text_source": "fullTextXML",
                "full_text_status": "available",
            },
        ]

    monkeypatch.setattr(
        wrapper,
        "collect_publication_texts",
        collect_publication_texts,
    )

    result = wrapper.collect_accessions(queries=["q"])

    assert text_calls == publications
    assert [record["datalink_id"] for record in result] == [
        "GSE1",
        "PRJNA10",
        "GSM2",
        "ERR3",
    ]
    assert result[0]["datalink_url"] == "https://example.org/GSE1"
    assert result[0]["discovery_sources"] == [
        "europe_pmc_datalink",
        "fulltext_regex",
    ]
    assert result[0]["publications"][0]["accession_discovery_sources"] == [
        "europe_pmc_datalink",
        "fulltext_regex",
    ]
    assert result[1]["discovery_sources"] == ["fulltext_regex"]
    assert result[1]["publications"][0]["text"] == "GSE1 and PRJNA10"


def test_collect_accessions_does_not_scrape_abstract_fallbacks(monkeypatch) -> None:
    wrapper = EuropePMCWrapper(request_delay=0)
    publication = {"query": "q", "source": "MED", "epmc_id": "1", "pmid": "1"}
    monkeypatch.setattr(
        wrapper,
        "collect_publications",
        lambda **kwargs: [publication],
    )
    monkeypatch.setattr(wrapper, "collect_datalinks", lambda **kwargs: [])
    monkeypatch.setattr(
        wrapper,
        "collect_publication_texts",
        lambda **kwargs: [
            {
                **publication,
                "text": "Abstract mentions GSE123",
                "text_source": "abstractText",
                "full_text_status": "missing_pmcid",
            }
        ],
    )

    assert wrapper.collect_accessions(queries=["q"]) == []


def test_collect_accessions_can_disable_fulltext_scraping(monkeypatch) -> None:
    wrapper = EuropePMCWrapper(request_delay=0)
    publication = {"query": "q", "source": "MED", "epmc_id": "1"}
    expected = [{"datalink_id": "GSE1", "publications": [publication]}]
    monkeypatch.setattr(
        wrapper,
        "collect_publications",
        lambda **kwargs: [publication],
    )
    monkeypatch.setattr(
        wrapper,
        "collect_datalinks",
        lambda **kwargs: expected,
    )
    monkeypatch.setattr(
        wrapper,
        "collect_publication_texts",
        lambda **kwargs: (_ for _ in ()).throw(
            AssertionError("full text should not be fetched")
        ),
    )

    assert wrapper.collect_accessions(
        queries=["q"],
        scrape_fulltext_accessions=False,
    ) == expected

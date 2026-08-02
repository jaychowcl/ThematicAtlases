from ThematicAtlases.accession_extraction import (
    extract_accessions_from_links,
    extract_accessions_from_text,
)
from ThematicAtlases.checkpoint import CheckpointStore
from ThematicAtlases.filterer import AtlasFilterer
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
    assert matches[14]["object_type"] == "study"
    assert matches[23]["object_type"] == "run"
    assert matches[29]["object_type"] == "submission"
    assert matches[-1]["object_type"] == "biosample"


def test_extract_accessions_normalizes_case_deduplicates_and_rejects_near_matches() -> None:
    matches = extract_accessions_from_text(
        "gse123, GSE123; xGSE999 GSE 456 GSEabc E-MTAB-7suffix."
    )

    assert [match["accession"] for match in matches] == ["GSE123"]


def test_extract_accessions_recognizes_curated_biomedical_repository_ids() -> None:
    matches = extract_accessions_from_text(
        "EGAS00001006330 EGAD00001001234 phs001234.v2.p1 SCP259 syn12345 "
        "PXD012345 MTBLS123 SDY456 PRJCA789 CRA123456 HRA001149"
    )

    assert [match["accession"] for match in matches] == [
        "EGAS00001006330",
        "EGAD00001001234",
        "PHS001234.V2.P1",
        "SCP259",
        "SYN12345",
        "PXD012345",
        "MTBLS123",
        "SDY456",
        "PRJCA789",
        "CRA123456",
        "HRA001149",
    ]
    assert [match["repository"] for match in matches] == [
        "ega",
        "ega",
        "dbgap",
        "single_cell_portal",
        "synapse",
        "pride",
        "metabolights",
        "immport",
        "ngdc",
        "ngdc",
        "ngdc",
    ]


def test_extract_accessions_rejects_curated_repository_near_matches() -> None:
    assert extract_accessions_from_text(
        "EGAS123 phsABC SCPx259 xSCP259 PXDabc MTBLS SDYx CRA HRAfoo"
    ) == []


def test_extract_accessions_from_curated_repository_links() -> None:
    collection = "ddfad306-714d-4cc0-9985-d9072820c530"
    dataset = "9a305865-e7b0-4e8a-bbbf-0b63287e85fd"
    links = [
        f"https://cellxgene.cziscience.com/collections/{collection}",
        f"https://cellxgene.cziscience.com/e/{dataset}.cxg/",
        "https://singlecell.broadinstitute.org/single_cell/study/SCP259/example",
        "https://www.synapse.org/Synapse:#!Synapse:syn12345",
        "https://zenodo.org/records/18432222",
        "https://doi.org/10.6084/m9.figshare.11786238.v2",
        "https://doi.org/10.5061/dryad.abc123",
        "https://doi.org/10.17632/abc123xyz.3",
        "https://dataverse.harvard.edu/dataset.xhtml?persistentId=doi:10.7910/DVN/ABC123",
    ]

    matches = extract_accessions_from_links(links)

    assert [(match["accession"], match["repository"]) for match in matches] == [
        (f"CELLXGENE-COLLECTION:{collection.upper()}", "cellxgene"),
        (f"CELLXGENE-DATASET:{dataset.upper()}", "cellxgene"),
        ("SCP259", "single_cell_portal"),
        ("SYN12345", "synapse"),
        ("ZENODO:18432222", "zenodo"),
        ("FIGSHARE:11786238.V2", "figshare"),
        ("DRYAD:10.5061/DRYAD.ABC123", "dryad"),
        ("MENDELEY:ABC123XYZ.3", "mendeley_data"),
        ("DATAVERSE:10.7910/DVN/ABC123", "dataverse"),
    ]
    assert [match["datalink_url"] for match in matches] == links


def test_extract_accessions_from_links_ignores_generic_file_sharing() -> None:
    assert extract_accessions_from_links(
        [
            "https://drive.google.com/file/d/abc/view",
            "https://dropbox.com/s/abc/data.zip",
            "https://bucket.s3.amazonaws.com/data.h5ad",
        ]
    ) == []


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


def test_collect_accessions_scans_hidden_jats_link_targets(monkeypatch) -> None:
    wrapper = EuropePMCWrapper(request_delay=0)
    publication = {"query": "q", "source": "MED", "epmc_id": "1", "pmid": "1"}
    monkeypatch.setattr(wrapper, "collect_publications", lambda **kwargs: [publication])
    monkeypatch.setattr(wrapper, "collect_datalinks", lambda **kwargs: [])
    monkeypatch.setattr(
        wrapper,
        "collect_publication_texts",
        lambda **kwargs: [
            {
                **publication,
                "text": "Download the processed atlas.",
                "full_text_links": ["https://zenodo.org/records/18432222"],
                "text_source": "fullTextXML",
                "full_text_status": "available",
            }
        ],
    )

    result = wrapper.collect_accessions(queries=["q"])

    assert result[0]["datalink_id"] == "ZENODO:18432222"
    assert result[0]["datalink_url"] == "https://zenodo.org/records/18432222"
    assert result[0]["accession_repository"] == "zenodo"


def test_jats_parser_retains_hidden_external_link_targets() -> None:
    wrapper = EuropePMCWrapper(request_delay=0)
    xml = """
    <article xmlns:xlink="http://www.w3.org/1999/xlink">
      <body><sec><title>Data availability</title><p>
        Processed data are deposited <ext-link
          xlink:href="https://zenodo.org/records/18432222">here</ext-link>.
      </p></sec></body>
    </article>
    """

    text, links = wrapper._text_and_links_from_xml(xml)

    assert "Processed data are deposited here" in text
    assert links == ["https://zenodo.org/records/18432222"]


def test_collect_accessions_scrapes_abstract_fallbacks_with_precise_provenance(
    monkeypatch,
) -> None:
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

    assert wrapper.collect_accessions(queries=["q"]) == [
        {
            "datalink_id": "GSE123",
            "datalink_id_scheme": "GEO",
            "datalink_url": "",
            "datalink_category": "GEO",
            "accession_repository": "geo",
            "accession_object_type": "series",
            "discovery_sources": ["abstract_regex"],
            "publications": [
                {
                    **publication,
                    "text": "Abstract mentions GSE123",
                    "text_source": "abstractText",
                    "full_text_status": "missing_pmcid",
                    "accession_discovery_sources": ["abstract_regex"],
                }
            ],
        }
    ]


def test_collect_publication_texts_fetches_latest_supported_preprint_jats() -> None:
    calls = []

    class Response:
        def __init__(self, payload=None, text=""):
            self._payload = payload
            self.text = text
            self.status_code = 200
            self.headers = {}

        def json(self):
            return self._payload

        def raise_for_status(self):
            return None

    class RequestPolicy:
        def get(self, url, **kwargs):
            calls.append(url)
            if url == (
                "https://api.biorxiv.org/details/biorxiv/"
                "10.1101/2025.09.12.25335572/na/json"
            ):
                return Response({"collection": []})
            if url == (
                "https://api.biorxiv.org/details/medrxiv/"
                "10.1101/2025.09.12.25335572/na/json"
            ):
                return Response(
                    {
                        "collection": [
                            {
                                "version": "1",
                                "jatsxml": "https://www.medrxiv.org/old.source.xml",
                            },
                            {
                                "version": "3",
                                "jatsxml": "https://www.medrxiv.org/latest.source.xml",
                            },
                        ]
                    }
                )
            if url == "https://www.medrxiv.org/latest.source.xml":
                return Response(
                    text=(
                        "<article><body><sec><title>Methods</title><p>No accessions.</p>"
                        "</sec></body><back><sec sec-type='data-availability'>"
                        "<title>Data Availability</title><p>Data: GSE213030 and "
                        "GSE254957.</p></sec><ref-list><ref><mixed-citation>"
                        "Unrelated GSE999.</mixed-citation></ref></ref-list></back></article>"
                    )
                )
            raise AssertionError(f"unexpected URL {url}")

    wrapper = EuropePMCWrapper(request_delay=0, request_policy=RequestPolicy())
    publication = {
        "source": "PPR",
        "epmc_id": "PPR1083600",
        "doi": "10.1101/2025.09.12.25335572",
        "abstractText": "Abstract without accessions",
    }

    enriched = wrapper.collect_publication_texts([publication])

    assert calls == [
        "https://api.biorxiv.org/details/biorxiv/10.1101/2025.09.12.25335572/na/json",
        "https://api.biorxiv.org/details/medrxiv/10.1101/2025.09.12.25335572/na/json",
        "https://www.medrxiv.org/latest.source.xml",
    ]
    assert enriched[0]["text_source"] == "preprintJATSXML"
    assert enriched[0]["full_text_status"] == "available"
    assert "GSE213030" in enriched[0]["text"]
    assert "GSE999" not in enriched[0]["text"]
    assert [
        record["datalink_id"]
        for record in wrapper.accessions_from_fulltexts(enriched)
    ] == ["GSE213030", "GSE254957"]


def test_collect_datalinks_remains_api_only(monkeypatch) -> None:
    wrapper = EuropePMCWrapper(request_delay=0)
    publication = {"source": "MED", "epmc_id": "1", "pmid": "1"}
    monkeypatch.setattr(
        wrapper,
        "_datalinks",
        lambda source, epmc_id: {"dataLinksList": {"Category": []}},
    )
    monkeypatch.setattr(
        wrapper,
        "collect_publication_texts",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("collect_datalinks must not fetch publication text")
        ),
    )

    assert wrapper.collect_datalinks([publication]) == []


def test_preprint_jats_rejects_untrusted_host_and_uses_abstract() -> None:
    calls = []

    class Response:
        status_code = 200
        headers = {}
        text = ""

        def json(self):
            return {
                "collection": [
                    {
                        "version": "1",
                        "jatsxml": "https://attacker.example/paper.xml",
                    }
                ]
            }

        def raise_for_status(self):
            return None

    class RequestPolicy:
        def get(self, url, **kwargs):
            calls.append(url)
            return Response()

    wrapper = EuropePMCWrapper(request_delay=0, request_policy=RequestPolicy())
    publication = {
        "source": "PPR",
        "epmc_id": "PPR1",
        "doi": "10.1101/2025.01.01.123456",
        "journalTitle": "bioRxiv",
        "abstractText": "Fallback GSE999",
    }

    enriched = wrapper.collect_publication_texts([publication])

    assert calls == [
        "https://api.biorxiv.org/details/biorxiv/10.1101/2025.01.01.123456/na/json"
    ]
    assert enriched[0]["text_source"] == "abstractText"
    assert enriched[0]["full_text_status"] == "error"


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


def test_fulltext_accession_discovery_is_checkpointed_and_reused(tmp_path) -> None:
    store = CheckpointStore(tmp_path / "resume.sqlite")
    wrapper = EuropePMCWrapper()
    publication = {
        "source": "MED",
        "epmc_id": "1",
        "text": "GSE123 and PRJNA456",
        "text_source": "fullTextXML",
        "full_text_status": "available",
    }

    first = wrapper.accessions_from_fulltexts(
        [publication],
        checkpoint_store=store,
    )
    second = wrapper.accessions_from_fulltexts(
        [{**publication, "text": "GSE999"}],
        checkpoint_store=store,
    )

    assert [record["datalink_id"] for record in first] == ["GSE123", "PRJNA456"]
    assert second == first
    assert (
        store.get("fulltext_accession_discovery", "MED:1")["status"]
        == "available"
    )
    assert store.has_retryable_boundary("discovery") is False


def test_filterer_reuses_prefetched_fulltext_without_another_request() -> None:
    filterer = AtlasFilterer(
        epmc_wrapper_factory=lambda: (_ for _ in ()).throw(
            AssertionError("full text should be reused")
        )
    )

    result = filterer.collect_publication_texts(
        jsons=[
            {
                "datalink_id": "GSE1",
                "publications": [
                    {
                        "source": "MED",
                        "epmc_id": "1",
                        "pmid": "1",
                        "text": "GSE1",
                        "text_source": "fullTextXML",
                        "full_text_status": "available",
                    }
                ],
            }
        ]
    )

    assert result == {
        "1": {
            "text": "GSE1",
            "text_source": "fullTextXML",
            "full_text_status": "available",
        }
    }

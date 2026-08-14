# =============================================================================
# Authors
# =============================================================================
# Created by jaychowcl @ Saez-Rodriguez Group & EMBL-EBI Functional Genomics Team on May 2026
# https://github.com/jaychowcl
# https://saezlab.org
# https://www.ebi.ac.uk/about/teams/functional-genomics/
# =============================================================================
"""Opt-in contracts for ThematicAtlases public HTTP providers."""

import pytest

from ThematicAtlases.wrappers.epmc import EuropePMCWrapper
from ThematicAtlases.wrappers.ae import ArrayExpressWrapper
from ThematicAtlases.wrappers.geo import GEOWrapper


pytestmark = pytest.mark.live_api


def test_europe_pmc_search_datalinks_and_full_text_contracts():
    wrapper = EuropePMCWrapper(page_limit=1, page_size=1, timeout=10, request_delay=0, max_retries=0)
    publications = wrapper.collect_publications(
        queries=["EXT_ID:39747812 AND SRC:MED"],
        max_publications=1,
        max_publications_per_query=[1],
    )
    assert len(publications) == 1
    publication = publications[0]
    assert publication["epmc_id"] == "39747812"
    assert publication.get("pmcid") == "PMC11697218"
    assert isinstance(wrapper.collect_datalinks([publication]), list)
    text = wrapper.collect_publication_texts([publication])[0]
    assert text["full_text_status"] == "available"
    assert text["text_source"] == "fullTextXML"
    assert text["text"].strip()


def test_biorxiv_details_and_jats_contract():
    wrapper = EuropePMCWrapper(timeout=10, request_delay=0, max_retries=0)
    publication = {
        "source": "PPR",
        "epmc_id": "PPR953245",
        "doi": "10.64898/2026.03.09.709232",
        "journalTitle": "biorxiv",
        "abstractText": "fallback",
    }
    enriched = wrapper.collect_publication_texts([publication])[0]
    assert enriched["full_text_status"] == "available"
    assert enriched["text_source"] == "preprintJATSXML"
    assert enriched["text"].strip()


def test_geo_esearch_and_esummary_contract():
    assert GEOWrapper(timeout=10, request_delay=0, max_retries=0).get_gse("GSM11805") == "GSE781"


def test_arrayexpress_biostudies_magetab_contract():
    record = {
        "datalink_id": "E-MTAB-6486",
        "datalink_id_scheme": "ArrayExpress",
        "publications": [],
    }

    result = ArrayExpressWrapper().collect_accession_metadata([record])

    assert result[0]["metadata_status"] == "available"
    package = result[0]["accession_metadata"]
    assert package["miniml_schema_version"] == "3.0"
    assert package["source"]["format"] == "MAGE-TAB"
    assert package["series"]["protocols"]
    assert package["series"]["assay_paths"]

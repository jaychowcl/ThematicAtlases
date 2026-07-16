import json
import threading
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor

import pytest
import requests

from ThematicAtlases.checkpoint import CheckpointStore
from ThematicAtlases.wrappers.enrichment import (
    CheckpointedINSDCFetcher,
    CheckpointedPubmedFetcher,
    EnrichmentAuditor,
    RetryTags,
    load_retry_tags,
)


PUBMED_RESULT = (
    "10.1/example",
    "One A, Two B",
    "A title",
    "published",
    "EFO",
    "EFO:0000000",
)


class FakePubmed:
    def __init__(self, outcome=PUBMED_RESULT):
        self.outcome = outcome
        self.calls = []

    def pubmed_summary(self, pubmed_id):
        self.calls.append(pubmed_id)
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


def test_pubmed_checkpoint_reuses_available_and_no_data(tmp_path) -> None:
    store = CheckpointStore(tmp_path / "resume.sqlite")
    available = FakePubmed()
    fetcher = CheckpointedPubmedFetcher(store, fetcher=available)

    assert fetcher.pubmed_summary("123") == PUBMED_RESULT
    assert fetcher.pubmed_summary("123") == PUBMED_RESULT
    assert available.calls == ["123"]
    assert store.get("pubmed_enrichment", "123")["status"] == "available"

    empty = FakePubmed((None, None, None, None, None, None))
    empty_fetcher = CheckpointedPubmedFetcher(store, fetcher=empty)
    assert empty_fetcher.pubmed_summary("456") == (None,) * 6
    assert empty_fetcher.pubmed_summary("456") == (None,) * 6
    assert empty.calls == ["456"]
    assert store.get("pubmed_enrichment", "456")["status"] == "no_data"


@pytest.mark.parametrize(
    ("error", "status"),
    [
        (requests.Timeout("pubmed timeout"), "retryable_error"),
        (requests.HTTPError("bad PMID", response=type("R", (), {"status_code": 404})()), "terminal_error"),
    ],
)
def test_pubmed_checkpoint_records_exact_errors(tmp_path, error, status) -> None:
    store = CheckpointStore(tmp_path / "resume.sqlite")
    fetcher = CheckpointedPubmedFetcher(store, fetcher=FakePubmed(error))

    with pytest.raises(type(error), match=str(error)):
        fetcher.pubmed_summary("789")

    item = store.get("pubmed_enrichment", "789")
    assert item["status"] == status
    assert item["error"] == str(error)


def test_pubmed_item_lock_prevents_duplicate_calls(tmp_path) -> None:
    store_path = tmp_path / "resume.sqlite"
    CheckpointStore(store_path)
    started = threading.Event()
    release = threading.Event()
    calls = []

    class SlowPubmed(FakePubmed):
        def pubmed_summary(self, pubmed_id):
            calls.append(pubmed_id)
            started.set()
            assert release.wait(timeout=5)
            return PUBMED_RESULT

    def fetch():
        return CheckpointedPubmedFetcher(
            CheckpointStore(store_path), fetcher=SlowPubmed()
        ).pubmed_summary("123")

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(fetch)
        assert started.wait(timeout=5)
        second = executor.submit(fetch)
        release.set()
        assert first.result() == PUBMED_RESULT
        assert second.result() == PUBMED_RESULT

    assert calls == ["123"]


SRA_XML = """<EXPERIMENT_PACKAGE_SET><EXPERIMENT_PACKAGE>
<STUDY accession="SRP1"/><EXPERIMENT accession="SRX1"><DESIGN><LIBRARY_DESCRIPTOR>
<LIBRARY_STRATEGY>RNA-Seq</LIBRARY_STRATEGY><LIBRARY_SOURCE>TRANSCRIPTOMIC</LIBRARY_SOURCE>
<LIBRARY_SELECTION>cDNA</LIBRARY_SELECTION><LIBRARY_LAYOUT><PAIRED/></LIBRARY_LAYOUT>
</LIBRARY_DESCRIPTOR></DESIGN><PLATFORM><ILLUMINA><INSTRUMENT_MODEL>NovaSeq</INSTRUMENT_MODEL>
</ILLUMINA></PLATFORM></EXPERIMENT><SAMPLE accession="SRS1"/>
<RUN_SET><RUN accession="SRR1" alias="run-one"/></RUN_SET>
</EXPERIMENT_PACKAGE></EXPERIMENT_PACKAGE_SET>"""


class FakeINSDC:
    def __init__(self, *, xml=SRA_XML, ena=None, sra_error=None, ena_error=None):
        self.xml = xml
        self.ena = [] if ena is None else ena
        self.sra_error = sra_error
        self.ena_error = ena_error
        self.sra_calls = []
        self.ena_calls = []

    def _ncbi_nrx(self, nrx):
        self.sra_calls.append(nrx)
        if self.sra_error:
            raise self.sra_error
        return ET.fromstring(self.xml)

    def fetch_ena_file_report(self, accession):
        self.ena_calls.append(accession)
        if self.ena_error:
            raise self.ena_error
        return self.ena


def test_sra_and_ena_are_checkpointed_independently(tmp_path) -> None:
    store = CheckpointStore(tmp_path / "resume.sqlite")
    base = FakeINSDC(
        ena=[
            {
                "run_accession": "SRR1",
                "fastq_ftp": "ftp.sra.ebi.ac.uk/SRR1.fastq.gz",
                "fastq_md5": "abc",
                "fastq_bytes": "10",
            }
        ]
    )
    fetcher = CheckpointedINSDCFetcher(store, fetcher=base)

    first = fetcher.fetch_sra_runs("SRX1")
    second = fetcher.fetch_sra_runs("SRX1")

    assert first == second
    assert first[0]["run"] == "SRR1"
    assert first[0]["fastq_files"][0]["md5"] == "abc"
    assert base.sra_calls == ["SRX1"]
    assert base.ena_calls == ["SRX1"]
    assert store.get("sra_xml", "SRX1")["status"] == "available"
    assert store.get("ena_fastq", "SRX1")["status"] == "available"


def test_ena_failure_preserves_sra_runs_and_records_identifier(tmp_path) -> None:
    store = CheckpointStore(tmp_path / "resume.sqlite")
    base = FakeINSDC(ena_error=requests.Timeout("ENA timeout for SRX1"))
    fetcher = CheckpointedINSDCFetcher(store, fetcher=base)

    runs = fetcher.fetch_sra_runs("SRX1")

    assert runs[0]["run"] == "SRR1"
    assert runs[0]["fastq_files"] == []
    assert store.get("sra_xml", "SRX1")["status"] == "available"
    ena = store.get("ena_fastq", "SRX1")
    assert ena["status"] == "retryable_error"
    assert ena["error"] == "ENA timeout for SRX1"


def test_sra_failure_records_exact_identifier(tmp_path) -> None:
    store = CheckpointStore(tmp_path / "resume.sqlite")
    base = FakeINSDC(sra_error=requests.Timeout("SRA timeout for SRX9"))
    fetcher = CheckpointedINSDCFetcher(store, fetcher=base)

    with pytest.raises(requests.Timeout, match="SRA timeout for SRX9"):
        fetcher.fetch_sra_runs("SRX9")

    item = store.get("sra_xml", "SRX9")
    assert item["status"] == "retryable_error"
    assert item["error"] == "SRA timeout for SRX9"
    assert store.get("ena_fastq", "SRX9") is None


def _legacy_package():
    return {
        "series": {
            "accession": [{"value": "GSE1"}],
            "pubmed_publication": [
                {
                    "pubmed_id": "123",
                    "doi": None,
                    "author_list": None,
                    "title": None,
                    "status": None,
                    "status_term_source_ref": None,
                    "status_term_accession_number": None,
                }
            ],
        },
        "sample": [
            {"sra_accession": ["SRX1"], "sra_run": []},
            {
                "sra_accession": ["SRX2"],
                "sra_run": [
                    {"run": "SRR2", "fastq_files": []},
                    {"run": "SRR3", "fastq_files": [{"uri": "ftp://ok"}]},
                ],
            },
        ],
    }


def test_audit_reports_candidates_without_mutating_checkpoints(tmp_path) -> None:
    store = CheckpointStore(tmp_path / "resume.sqlite")
    store.put(
        "geo_metadata",
        "GSE1",
        1,
        "available",
        payload={"checkpoint_version": 2, "packages": [_legacy_package()]},
    )
    before = store.items("geo_metadata")

    report = EnrichmentAuditor().audit(store)

    assert store.items("geo_metadata") == before
    assert store.items("pubmed_enrichment") == []
    assert [(item["kind"], item["identifier"], item["sample_path"]) for item in report["candidates"]] == [
        ("pubmed", "123", None),
        ("sra", "SRX1", "/sample/0"),
        ("ena", "SRX2", "/sample/1"),
    ]
    assert report["candidates"][2]["affected_run_ids"] == ["SRR2"]
    assert report["counts"] == {"pubmed": 1, "sra": 1, "ena": 1, "total": 3}


def test_retry_tag_file_validation_and_normalization(tmp_path) -> None:
    path = tmp_path / "tags.json"
    path.write_text(
        json.dumps(
            {
                "tag_id": "manual-1",
                "pubmed": ["123", "123"],
                "sra": ["srx1"],
                "ena": ["SRP2"],
            }
        ),
        encoding="utf-8",
    )

    assert load_retry_tags(path) == RetryTags(
        tag_id="manual-1", pubmed=("123",), sra=("SRX1",), ena=("SRP2",)
    )

    path.write_text(json.dumps({"tag_id": "", "pubmed": [], "sra": [], "ena": []}))
    with pytest.raises(ValueError, match="tag_id"):
        load_retry_tags(path)

    path.write_text(json.dumps({"tag_id": "x", "pubmed": ["PMID1"], "sra": [], "ena": []}))
    with pytest.raises(ValueError, match="PubMed"):
        load_retry_tags(path)


def test_new_retry_tag_forces_call_and_same_tag_is_idempotent(tmp_path) -> None:
    store = CheckpointStore(tmp_path / "resume.sqlite")
    original = FakePubmed()
    assert CheckpointedPubmedFetcher(store, fetcher=original).pubmed_summary("123") == PUBMED_RESULT

    replacement = FakePubmed(("new", None, None, None, None, None))
    forced = CheckpointedPubmedFetcher(
        store,
        fetcher=replacement,
        forced_identifiers={"123"},
        tag_id="manual-1",
    )
    assert forced.pubmed_summary("123")[0] == "new"
    assert forced.pubmed_summary("123")[0] == "new"
    assert replacement.calls == ["123"]

    later = FakePubmed(("newer", None, None, None, None, None))
    assert CheckpointedPubmedFetcher(
        store,
        fetcher=later,
        forced_identifiers={"123"},
        tag_id="manual-2",
    ).pubmed_summary("123")[0] == "newer"
    assert later.calls == ["123"]

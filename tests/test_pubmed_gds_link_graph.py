from __future__ import annotations

import requests

from ThematicAtlases.checkpoint import CheckpointStore
from ThematicAtlases.wrappers.publication_policy import PublicationRecordPolicy
from ThematicAtlases.wrappers.pubmed_gds import (
    PUBMED_GDS_DISCOVERY_CONTRACT_VERSION,
    PubMedGDSLinkGraphWrapper,
)


class Response:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


class RequestPolicy:
    max_retries = 0

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.waits = []

    def get(self, url, *, params, **kwargs):
        self.calls.append((url, params, kwargs))
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return Response(response)

    def wait(self, delay):
        self.waits.append(delay)


def publication(pmid: str, title: str = "Title") -> dict:
    return {
        "source": "MED",
        "epmc_id": pmid,
        "pmid": pmid,
        "doi": f"10.1000/{pmid}",
        "title": title,
    }


def elink_payload(mapping: dict[str, list[str]]) -> dict:
    return {
        "linksets": [
            {
                "ids": [pmid],
                "linksetdbs": ([{
                    "dbto": "gds",
                    "linkname": "pubmed_gds",
                    "links": uids,
                }] if uids else []),
            }
            for pmid, uids in mapping.items()
        ]
    }


def summary_payload(records: list[dict]) -> dict:
    return {
        "result": {
            "uids": [record["uid"] for record in records],
            **{record["uid"]: record for record in records},
        }
    }


def test_link_graph_batches_one_to_one_links_and_accepts_only_gse(tmp_path):
    policy = RequestPolicy([
        elink_payload({"1": ["101", "102"], "2": ["101", "103"]}),
        summary_payload([
            {"uid": "101", "accession": "GSE11", "entrytype": "GSE"},
            {"uid": "102", "accession": "GDS12", "entrytype": "GDS"},
            {"uid": "103", "accession": "GPL13", "entrytype": "GPL"},
        ]),
    ])
    store = CheckpointStore(tmp_path / "checkpoints.sqlite3")
    wrapper = PubMedGDSLinkGraphWrapper(
        request_policy=policy,
        request_delay=0,
    )

    records = wrapper.discover([
        publication("1", "First"),
        publication("2", "Second"),
        {"doi": "10.1000/no-pmid", "title": "No PMID"},
    ], checkpoint_store=store)

    assert [record["datalink_id"] for record in records] == ["GSE11"]
    assert [item["pmid"] for item in records[0]["publications"]] == ["1", "2"]
    assert records[0]["discovery_sources"] == ["ncbi_pubmed_gds"]
    assert records[0]["link_graph_provenance"] == [
        {
            "provider": "NCBI E-utilities",
            "origin_database": "pubmed",
            "origin_id": "1",
            "link_name": "pubmed_gds",
            "target_database": "gds",
            "target_uid": "101",
            "accession": "GSE11",
            "contract_version": PUBMED_GDS_DISCOVERY_CONTRACT_VERSION,
        },
        {
            "provider": "NCBI E-utilities",
            "origin_database": "pubmed",
            "origin_id": "2",
            "link_name": "pubmed_gds",
            "target_database": "gds",
            "target_uid": "101",
            "accession": "GSE11",
            "contract_version": PUBMED_GDS_DISCOVERY_CONTRACT_VERSION,
        },
    ]
    elink_params = policy.calls[0][1]
    assert [value for name, value in elink_params if name == "id"] == ["1", "2"]
    assert store.get("gds_summaries", "102")["status"] == "no_data"
    assert store.get("gds_summaries", "103")["status"] == "no_data"


def test_link_graph_reuses_positive_and_authoritative_negative_checkpoints(tmp_path):
    store = CheckpointStore(tmp_path / "checkpoints.sqlite3")
    first_policy = RequestPolicy([
        elink_payload({"1": [], "2": ["201"]}),
        summary_payload([
            {"uid": "201", "accession": "GSE21", "entrytype": "GSE"},
        ]),
    ])
    first = PubMedGDSLinkGraphWrapper(
        request_policy=first_policy,
        request_delay=0,
    ).discover([publication("1"), publication("2")], checkpoint_store=store)

    second_policy = RequestPolicy([])
    second = PubMedGDSLinkGraphWrapper(
        request_policy=second_policy,
        request_delay=0,
    ).discover([publication("1"), publication("2")], checkpoint_store=store)

    assert [record["datalink_id"] for record in first] == ["GSE21"]
    assert second == first
    assert second_policy.calls == []
    assert store.get("pubmed_gds_links", "1")["status"] == "no_data"


def test_link_graph_batches_publications_without_losing_input_mapping(tmp_path):
    policy = RequestPolicy([
        elink_payload({"1": ["401"], "2": ["402"]}),
        elink_payload({"3": ["403"]}),
        summary_payload([
            {"uid": "401", "accession": "GSE41", "entrytype": "GSE"},
            {"uid": "402", "accession": "GSE42", "entrytype": "GSE"},
            {"uid": "403", "accession": "GSE43", "entrytype": "GSE"},
        ]),
    ])

    records = PubMedGDSLinkGraphWrapper(
        request_policy=policy,
        request_delay=0,
        link_batch_size=2,
    ).discover(
        [publication("1"), publication("2"), publication("3")],
        checkpoint_store=CheckpointStore(tmp_path / "checkpoints.sqlite3"),
    )

    assert [record["datalink_id"] for record in records] == [
        "GSE41", "GSE42", "GSE43"
    ]
    assert [
        [value for name, value in params if name == "id"]
        for url, params, _kwargs in policy.calls
        if "elink.fcgi" in url
    ] == [["1", "2"], ["3"]]


def test_link_graph_rejects_mismatched_one_to_one_response(tmp_path):
    store = CheckpointStore(tmp_path / "checkpoints.sqlite3")
    policy = RequestPolicy([elink_payload({"999": ["401"]})])

    records = PubMedGDSLinkGraphWrapper(
        request_policy=policy,
        request_delay=0,
    ).discover([publication("1")], checkpoint_store=store)

    assert records == []
    checkpoint = store.get("pubmed_gds_links", "1")
    assert checkpoint["status"] == "terminal_error"
    assert checkpoint["error_type"] == "ValueError"

    replay_policy = RequestPolicy([])
    replayed = PubMedGDSLinkGraphWrapper(
        request_policy=replay_policy,
        request_delay=0,
    ).discover([publication("1")], checkpoint_store=store)

    assert replayed == []
    assert replay_policy.calls == []


def test_link_graph_retries_only_retryable_checkpoint_failures(tmp_path):
    store = CheckpointStore(tmp_path / "checkpoints.sqlite3")
    failed_policy = RequestPolicy([requests.Timeout("temporary")])
    first = PubMedGDSLinkGraphWrapper(
        request_policy=failed_policy,
        request_delay=0,
    ).discover([publication("1")], checkpoint_store=store)

    resumed_policy = RequestPolicy([
        elink_payload({"1": ["501"]}),
        summary_payload([
            {"uid": "501", "accession": "GSE51", "entrytype": "GSE"},
        ]),
    ])
    second = PubMedGDSLinkGraphWrapper(
        request_policy=resumed_policy,
        request_delay=0,
    ).discover([publication("1")], checkpoint_store=store)

    assert first == []
    assert [record["datalink_id"] for record in second] == ["GSE51"]
    assert len(resumed_policy.calls) == 2


def test_link_graph_resumes_summary_after_interruption_without_repeating_elink(tmp_path):
    store = CheckpointStore(tmp_path / "checkpoints.sqlite3")
    interrupted = RequestPolicy([
        elink_payload({"1": ["301"]}),
        KeyboardInterrupt(),
    ])
    wrapper = PubMedGDSLinkGraphWrapper(
        request_policy=interrupted,
        request_delay=0,
    )

    try:
        wrapper.discover([publication("1")], checkpoint_store=store)
    except KeyboardInterrupt:
        pass
    else:
        raise AssertionError("expected interruption")

    resumed = RequestPolicy([
        summary_payload([
            {"uid": "301", "accession": "GSE31", "entrytype": "GSE"},
        ]),
    ])
    records = PubMedGDSLinkGraphWrapper(
        request_policy=resumed,
        request_delay=0,
    ).discover([publication("1")], checkpoint_store=store)

    assert [record["datalink_id"] for record in records] == ["GSE31"]
    assert "esummary.fcgi" in resumed.calls[0][0]
    assert all("elink.fcgi" not in call[0] for call in resumed.calls)


def test_link_graph_cached_only_never_requests_missing_stages(tmp_path):
    policy = RequestPolicy([])
    records = PubMedGDSLinkGraphWrapper(
        request_policy=policy,
        request_delay=0,
    ).discover(
        [publication("1")],
        checkpoint_store=CheckpointStore(tmp_path / "checkpoints.sqlite3"),
        cached_only=True,
    )

    assert records == []
    assert policy.calls == []


def test_link_graph_yields_before_claiming_a_new_batch(tmp_path):
    policy = RequestPolicy([])
    store = CheckpointStore(tmp_path / "checkpoints.sqlite3")

    records = PubMedGDSLinkGraphWrapper(
        request_policy=policy,
        request_delay=0,
    ).discover(
        [publication("1")],
        checkpoint_store=store,
        continue_predicate=lambda: False,
    )

    assert records == []
    assert policy.calls == []
    assert store.get("pubmed_gds_links", "1") is None


def test_link_graph_rechecks_phase_after_claim_before_provider_call(tmp_path):
    policy = RequestPolicy([])
    store = CheckpointStore(tmp_path / "checkpoints.sqlite3")
    decisions = iter((True, False))

    records = PubMedGDSLinkGraphWrapper(
        request_policy=policy,
        request_delay=0,
    ).discover(
        [publication("1")],
        checkpoint_store=store,
        continue_predicate=lambda: next(decisions),
    )

    assert records == []
    assert policy.calls == []
    assert store.get("pubmed_gds_links", "1") is None


def test_link_graph_defers_a_batch_owned_by_another_process(tmp_path):
    policy = RequestPolicy([])
    store = CheckpointStore(
        tmp_path / "checkpoints.sqlite3",
        default_item_lock_timeout_seconds=0.01,
    )
    wrapper = PubMedGDSLinkGraphWrapper(
        request_policy=policy,
        request_delay=0,
    )

    with store.item_lock("pubmed_gds_links", "1"):
        records = wrapper.discover(
            [publication("1")],
            checkpoint_store=store,
        )

    assert records == []
    assert policy.calls == []
    assert store.get("pubmed_gds_links", "1") is None


def test_link_graph_checkpoints_sanitized_batch_failure(tmp_path):
    store = CheckpointStore(tmp_path / "checkpoints.sqlite3")
    policy = RequestPolicy([requests.Timeout("private upstream detail")])

    records = PubMedGDSLinkGraphWrapper(
        request_policy=policy,
        request_delay=0,
    ).discover([publication("1"), publication("2")], checkpoint_store=store)

    assert records == []
    for pmid in ("1", "2"):
        item = store.get("pubmed_gds_links", pmid)
        assert item["status"] == "retryable_error"
        assert "private upstream detail" not in str(item.get("error"))


def test_link_graph_recovers_legacy_terminal_chunked_transfer_checkpoint(tmp_path):
    store = CheckpointStore(tmp_path / "checkpoints.sqlite3")
    store.put(
        "pubmed_gds_links",
        "1",
        1,
        "terminal_error",
        payload={"contract_version": PUBMED_GDS_DISCOVERY_CONTRACT_VERSION},
        error_type="ChunkedEncodingError",
        failure_category="permanent",
    )
    policy = RequestPolicy([elink_payload({"1": []})])

    records = PubMedGDSLinkGraphWrapper(
        request_policy=policy,
        request_delay=0,
    ).discover([publication("1")], checkpoint_store=store)

    assert records == []
    assert len(policy.calls) == 1
    assert store.get("pubmed_gds_links", "1")["status"] == "no_data"


def test_link_graph_splits_truncated_batch_without_poisoning_all_pmids(tmp_path):
    store = CheckpointStore(tmp_path / "checkpoints.sqlite3")
    policy = RequestPolicy(
        [
            requests.exceptions.ChunkedEncodingError("truncated batch"),
            elink_payload({"1": [], "2": []}),
            elink_payload({"3": [], "4": []}),
        ]
    )

    records = PubMedGDSLinkGraphWrapper(
        request_policy=policy,
        request_delay=0,
        link_batch_size=4,
    ).discover(
        [publication(str(value)) for value in range(1, 5)],
        checkpoint_store=store,
    )

    assert records == []
    assert len(policy.calls) == 3
    assert [
        store.get("pubmed_gds_links", str(value))["status"]
        for value in range(1, 5)
    ] == ["no_data"] * 4


def test_link_graph_splits_only_once_and_defers_still_malformed_subbatches(
    tmp_path,
):
    store = CheckpointStore(tmp_path / "checkpoints.sqlite3")
    policy = RequestPolicy(
        [
            {"unexpected": "whole batch"},
            {"unexpected": "first half"},
            {"unexpected": "second half"},
        ]
    )

    PubMedGDSLinkGraphWrapper(
        request_policy=policy,
        request_delay=0,
        link_batch_size=8,
    ).discover(
        [publication(str(value)) for value in range(1, 9)],
        checkpoint_store=store,
    )

    assert len(policy.calls) == 3
    assert [
        store.get("pubmed_gds_links", str(value))["status"]
        for value in range(1, 9)
    ] == ["retryable_error"] * 8
    assert store.get_meta("pubmed_gds_recommended_link_batch_size") == 4


def test_link_graph_isolates_malformed_singleton_as_terminal(tmp_path):
    store = CheckpointStore(tmp_path / "checkpoints.sqlite3")
    policy = RequestPolicy([{"unexpected": "payload"}])

    PubMedGDSLinkGraphWrapper(
        request_policy=policy,
        request_delay=0,
    ).discover([publication("1")], checkpoint_store=store)

    item = store.get("pubmed_gds_links", "1")
    assert item["status"] == "terminal_error"
    assert item["error_type"] == "ValueError"


def test_publication_policy_merges_graph_after_datalink_and_text_provenance():
    publication_record = publication("1")
    datalink = {
        "datalink_id": "GSE1",
        "publications": [publication_record],
    }
    text = {
        "datalink_id": "gse1",
        "discovery_sources": ["fulltext_regex"],
        "publications": [{
            **publication_record,
            "accession_discovery_sources": ["fulltext_regex"],
        }],
    }
    graph = {
        "datalink_id": "GSE1",
        "discovery_sources": ["ncbi_pubmed_gds"],
        "publications": [{
            **publication_record,
            "accession_discovery_sources": ["ncbi_pubmed_gds"],
        }],
    }

    merged = PublicationRecordPolicy().merge_accessions(
        [datalink], [text], [graph]
    )

    assert len(merged) == 1
    assert merged[0]["discovery_sources"] == [
        "europe_pmc_datalink", "fulltext_regex", "ncbi_pubmed_gds"
    ]
    assert merged[0]["publications"][0]["accession_discovery_sources"] == [
        "europe_pmc_datalink", "fulltext_regex", "ncbi_pubmed_gds"
    ]

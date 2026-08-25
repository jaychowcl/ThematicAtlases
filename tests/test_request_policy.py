import requests
import pytest
import multiprocessing
import time
import logging
from meta_standards_converter.helpers.request_helper import (
    HostRequestCooldownDeferred,
    HostRequestGate,
    RateLimitedRequester,
    RequestSettings,
)

from ThematicAtlases.infrastructure import RequestPolicy
from ThematicAtlases.infrastructure.http import (
    RequestSecurityError,
    ResponseSizeLimitError,
)


class Response:
    def __init__(self, status_code=200, headers=None):
        self.status_code = status_code
        self.headers = headers or {}
        self.raise_calls = 0

    def raise_for_status(self):
        self.raise_calls += 1

    def close(self):
        pass


class StreamingResponse(Response):
    def __init__(self, body, headers):
        super().__init__(200, headers)
        self.body = body

    def iter_content(self, chunk_size):
        yield self.body


class RecordingGate:
    def __init__(self):
        self.waits = []
        self.cooldowns = []

    def wait(self, key, **kwargs):
        self.waits.append((key, kwargs))
        return 0.25

    def defer(self, key, **kwargs):
        self.cooldowns.append((key, kwargs))
        return kwargs["delay_seconds"]


def _take_thematic_atlas_ncbi_slot(directory, barrier, output):
    policy = RequestPolicy(
        max_retries=0,
        request_get=lambda **_kwargs: Response(200),
        host_gate=HostRequestGate(directory=directory),
        host_start_intervals={"eutils.ncbi.nlm.nih.gov": 0.05},
    )
    barrier.wait(timeout=5)
    policy.get("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi")
    output.put(time.time())


def _take_msc_ncbi_slot(directory, barrier, output):
    requester = RateLimitedRequester(
        service="ncbi_eutils",
        settings=RequestSettings(request_delay=0.05, max_retries=0),
        get=lambda *_args, **_kwargs: Response(200),
        host_gate=HostRequestGate(directory=directory),
    )
    barrier.wait(timeout=5)
    requester.get("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi")
    output.put(time.time())


def test_request_policy_retries_declared_status_with_retry_after():
    responses = [Response(429, {"Retry-After": "3"}), Response(200)]
    sleeps = []
    calls = []

    policy = RequestPolicy(
        timeout=12,
        max_retries=1,
        request_get=lambda **kwargs: calls.append(kwargs) or responses.pop(0),
        sleep=sleeps.append,
        allowed_hosts={"example.test"},
    )

    response = policy.get("https://example.test", params={"q": "lung"})

    assert response.status_code == 200
    assert sleeps == [3.0]
    assert calls == [
        {
            "url": "https://example.test",
            "params": {"q": "lung"},
            "timeout": 12,
            "allow_redirects": False,
            "stream": True,
        },
        {
            "url": "https://example.test",
            "params": {"q": "lung"},
            "timeout": 12,
            "allow_redirects": False,
            "stream": True,
        },
    ]


def test_request_policy_preserves_repeated_parameter_pairs():
    calls = []
    parameters = [
        ("dbfrom", "pubmed"),
        ("linkname", "pubmed_gds"),
        ("id", "1"),
        ("id", "2"),
    ]
    policy = RequestPolicy(
        max_retries=0,
        request_get=lambda **kwargs: calls.append(kwargs) or Response(),
        allowed_hosts={"example.test"},
    )

    policy.get("https://example.test/elink.fcgi", params=parameters)

    assert calls[0]["params"] == parameters


def test_request_policy_per_call_retry_limit_does_not_mutate_default():
    responses = [Response(503), Response(200)]
    sleeps = []
    calls = []
    policy = RequestPolicy(
        max_retries=3,
        request_get=lambda **kwargs: calls.append(kwargs) or responses.pop(0),
        sleep=sleeps.append,
        allowed_hosts={"example.test"},
    )

    response = policy.get(
        "https://example.test",
        max_retries=0,
        raise_for_status=False,
    )

    assert response.status_code == 503
    assert len(calls) == 1
    assert sleeps == []
    assert policy.max_retries == 3


def test_request_policy_rejects_negative_per_call_retry_limit():
    policy = RequestPolicy(
        request_get=lambda **_kwargs: pytest.fail("must not request"),
        allowed_hosts={"example.test"},
    )

    with pytest.raises(ValueError, match="max_retries must not be negative"):
        policy.get("https://example.test", max_retries=-1)


def test_request_policy_wait_uses_injected_sleeper():
    sleeps = []
    policy = RequestPolicy(
        sleep=sleeps.append,
        allowed_hosts={"example.test"},
    )

    policy.wait(1.25)

    assert sleeps == [1.25]


def test_request_policy_rejects_negative_wait():
    policy = RequestPolicy(allowed_hosts={"example.test"})

    with pytest.raises(ValueError, match="delay must not be negative"):
        policy.wait(-0.1)


def test_request_policy_exception_retry_and_final_status_are_caller_controlled():
    outcomes = [requests.Timeout("slow"), Response(503)]
    sleeps = []

    def request_get(**_kwargs):
        value = outcomes.pop(0)
        if isinstance(value, Exception):
            raise value
        return value

    response = RequestPolicy(
        max_retries=1,
        request_get=request_get,
        sleep=sleeps.append,
        random_value=lambda: 1.0,
        allowed_hosts={"example.test"},
    ).get(
        "https://example.test",
        retry_exceptions=True,
        raise_for_status=False,
    )

    assert response.status_code == 503
    assert sleeps == [0.5]
    assert response.raise_calls == 0


def test_retry_after_never_returns_negative_delay():
    assert RequestPolicy.retry_delay(Response(429, {"Retry-After": "-3"}), 0) == 0


def test_retry_after_http_date_is_parsed_and_bounded():
    assert RequestPolicy.retry_delay(
        Response(429, {"Retry-After": "Wed, 21 Oct 2099 07:28:00 GMT"}), 0
    ) > 8


def test_retry_after_past_inline_budget_is_persisted_and_deferred():
    calls = []
    policy = RequestPolicy(
        max_retries=2,
        max_inline_wait=30,
        request_get=lambda **kwargs: calls.append(kwargs)
        or Response(429, {"Retry-After": "60"}),
        allowed_hosts={"example.test"},
    )

    with pytest.raises(HostRequestCooldownDeferred):
        policy.get("https://example.test")

    assert len(calls) == 1
    assert policy.retry_count == 1


def test_request_policy_uses_typed_profile_timeouts_by_default():
    calls = []
    RequestPolicy(
        max_retries=0,
        request_get=lambda **kwargs: calls.append(kwargs) or Response(),
        allowed_hosts={"example.test"},
        resource_profile="large",
    ).get("https://example.test")

    assert calls[0]["timeout"] == (30, 300)


def test_request_policy_rejects_unapproved_hosts_before_request():
    with pytest.raises(RequestSecurityError, match="host is not allowed"):
        RequestPolicy(
            request_get=lambda **_kwargs: pytest.fail("must not request"),
        ).get("https://127.0.0.1/private")


def test_request_policy_rejects_cross_host_redirect():
    response = Response(302, {"Location": "https://127.0.0.1/private"})
    with pytest.raises(RequestSecurityError, match="host is not allowed"):
        RequestPolicy(
            max_retries=0,
            request_get=lambda **_kwargs: response,
            allowed_hosts={"example.test"},
        ).get("https://example.test/start")


def test_request_policy_gates_every_actual_redirect_attempt():
    responses = [
        Response(302, {"Location": "https://example.test/final"}),
        Response(200),
    ]
    gate = RecordingGate()
    policy = RequestPolicy(
        max_retries=0,
        request_get=lambda **_kwargs: responses.pop(0),
        host_gate=gate,
        allowed_hosts={"example.test"},
    )

    assert policy.get("https://example.test/start").status_code == 200
    assert [key for key, _kwargs in gate.waits] == [
        "example.test",
        "example.test",
    ]
    assert policy.provider_attempts == 2
    assert policy.rate_wait_seconds == 0.5


def test_default_europe_pmc_start_interval_is_half_a_second():
    assert RequestPolicy()._host_interval("www.ebi.ac.uk") == 0.5


def test_request_policy_logs_no_api_key_or_query_value(caplog):
    responses = [Response(503), Response(200)]
    logger = logging.getLogger("tests.safe_request_policy")
    policy = RequestPolicy(
        max_retries=1,
        request_get=lambda **_kwargs: responses.pop(0),
        allowed_hosts={"example.test"},
        logger=logger,
        random_value=lambda: 0,
    )

    with caplog.at_level("DEBUG", logger=logger.name):
        policy.get(
            "https://example.test/data?api_key=secret-key",
            params={"query": "private-query"},
            raise_for_status=False,
        )

    assert "secret-key" not in caplog.text
    assert "private-query" not in caplog.text


def test_thematic_atlas_and_msc_share_ncbi_gate_across_processes(tmp_path):
    context = multiprocessing.get_context("fork")
    barrier = context.Barrier(2)
    output = context.Queue()
    processes = [
        context.Process(
            target=target,
            args=(str(tmp_path / "shared-gate"), barrier, output),
        )
        for target in (_take_thematic_atlas_ncbi_slot, _take_msc_ncbi_slot)
    ]

    for process in processes:
        process.start()
    timestamps = sorted(output.get(timeout=5) for _ in processes)
    for process in processes:
        process.join(timeout=5)
        assert process.exitcode == 0

    assert timestamps[1] - timestamps[0] >= 0.04


def test_request_policy_rejects_declared_oversized_response():
    response = Response(200, {"Content-Length": "65"})
    with pytest.raises(ResponseSizeLimitError, match="exceeds"):
        RequestPolicy(
            max_retries=0,
            request_get=lambda **_kwargs: response,
            allowed_hosts={"example.test"},
            resource_overrides={"max_xml_bytes": 64},
        ).get("https://example.test/data")


def test_request_policy_accepts_compressed_length_distinct_from_decoded_body():
    body = b"<article><body>decoded JATS</body></article>"
    response = StreamingResponse(
        body,
        {"Content-Length": "12", "Content-Encoding": "gzip"},
    )

    returned = RequestPolicy(
        max_retries=0,
        request_get=lambda **_kwargs: response,
        allowed_hosts={"example.test"},
        resource_overrides={"max_xml_bytes": 64},
    ).get("https://example.test/data")

    assert returned._content == body

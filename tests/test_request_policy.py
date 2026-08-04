import requests

from ThematicAtlases.infrastructure import RequestPolicy


class Response:
    def __init__(self, status_code=200, headers=None):
        self.status_code = status_code
        self.headers = headers or {}
        self.raise_calls = 0

    def raise_for_status(self):
        self.raise_calls += 1


def test_request_policy_retries_declared_status_with_retry_after():
    responses = [Response(429, {"Retry-After": "3"}), Response(200)]
    sleeps = []
    calls = []

    policy = RequestPolicy(
        timeout=12,
        max_retries=1,
        request_get=lambda **kwargs: calls.append(kwargs) or responses.pop(0),
        sleep=sleeps.append,
    )

    response = policy.get("https://example.test", params={"q": "lung"})

    assert response.status_code == 200
    assert sleeps == [3.0]
    assert calls == [
        {"url": "https://example.test", "params": {"q": "lung"}, "timeout": 12},
        {"url": "https://example.test", "params": {"q": "lung"}, "timeout": 12},
    ]


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
    ) == 8

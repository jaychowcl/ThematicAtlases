"""Shared bounded HTTP retry policy for repository adapters."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
import inspect
import logging
import random
import time
from typing import Any
from urllib.parse import urljoin, urlsplit

import requests
from meta_standards_converter.helpers.request_helper import (
    HostRequestCooldownDeferred,
    HostRequestGate,
)
from meta_standards_converter.runtime_contracts import (
    ResourceProfile,
    get_resource_profile,
)


DEFAULT_ALLOWED_HOST_SUFFIXES = frozenset(
    {
        "ebi.ac.uk",
        "ncbi.nlm.nih.gov",
        "biorxiv.org",
        "medrxiv.org",
    }
)
RequestParameters = Mapping[str, Any] | Sequence[tuple[str, Any]]
REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
DEFAULT_HOST_START_INTERVALS = {
    "eutils.ncbi.nlm.nih.gov": 0.5,
    "europepmc.org": 0.5,
    "api.biorxiv.org": 1.0,
    "biorxiv.org": 1.0,
    "medrxiv.org": 1.0,
    "ftp.ncbi.nlm.nih.gov": 1.0,
    "ftp.ebi.ac.uk": 1.0,
    "www.ebi.ac.uk": 0.5,
}


class RequestSecurityError(RuntimeError):
    """A request or redirect crossed the configured egress boundary."""


class ResponseSizeLimitError(RuntimeError):
    """A response or aggregate run exceeded the selected resource profile."""


class RequestPolicy:
    """Issue GET requests with explicit, bounded retry behavior."""

    def __init__(
        self,
        *,
        timeout: int | float | tuple[int | float, int | float] | None = None,
        max_retries: int = 3,
        retry_statuses: frozenset[int] | set[int] = frozenset(
            {403, 408, 425, 429, 500, 502, 503, 504}
        ),
        request_get: Callable[..., Any] | None = None,
        sleep: Callable[[float], None] = time.sleep,
        logger: logging.Logger | None = None,
        name: str = "HTTP",
        resource_profile: str | ResourceProfile = "standard",
        resource_overrides: Mapping[str, int | float] | None = None,
        allowed_hosts: set[str] | frozenset[str] = frozenset(),
        allowed_host_suffixes: set[str] | frozenset[str] = (
            DEFAULT_ALLOWED_HOST_SUFFIXES
        ),
        host_gate: HostRequestGate | Any | None = None,
        host_start_intervals: Mapping[str, int | float] | None = None,
        max_inline_wait: int | float = 30,
        random_value: Callable[[], float] = random.random,
    ) -> None:
        self.resource_profile = (
            resource_profile.with_overrides(resource_overrides or {})
            if isinstance(resource_profile, ResourceProfile)
            else get_resource_profile(
                resource_profile,
                overrides=resource_overrides,
            )
        )
        if timeout is None:
            timeout = (
                self.resource_profile.connect_timeout_seconds,
                self.resource_profile.read_timeout_seconds,
            )
        timeout_values = timeout if isinstance(timeout, tuple) else (timeout,)
        if not timeout_values or any(value <= 0 for value in timeout_values):
            raise ValueError("timeout must be positive")
        if max_retries < 0:
            raise ValueError("max_retries must not be negative")
        if max_inline_wait < 0:
            raise ValueError("max_inline_wait must not be negative")
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_statuses = frozenset(retry_statuses)
        self._request_get = request_get
        self._sleep = sleep
        self._logger = logger or logging.getLogger(__name__)
        self._name = name
        self._host_gate = host_gate or HostRequestGate.default()
        self._host_start_intervals = {
            str(host).casefold().lstrip(".").rstrip("."): float(interval)
            for host, interval in (
                host_start_intervals or DEFAULT_HOST_START_INTERVALS
            ).items()
        }
        if any(interval < 0 for interval in self._host_start_intervals.values()):
            raise ValueError("host start intervals must not be negative")
        self.max_inline_wait = float(max_inline_wait)
        self._random_value = random_value
        self._wall_clock_offset = 0.0
        self.allowed_hosts = frozenset(
            str(host).casefold().rstrip(".") for host in allowed_hosts
        )
        self.allowed_host_suffixes = frozenset(
            str(host).casefold().lstrip(".").rstrip(".")
            for host in allowed_host_suffixes
        )
        self._response_bytes = 0
        self.provider_attempts = 0
        self.retry_count = 0
        self.rate_wait_seconds = 0.0

    def get(
        self,
        url: str,
        *,
        params: RequestParameters | None = None,
        retry_exceptions: bool = False,
        raise_for_status: bool = True,
        max_retries: int | None = None,
    ) -> Any:
        """Return the final response or propagate its terminal failure."""

        retry_limit = self.max_retries if max_retries is None else max_retries
        if retry_limit < 0:
            raise ValueError("max_retries must not be negative")
        self._validate_url(url)
        for attempt in range(retry_limit + 1):
            try:
                response = self._request_with_redirects(url, params=params)
            except requests.RequestException as error:
                if not retry_exceptions or attempt >= retry_limit:
                    raise
                delay = self.retry_delay(
                    None,
                    attempt,
                    random_value=self._random_value,
                )
                host = (urlsplit(url).hostname or "").casefold().rstrip(".")
                retry_at = self._host_gate.defer(
                    host,
                    delay_seconds=delay,
                    clock=self._wall_clock,
                )
                self.retry_count += 1
                self._logger.debug(
                    "%s retry error_type=%s attempt=%s delay=%s",
                    self._name,
                    type(error).__name__,
                    attempt + 1,
                    delay,
                )
                if delay > self.max_inline_wait:
                    raise HostRequestCooldownDeferred(host, retry_at) from error
                self._sleep_and_advance(delay)
                self.rate_wait_seconds += delay
                continue

            if response.status_code in self.retry_statuses and attempt < retry_limit:
                delay = self.retry_delay(
                    response,
                    attempt,
                    random_value=self._random_value,
                )
                host = (urlsplit(url).hostname or "").casefold().rstrip(".")
                retry_at = self._host_gate.defer(
                    host,
                    delay_seconds=delay,
                    clock=self._wall_clock,
                )
                self.retry_count += 1
                self._logger.debug(
                    "%s retry status=%s attempt=%s delay=%s",
                    self._name,
                    response.status_code,
                    attempt + 1,
                    delay,
                )
                self._close(response)
                if delay > self.max_inline_wait:
                    raise HostRequestCooldownDeferred(host, retry_at)
                self._sleep_and_advance(delay)
                self.rate_wait_seconds += delay
                continue
            if response.status_code in {403, 429}:
                delay = self.retry_delay(
                    response,
                    attempt,
                    random_value=self._random_value,
                )
                retry_at = self._host_gate.defer(
                    (urlsplit(url).hostname or "").casefold().rstrip("."),
                    delay_seconds=delay,
                    clock=self._wall_clock,
                )
                setattr(response, "_thematic_atlases_retry_at", retry_at)
            if raise_for_status:
                response.raise_for_status()
            self._enforce_response_limit(response)
            return response
        raise RuntimeError("bounded HTTP retry loop terminated without a response")

    def wait(self, delay: int | float) -> None:
        """Wait through the injected sleeper before another provider request."""

        if delay < 0:
            raise ValueError("delay must not be negative")
        self._sleep_and_advance(float(delay))

    def defer_retry(
        self,
        url: str,
        *,
        response: Any | None,
        attempt: int,
    ) -> float:
        """Persist one retry cooldown and honor it within the inline budget."""

        self._validate_url(url)
        host = (urlsplit(url).hostname or "").casefold().rstrip(".")
        delay = self.retry_delay(
            response,
            attempt,
            random_value=self._random_value,
        )
        retry_at = self._host_gate.defer(
            host,
            delay_seconds=delay,
            clock=self._wall_clock,
        )
        self.retry_count += 1
        if delay > self.max_inline_wait:
            raise HostRequestCooldownDeferred(host, retry_at)
        self._sleep_and_advance(delay)
        self.rate_wait_seconds += delay
        return delay

    def _wall_clock(self) -> float:
        return time.time() + self._wall_clock_offset

    def _sleep_and_advance(self, delay: float) -> None:
        started = time.time()
        self._sleep(float(delay))
        elapsed = max(time.time() - started, 0.0)
        self._wall_clock_offset += max(float(delay) - elapsed, 0.0)

    def _request_with_redirects(
        self,
        url: str,
        *,
        params: RequestParameters | None,
    ) -> Any:
        current = url
        for redirect_count in range(self.resource_profile.max_redirects + 1):
            self._validate_url(current)
            arguments: dict[str, Any] = {
                "url": current,
                "timeout": self.timeout,
            }
            if redirect_count == 0 and params is not None:
                arguments["params"] = (
                    dict(params) if isinstance(params, Mapping) else list(params)
                )
            request_get = self._request_get or requests.get
            self._add_supported_argument(
                request_get, arguments, "allow_redirects", False
            )
            self._add_supported_argument(request_get, arguments, "stream", True)
            host = (urlsplit(current).hostname or "").casefold().rstrip(".")
            waited = self._host_gate.wait(
                host,
                min_interval_seconds=self._host_interval(host),
                max_wait_seconds=self.max_inline_wait,
                sleep=self._sleep_and_advance,
                clock=self._wall_clock,
            )
            self.rate_wait_seconds += float(waited)
            self.provider_attempts += 1
            response = request_get(**arguments)
            if response.status_code not in REDIRECT_STATUSES:
                return response
            location = response.headers.get("Location")
            self._close(response)
            if not location:
                raise RequestSecurityError("redirect response omitted Location")
            if redirect_count >= self.resource_profile.max_redirects:
                raise RequestSecurityError("response exceeded redirect limit")
            target = urljoin(current, str(location))
            if urlsplit(target).scheme.casefold() != "https":
                raise RequestSecurityError("redirect target must use HTTPS")
            self._validate_url(target)
            current = target
        raise RequestSecurityError("response exceeded redirect limit")

    @staticmethod
    def _add_supported_argument(
        request_get: Callable[..., Any],
        arguments: dict[str, Any],
        name: str,
        value: Any,
    ) -> None:
        try:
            parameters = inspect.signature(request_get).parameters.values()
        except (TypeError, ValueError):
            parameters = ()
        if any(
            parameter.kind == inspect.Parameter.VAR_KEYWORD
            or parameter.name == name
            for parameter in parameters
        ):
            arguments[name] = value

    def _validate_url(self, value: str) -> None:
        parsed = urlsplit(value)
        if parsed.scheme.casefold() != "https":
            raise RequestSecurityError("request URL must use HTTPS")
        if parsed.username is not None or parsed.password is not None:
            raise RequestSecurityError("request URL must not contain credentials")
        host = (parsed.hostname or "").casefold().rstrip(".")
        if not host or not (
            host in self.allowed_hosts
            or any(
                host == suffix or host.endswith(f".{suffix}")
                for suffix in self.allowed_host_suffixes
            )
        ):
            raise RequestSecurityError(f"request host is not allowed: {host}")

    def _host_interval(self, host: str) -> float:
        matches = [
            interval
            for suffix, interval in self._host_start_intervals.items()
            if host == suffix or host.endswith(f".{suffix}")
        ]
        return max(matches, default=0.0)

    def _enforce_response_limit(self, response: Any) -> None:
        limit = self.resource_profile.max_xml_bytes
        raw_length = response.headers.get("Content-Length")
        raw_encoding = response.headers.get("Content-Encoding")
        content_length_describes_decoded_body = (
            str(raw_encoding or "").strip().casefold() in {"", "identity"}
        )
        declared = None
        if raw_length not in {None, ""}:
            try:
                declared = int(raw_length)
            except (TypeError, ValueError) as error:
                raise ResponseSizeLimitError(
                    "response Content-Length is invalid"
                ) from error
            if declared < 0 or declared > limit:
                raise ResponseSizeLimitError(
                    f"response declares {declared} bytes and exceeds the {limit} byte limit"
                )
        iter_content = getattr(response, "iter_content", None)
        if not callable(iter_content):
            self._account_response_bytes(declared or 0)
            return
        content = bytearray()
        for chunk in iter_content(chunk_size=1024 * 1024):
            if not chunk:
                continue
            content.extend(chunk)
            if len(content) > limit:
                raise ResponseSizeLimitError(
                    f"response exceeds the {limit} byte limit"
                )
        if (
            declared is not None
            and content_length_describes_decoded_body
            and len(content) != declared
        ):
            raise ResponseSizeLimitError(
                "response body size does not match Content-Length"
            )
        response._content = bytes(content)
        response._content_consumed = True
        self._account_response_bytes(len(content))

    def _account_response_bytes(self, byte_count: int) -> None:
        self._response_bytes += byte_count
        if self._response_bytes > self.resource_profile.max_aggregate_download_bytes:
            raise ResponseSizeLimitError(
                "aggregate response bytes exceed the selected resource profile"
            )

    @staticmethod
    def _close(response: Any) -> None:
        close = getattr(response, "close", None)
        if callable(close):
            close()

    @staticmethod
    def retry_delay(
        response: Any | None,
        attempt: int,
        *,
        random_value: Callable[[], float] = lambda: 1.0,
    ) -> float:
        retry_after = None if response is None else response.headers.get("Retry-After")
        parsed = HostRequestGate.retry_after_seconds(retry_after)
        if parsed is not None:
            return parsed
        jitter = float(random_value())
        if not 0 <= jitter <= 1:
            raise ValueError("random_value must return a number between zero and one")
        return min(0.5 * (2**attempt), 8.0) * jitter


__all__ = [
    "RequestPolicy",
    "RequestSecurityError",
    "ResponseSizeLimitError",
]

"""Shared bounded HTTP retry policy for repository adapters."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import inspect
import logging
import time
from typing import Any
from urllib.parse import urljoin, urlsplit

import requests
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
REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})


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
            {429, 500, 502, 503, 504}
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
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_statuses = frozenset(retry_statuses)
        self._request_get = request_get
        self._sleep = sleep
        self._logger = logger or logging.getLogger(__name__)
        self._name = name
        self.allowed_hosts = frozenset(
            str(host).casefold().rstrip(".") for host in allowed_hosts
        )
        self.allowed_host_suffixes = frozenset(
            str(host).casefold().lstrip(".").rstrip(".")
            for host in allowed_host_suffixes
        )
        self._response_bytes = 0

    def get(
        self,
        url: str,
        *,
        params: Mapping[str, Any] | None = None,
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
                delay = self.retry_delay(None, attempt)
                self._logger.debug(
                    "%s retry error_type=%s attempt=%s delay=%s",
                    self._name,
                    type(error).__name__,
                    attempt + 1,
                    delay,
                )
                self.wait(delay)
                continue

            if response.status_code in self.retry_statuses and attempt < retry_limit:
                delay = self.retry_delay(response, attempt)
                self._logger.debug(
                    "%s retry status=%s attempt=%s delay=%s",
                    self._name,
                    response.status_code,
                    attempt + 1,
                    delay,
                )
                self._close(response)
                self.wait(delay)
                continue
            if raise_for_status:
                response.raise_for_status()
            self._enforce_response_limit(response)
            return response
        raise RuntimeError("bounded HTTP retry loop terminated without a response")

    def wait(self, delay: int | float) -> None:
        """Wait through the injected sleeper before another provider request."""

        if delay < 0:
            raise ValueError("delay must not be negative")
        self._sleep(float(delay))

    def _request_with_redirects(
        self,
        url: str,
        *,
        params: Mapping[str, Any] | None,
    ) -> Any:
        current = url
        for redirect_count in range(self.resource_profile.max_redirects + 1):
            self._validate_url(current)
            arguments: dict[str, Any] = {
                "url": current,
                "timeout": self.timeout,
            }
            if redirect_count == 0 and params is not None:
                arguments["params"] = dict(params)
            request_get = self._request_get or requests.get
            self._add_supported_argument(
                request_get, arguments, "allow_redirects", False
            )
            self._add_supported_argument(request_get, arguments, "stream", True)
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
    def retry_delay(response: Any | None, attempt: int) -> float:
        retry_after = None if response is None else response.headers.get("Retry-After")
        if retry_after is not None:
            try:
                delay = float(retry_after)
            except (TypeError, ValueError):
                try:
                    retry_at = parsedate_to_datetime(str(retry_after))
                    if retry_at.tzinfo is None:
                        retry_at = retry_at.replace(tzinfo=timezone.utc)
                    delay = (retry_at - datetime.now(timezone.utc)).total_seconds()
                except (TypeError, ValueError, OverflowError):
                    delay = None
            if delay is not None:
                return min(max(delay, 0.0), 8.0)
        return min(0.5 * (2**attempt), 8.0)


__all__ = [
    "RequestPolicy",
    "RequestSecurityError",
    "ResponseSizeLimitError",
]

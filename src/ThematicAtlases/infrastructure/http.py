"""Shared bounded HTTP retry policy for repository adapters."""

from __future__ import annotations

from collections.abc import Callable, Mapping
import logging
import time
from typing import Any

import requests


class RequestPolicy:
    """Issue GET requests with explicit, bounded retry behavior."""

    def __init__(
        self,
        *,
        timeout: int | float = 30,
        max_retries: int = 3,
        retry_statuses: frozenset[int] | set[int] = frozenset(
            {429, 500, 502, 503, 504}
        ),
        request_get: Callable[..., Any] | None = None,
        sleep: Callable[[float], None] = time.sleep,
        logger: logging.Logger | None = None,
        name: str = "HTTP",
    ) -> None:
        if timeout <= 0:
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

    def get(
        self,
        url: str,
        *,
        params: Mapping[str, Any] | None = None,
        retry_exceptions: bool = False,
        raise_for_status: bool = True,
    ) -> Any:
        """Return the final response or propagate its terminal failure."""

        for attempt in range(self.max_retries + 1):
            request_get = self._request_get or requests.get
            arguments: dict[str, Any] = {"url": url, "timeout": self.timeout}
            if params is not None:
                arguments["params"] = dict(params)
            try:
                response = request_get(**arguments)
            except requests.RequestException as error:
                if not retry_exceptions or attempt >= self.max_retries:
                    raise
                delay = self.retry_delay(None, attempt)
                self._logger.debug(
                    "%s retry error=%r attempt=%s delay=%s",
                    self._name,
                    error,
                    attempt + 1,
                    delay,
                )
                self._sleep(delay)
                continue

            if response.status_code in self.retry_statuses and attempt < self.max_retries:
                delay = self.retry_delay(response, attempt)
                self._logger.debug(
                    "%s retry status=%s attempt=%s delay=%s",
                    self._name,
                    response.status_code,
                    attempt + 1,
                    delay,
                )
                self._sleep(delay)
                continue
            if raise_for_status:
                response.raise_for_status()
            return response
        raise RuntimeError("bounded HTTP retry loop terminated without a response")

    @staticmethod
    def retry_delay(response: Any | None, attempt: int) -> float:
        retry_after = None if response is None else response.headers.get("Retry-After")
        if retry_after is not None:
            try:
                return float(retry_after)
            except (TypeError, ValueError):
                pass
        return min(0.5 * (2**attempt), 8.0)


__all__ = ["RequestPolicy"]

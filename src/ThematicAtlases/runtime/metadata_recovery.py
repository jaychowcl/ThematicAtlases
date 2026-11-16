"""Structured whole-study recovery eligibility shared by resume and reporting."""
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
import hashlib
import json
import math
import time

_active = ContextVar('ta_metadata_retry_scope', default=None)


def provider_issues(payload):
    """Only the latest attempt is authoritative; never interpret warning text."""
    outcome = payload.get('last_failure', payload.get('outcome', {}))
    if not isinstance(outcome, dict):
        return []
    found = {}
    for diagnostic in outcome.get('diagnostics', []):
        if not isinstance(diagnostic, dict) or diagnostic.get('code') == 'provider_recovered':
            continue
        issue = diagnostic.get('provider_issue')
        if not isinstance(issue, dict) or not isinstance(issue.get('error'), dict):
            continue
        key = issue['error'].get('correlation_id') or json.dumps(issue, sort_keys=True)
        found[key] = issue
    return list(found.values())


def retryable_provider_issues(item):
    if not item or item.get('status') in {'terminal_error', 'no_data'}:
        return []
    return [issue for issue in provider_issues(item.get('payload') or {})
            if issue.get('reason') in {'provider_response_invalid', 'provider_transport_failure', 'provider_http_failure'}
            and issue['error'].get('retry_category') == 'retryable']


def retry_at(item):
    payload = (item or {}).get('payload') or {}
    values = [payload.get('next_retry_at'), *[i.get('retry_at') for i in retryable_provider_issues(item)]]
    return max((v for v in values if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)), default=0)


def _version(item):
    return hashlib.sha256(json.dumps(item.get('payload'), sort_keys=True).encode()).hexdigest()


@dataclass
class RetryScope:
    store_path: str
    selected: dict
    attempted: set = field(default_factory=set)

    def allows(self, key, saved):
        return (key not in self.attempted and key in self.selected
                and self.selected[key] == _version(saved)
                and bool(retryable_provider_issues(saved)) and retry_at(saved) <= time.time())

    def stale(self, key, saved):
        return key in self.selected and self.selected[key] != _version(saved)


def current_retry_scope(store):
    scope = _active.get()
    return scope if store is not None and scope is not None and scope.store_path == str(store.path) else None


@contextmanager
def metadata_retry_scope(store):
    scope = RetryScope(str(store.path), {item['key']: _version(item)
        for item in store.items('metadata_conversion') if retryable_provider_issues(item)})
    token = _active.set(scope)
    try:
        yield scope
    finally:
        _active.reset(token)

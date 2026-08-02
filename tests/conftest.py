import os
from pathlib import Path
import socket
import subprocess
from urllib.parse import urlsplit

import pytest
import requests


_NETWORK_ERROR = "network access is disabled during tests"
_SUBPROCESS_ERROR = (
    "subprocess execution is disabled during tests; mark an intentional test "
    "with @pytest.mark.allow_subprocess"
)
_LIVE_ENV = "RUN_LIVE_API_TESTS"
_LIVE_DIR = (Path(__file__).parent / "live_api").resolve()
_LIVE_HOSTS = {"api.biorxiv.org", "eutils.ncbi.nlm.nih.gov", "www.biorxiv.org", "www.ebi.ac.uk", "www.medrxiv.org"}


def pytest_configure(config) -> None:
    config.addinivalue_line("markers", "live_api: opt-in public provider contract")
    config.addinivalue_line(
        "markers",
        "allow_subprocess: allow this test to create subprocesses",
    )


def pytest_collection_modifyitems(items) -> None:
    enabled = os.environ.get(_LIVE_ENV) == "1"
    for item in items:
        if item.get_closest_marker("live_api") is None:
            continue
        if not Path(str(item.path)).resolve().is_relative_to(_LIVE_DIR):
            raise pytest.UsageError("live_api tests are restricted to tests/live_api")
        if not enabled:
            item.add_marker(pytest.mark.skip(reason=f"set {_LIVE_ENV}=1 to run live API contracts"))


def _blocked_network(*args, **kwargs):
    raise RuntimeError(_NETWORK_ERROR)


def _blocked_subprocess(*args, **kwargs):
    raise RuntimeError(_SUBPROCESS_ERROR)


@pytest.fixture(autouse=True)
def block_external_effects(request, monkeypatch) -> None:
    live = request.node.get_closest_marker("live_api") is not None and os.environ.get(_LIVE_ENV) == "1"
    if live:
        original_request = requests.sessions.Session.request
        original_send = requests.sessions.Session.send
        sends = [0]

        def validate(url):
            parsed = urlsplit(str(url))
            if parsed.scheme not in {"http", "https"} or parsed.hostname not in _LIVE_HOSTS:
                raise RuntimeError(f"unapproved live API URL: {url}")

        def guarded_request(session, method, url, *args, **kwargs):
            validate(url)
            return original_request(session, method, url, *args, **kwargs)

        def guarded_send(session, prepared, *args, **kwargs):
            validate(prepared.url)
            sends[0] += 1
            if sends[0] > 12:
                raise RuntimeError("live API request budget exceeded")
            return original_send(session, prepared, *args, **kwargs)

        monkeypatch.setattr(requests.sessions.Session, "request", guarded_request)
        monkeypatch.setattr(requests.sessions.Session, "send", guarded_send)
    else:
        monkeypatch.setattr(socket, "create_connection", _blocked_network)
        monkeypatch.setattr(socket.socket, "connect", _blocked_network)
        monkeypatch.setattr(socket.socket, "connect_ex", _blocked_network)
    if request.node.get_closest_marker("allow_subprocess") is None:
        monkeypatch.setattr(subprocess, "Popen", _blocked_subprocess)

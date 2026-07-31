import socket
import subprocess

import pytest


_NETWORK_ERROR = (
    "network access is disabled during tests; mark an intentional test "
    "with @pytest.mark.allow_network"
)
_SUBPROCESS_ERROR = (
    "subprocess execution is disabled during tests; mark an intentional test "
    "with @pytest.mark.allow_subprocess"
)


def pytest_configure(config) -> None:
    config.addinivalue_line(
        "markers",
        "allow_network: allow this test to use sockets or HTTP clients",
    )
    config.addinivalue_line(
        "markers",
        "allow_subprocess: allow this test to create subprocesses",
    )


def _blocked_network(*args, **kwargs):
    raise RuntimeError(_NETWORK_ERROR)


def _blocked_subprocess(*args, **kwargs):
    raise RuntimeError(_SUBPROCESS_ERROR)


@pytest.fixture(autouse=True)
def block_external_effects(request, monkeypatch) -> None:
    if request.node.get_closest_marker("allow_network") is None:
        monkeypatch.setattr(socket, "create_connection", _blocked_network)
        monkeypatch.setattr(socket.socket, "connect", _blocked_network)
        monkeypatch.setattr(socket.socket, "connect_ex", _blocked_network)
    if request.node.get_closest_marker("allow_subprocess") is None:
        monkeypatch.setattr(subprocess, "Popen", _blocked_subprocess)

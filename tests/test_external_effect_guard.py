import socket
import subprocess

import pytest


def test_network_is_blocked_by_default() -> None:
    with pytest.raises(RuntimeError, match="network access is disabled"):
        socket.create_connection(("127.0.0.1", 9))


def test_subprocess_is_blocked_by_default() -> None:
    with pytest.raises(RuntimeError, match="subprocess execution is disabled"):
        subprocess.Popen(["python", "--version"])


@pytest.mark.allow_subprocess
def test_allow_subprocess_marker_restores_popen_implementation() -> None:
    assert subprocess.Popen.__module__ == "subprocess"


def test_external_effect_markers_are_registered(pytestconfig) -> None:
    markers = pytestconfig.getini("markers")

    assert not any(value.startswith("allow_network:") for value in markers)
    assert any(value.startswith("allow_subprocess:") for value in markers)

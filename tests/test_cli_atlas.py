import json

import pytest

from ThematicAtlases.cli_atlas import main


def test_collect_jsons_emits_placeholder_response(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["collect-jsons"]) == 0

    assert json.loads(capsys.readouterr().out) == {
        "command": "collect-jsons",
        "status": "placeholder",
        "result": None,
    }


def test_filter_jsons_emits_placeholder_response(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["filter-jsons"]) == 0

    assert json.loads(capsys.readouterr().out) == {
        "command": "filter-jsons",
        "status": "placeholder",
        "result": None,
    }


def test_harmonize_jsons_emits_placeholder_response(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["harmonize-jsons"]) == 0

    assert json.loads(capsys.readouterr().out) == {
        "command": "harmonize-jsons",
        "status": "placeholder",
        "result": None,
    }


def test_unknown_command_exits_with_argparse_error() -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["not-a-command"])

    assert exc_info.value.code == 2

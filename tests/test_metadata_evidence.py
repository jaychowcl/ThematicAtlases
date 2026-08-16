import pytest

from ThematicAtlases.wrappers.metadata_evidence import compressed_text, restored_text


def test_compressed_text_round_trips_and_verifies_checksum() -> None:
    payload = compressed_text("<MINiML>source</MINiML>")

    assert payload["encoding"] == "gzip+base64"
    assert payload["byte_count"] == len("<MINiML>source</MINiML>".encode())
    assert restored_text(payload) == "<MINiML>source</MINiML>"

    payload["sha256"] = "0" * 64
    with pytest.raises(ValueError, match="checksum"):
        restored_text(payload)

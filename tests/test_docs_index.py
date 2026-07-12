import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "docs" / "index.md"
CODEBASE = ROOT / "docs" / "codebase.md"


def test_docs_index_routes_by_stable_anchors_not_line_numbers() -> None:
    index_text = INDEX.read_text(encoding="utf-8")
    codebase_text = CODEBASE.read_text(encoding="utf-8")

    assert "lines:" not in index_text
    assert "sed -n" not in index_text

    anchors = re.findall(r"^  anchor: (.+)$", index_text, flags=re.MULTILINE)
    assert anchors
    for anchor in anchors:
        assert f'<a id="{anchor}"></a>' in codebase_text


def test_docs_index_documents_anchor_retrieval_helper() -> None:
    index_text = INDEX.read_text(encoding="utf-8")

    assert "retrieve_codebase_section.py --id <section-id>" in index_text

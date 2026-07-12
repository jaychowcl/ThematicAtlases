from pathlib import Path


THEME = Path(__file__).resolve().parents[1] / "docs" / "theme_fibrosis.txt"
README = Path(__file__).resolve().parents[1] / "README.md"
CODEBASE = Path(__file__).resolve().parents[1] / "docs" / "codebase.md"


def test_fibrosis_theme_defines_the_curated_dataset_scope() -> None:
    text = THEME.read_text(encoding="utf-8").lower()

    required_phrases = [
        "human bulk, single-cell, single-nucleus, or spatial transcriptomic datasets",
        "at least one profiled",
        "non-fibrotic controls and comparator samples",
        "animal-only datasets",
        "fibrosis-inducing or profibrotic treatment",
        "established fibrotic phenotype is not demonstrated",
        "relevant:",
        "unsure:",
        "not_relevant:",
    ]

    for phrase in required_phrases:
        assert phrase in text


def test_documentation_uses_the_tracked_fibrosis_theme_path() -> None:
    for document in (README, CODEBASE):
        text = document.read_text(encoding="utf-8")
        assert "docs/theme_fibrosis.txt" in text
        assert ".dev/theme_fibrosis.txt" not in text

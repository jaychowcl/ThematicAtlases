from pathlib import Path


README = Path(__file__).resolve().parents[1] / "README.md"


def test_readme_preserves_top_level_section_names() -> None:
    headings = [
        line.strip()
        for line in README.read_text(encoding="utf-8").splitlines()
        if line.startswith("#")
    ]

    assert headings == [
        "# ThematicAtlases",
        "## Description",
        "## Installation",
        "### Requirements",
        "## Quickstart",
        "## CLI",
        "## Python API",
        "## More information",
        "## Authors",
    ]


def test_readme_describes_major_code_flow_and_output_shape() -> None:
    text = README.read_text(encoding="utf-8")

    required_phrases = [
        "`create_atlas()` is the end-to-end Python flow: it calls `collect_datasets()`, then passes those datasets to `harmonize_datasets()`.",
        "`Atlas` is the root orchestrator and dependency-injection boundary.",
        "`AtlasCollector`",
        "`AtlasFilterer`",
        "`PublicationTextReviewer`",
        "`EuropePMCWrapper`",
        "`GEOWrapper`",
        "`ArrayExpressWrapper`",
        "`AtlasHarmonizer`",
        "`original_datalinks`",
        "`geo2json`",
        "`publication_text_ref`",
        "`accessions` and `publication_texts`",
        "`--out`",
        "`--dev-out-dir`",
        "`--no-dev-output`",
        "`YYYYMMDDTHHMMSS_01_collected_accessions.json`",
    ]

    for phrase in required_phrases:
        assert phrase in text

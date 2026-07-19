import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
CODEBASE = ROOT / "docs" / "codebase.md"


def test_readme_uses_the_required_user_facing_structure() -> None:
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
        "## Configuration",
        "## Quickstart",
        "### CLI",
        "### Python",
        "### Inputs & Outputs",
        "## Guide",
        "### CLI guide",
        "### Python API guide",
        "### Workflow scripts",
        "### Code flow",
        "## Docs",
        "## Authors",
    ]


def test_quickstarts_link_to_the_full_interface_guides() -> None:
    text = README.read_text(encoding="utf-8")

    assert '<a id="quickstart-cli"></a>' in text
    assert '<a id="quickstart-python"></a>' in text
    assert '<a id="cli-guide"></a>' in text
    assert '<a id="python-api-guide"></a>' in text
    assert "[CLI guide](#cli-guide)" in text
    assert "[Python API guide](#python-api-guide)" in text


def test_configuration_documents_real_sources_and_credentials() -> None:
    text = README.read_text(encoding="utf-8")

    required_phrases = [
        "Google Application Default Credentials",
        "gcloud auth application-default login",
        "config/fibrosis_discovery_queries.json",
        "docs/theme_fibrosis.txt",
        "GEO-only",
        "not a dotenv file",
        "There is no central application configuration file",
        "There is no Docker interface",
    ]

    for phrase in required_phrases:
        assert phrase in text


def test_cli_guide_lists_every_registered_command_and_option() -> None:
    text = README.read_text(encoding="utf-8")
    options = set(re.findall(r'add_argument\("(--[a-z-]+)"', (ROOT / "src" / "ThematicAtlases" / "cli_atlas.py").read_text(encoding="utf-8")))
    cli_guide = text.split("### CLI guide", 1)[1].split(
        "### Python API guide", 1
    )[0]

    for command in ("collect-datasets", "create-atlas", "harmonize-datasets"):
        assert command in cli_guide
    for option in options:
        assert f"`{option}`" in text
    assert "`-v`, `--verbose`" in text


def test_python_guide_covers_public_workflow_methods_and_specialists() -> None:
    text = README.read_text(encoding="utf-8")
    python_guide = text.split("### Python API guide", 1)[1].split(
        "### Workflow scripts", 1
    )[0]

    required_symbols = [
        "`Atlas(...)`",
        "`Atlas.create_atlas(...)`",
        "`Atlas.collect_datasets(...)`",
        "`Atlas.harmonize_datasets(...)`",
        "`Atlas.resume(...)`",
        "`Atlas.amend_queries(...)`",
        "`Atlas.archive_existing_runs(...)`",
        "`PublicationTextReviewer.resume(...)`",
        "`AtlasCollector.resume_metadata(...)`",
        "`ThematicReviewerBenchmark`",
    ]

    for symbol in required_symbols:
        assert symbol in python_guide


def test_readme_describes_inputs_outputs_flow_docs_and_author() -> None:
    text = README.read_text(encoding="utf-8")

    required_phrases = [
        "`accessions`",
        "`publication_texts`",
        "`atlas.summary.json`",
        "`resume_state.sqlite`",
        "`AtlasCollector`",
        "`AtlasFilterer`",
        "`PublicationTextReviewer`",
        "`AtlasHarmonizer`",
        "[Codebase handoff](docs/codebase.md)",
        "[Documentation index](docs/index.md)",
        "Created by [jaychowcl](https://github.com/jaychowcl) @ [Saez-Rodriguez Group](https://saezlab.org) & [EMBL-EBI Functional Genomics Team](https://www.ebi.ac.uk/about/teams/functional-genomics/) on May 2026",
    ]

    for phrase in required_phrases:
        assert phrase in text


def test_readme_codebase_anchor_links_resolve() -> None:
    text = README.read_text(encoding="utf-8")
    codebase_text = CODEBASE.read_text(encoding="utf-8")
    anchors = re.findall(r"\(docs/codebase\.md#([a-z0-9-]+)\)", text)

    assert anchors
    for anchor in anchors:
        assert f'<a id="{anchor}"></a>' in codebase_text

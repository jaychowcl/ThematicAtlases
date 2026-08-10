import argparse
import inspect
import re
from pathlib import Path

from ThematicAtlases.atlas import Atlas
from ThematicAtlases.cli_atlas import _build_parser
from ThematicAtlases.wrappers.epmc import EuropePMCWrapper


ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
CODEBASE = ROOT / "docs" / "codebase.md"
HISTORICAL_LOGO = (
    '<img width="375" height="250" '
    'alt="ChatGPT Image Jul 27, 2026, 10_33_57 AM" '
    'src="https://github.com/user-attachments/assets/'
    'ea6a1467-8555-4493-8523-a2edb0ed22ff" />'
)
HISTORICAL_AUTHORS = (
    "Created by [jaychowcl](https://github.com/jaychowcl) @ "
    "[Saez-Rodriguez Group](https://saezlab.org) & "
    "[EMBL-EBI Functional Genomics Team]"
    "(https://www.ebi.ac.uk/about/teams/functional-genomics/) on May 2026"
)


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
        "## Quickstart",
        "### CLI",
        "### Python",
        "### Inputs & Outputs",
        "## Guide",
        "### CLI guide",
        "### Python API guide",
        "### Workflow scripts",
        "### Configuration",
        "### Code flow",
        "## Testing",
        "## Docs",
        "## Authors",
    ]


def test_readme_and_handoff_record_current_contracts_and_test_evidence() -> None:
    readme = README.read_text(encoding="utf-8")
    codebase = CODEBASE.read_text(encoding="utf-8")
    index = (ROOT / "docs" / "index.md").read_text(encoding="utf-8")

    for document in (readme, codebase):
        assert "Atlas document schema 1.0" in document
        assert "H5AD metadata schema 1.0" in document
        assert "2026-08-10" in document
        assert "541 passed, 4 skipped" in document
    for stale in ("meta-standards-converter 3", "H5AD metadata schema 3.0"):
        assert stale not in index
        assert stale not in codebase


def test_readme_preserves_historical_branding_and_attribution() -> None:
    text = README.read_text(encoding="utf-8")

    assert text.startswith(f"{HISTORICAL_LOGO}\n\n# ThematicAtlases\n")
    assert f"## Authors\n\n{HISTORICAL_AUTHORS}\n" in text


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
        "GEO and ArrayExpress",
        "not a dotenv file",
        "There is no central application configuration file",
        "There is no Docker interface",
    ]

    for phrase in required_phrases:
        assert phrase in text


def test_cli_guide_lists_every_registered_command_and_option() -> None:
    text = README.read_text(encoding="utf-8")
    parser = _build_parser()
    assert "placeholder" not in parser.format_help().lower()
    subparsers = next(
        action
        for action in parser._actions
        if isinstance(action, argparse._SubParsersAction)
    )
    cli_guide = text.split("### CLI guide", 1)[1].split(
        "### Python API guide", 1
    )[0]

    assert set(subparsers.choices) == {
        "collect-datasets",
        "create-atlas",
        "harmonize-datasets",
        "resume",
        "fork-run",
    }
    assert "placeholder" not in subparsers.choices[
        "harmonize-datasets"
    ].format_help().lower()
    for command, command_parser in subparsers.choices.items():
        assert command in cli_guide
        options = {
            option
            for action in command_parser._actions
            for option in action.option_strings
            if option.startswith("--") and option != "--help"
        }
        for option in options:
            assert re.search(rf"`{re.escape(option)}(?:`|\s)", cli_guide)
    assert "`-v`, `--verbose`" in text


def test_python_workflow_signatures_and_guide_match_public_interfaces() -> None:
    text = README.read_text(encoding="utf-8")
    python_guide = text.split("### Python API guide", 1)[1].split(
        "### Workflow scripts", 1
    )[0]

    assert list(inspect.signature(Atlas.collect_datasets).parameters) == [
        "self", "query", "file", "out", "theme", "review_filter",
        "review_strategy", "metadata_repositories", "max_publications",
        "max_publications_per_query", "reviewer", "collect_metadata",
        "generate_queries", "max_generated_queries", "dev_trace", "dev_out_dir",
        "run_id", "review_before_metadata", "stop_before_review",
        "scrape_fulltext_accessions", "unsupported_accessions_out",
        "prune_accessions", "_trace_writer",
    ]
    assert list(inspect.signature(Atlas.create_atlas).parameters)[-5:] == [
        "scrape_fulltext_accessions",
        "unsupported_accessions_out",
        "thematic_review",
        "prune_accessions",
        "stop_after",
    ]
    assert list(inspect.signature(Atlas.harmonize_datasets).parameters) == [
        "self", "datasets", "harmonization_details_out", "harmonization_options"
    ]
    assert list(inspect.signature(EuropePMCWrapper.collect_accessions).parameters)[-1] == (
        "scrape_fulltext_accessions"
    )
    assert python_guide.count("scrape_fulltext_accessions=True") >= 2
    assert python_guide.count("prune_accessions=False") >= 2

    required_symbols = [
        "`Atlas(...)`",
        "`Atlas.create_atlas(...)`",
        "`Atlas.collect_datasets(...)`",
        "`Atlas.harmonize_datasets(...)`",
        "`Atlas.resume(...)`",
        "`Atlas.fork_run(...)`",
        "`Atlas.amend_queries(...)`",
        "`Atlas.archive_existing_runs(...)`",
        "`PublicationTextReviewer.resume(...)`",
        "`AtlasCollector.resume_metadata(...)`",
        "`benchmark_fibrosis_meta_pubs_recall.py TRACE_DIR [--references CSV] [--out DIRECTORY]`",
        "`CheckpointStore`",
        "`EuropePMCWrapper`",
        "`GEOWrapper`",
        "`ArrayExpressWrapper`",
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
        HISTORICAL_AUTHORS,
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


def test_readme_redirects_archived_focused_runners() -> None:
    text = README.read_text(encoding="utf-8")
    scripts = sorted(path.name for path in ROOT.glob("run_*.py"))

    assert scripts == []
    assert "Non-canonical fibrosis runners are archived locally" in text
    assert "gsk_ThematicAtlases_adapter/scripts/create_fibrosis_atlas.py" in text


def test_readme_documents_retained_discovery_catalog_limits() -> None:
    text = README.read_text(encoding="utf-8")

    assert "40,000 raw hits" in text
    assert "before cross-query deduplication" in text
    assert "Generated-query mode does not use those four static caps" in text


def test_readme_documents_supported_interfaces_after_archival() -> None:
    text = README.read_text(encoding="utf-8")
    workflow_scripts = text.split("### Workflow scripts", 1)[1].split(
        "### Configuration", 1
    )[0]

    assert "installed `thematic-atlas` CLI" in workflow_scripts
    assert "importable Python APIs" in workflow_scripts
    assert "supported repository-root entry points" in workflow_scripts

import ast
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "docs" / "index.md"
CODEBASE = ROOT / "docs" / "codebase.md"

CANONICAL_SECTIONS = (
    "architecture",
    "system-context-and-boundaries",
    "architectural-decisions",
    "design-invariants-and-expectations",
    "component-relationships-and-data-flow",
    "entrypoints-and-interfaces",
    "orchestrators-and-core-types",
    "public-api-reference",
    "principal-workflows",
    "extension-and-change-guidance",
)


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


def test_canonical_sections_are_substantive_and_routed_with_purpose() -> None:
    index_text = INDEX.read_text(encoding="utf-8")
    codebase_text = CODEBASE.read_text(encoding="utf-8")

    for position, anchor in enumerate(CANONICAL_SECTIONS):
        marker = f'<a id="{anchor}"></a>'
        assert marker in codebase_text
        start = codebase_text.index(marker) + len(marker)
        later = [
            codebase_text.find(f'<a id="{candidate}"></a>', start)
            for candidate in CANONICAL_SECTIONS[position + 1 :]
        ]
        ends = [offset for offset in later if offset >= 0]
        section = codebase_text[start : min(ends) if ends else len(codebase_text)]
        assert len(section.split()) >= 25, f"{anchor} is not substantive"

        route = re.search(
            rf"- id: {re.escape(anchor)}\n"
            rf"  title: .+\n"
            rf"  anchor: {re.escape(anchor)}\n"
            rf"  purpose: .+\n"
            rf"  keywords: .+",
            index_text,
        )
        assert route, f"{anchor} lacks a complete index route"


def test_architectural_decisions_have_evidence_safe_fields() -> None:
    text = CODEBASE.read_text(encoding="utf-8")
    section = text.split('<a id="architectural-decisions"></a>', 1)[1].split(
        '<a id="design-invariants-and-expectations"></a>', 1
    )[0]
    decisions = re.split(r"(?=^### AD-)", section, flags=re.MULTILINE)[1:]

    assert decisions
    for decision in decisions:
        for field in (
            "**Status:**",
            "**Decision:**",
            "**Rationale:**",
            "**Consequences:**",
            "**Affected components:**",
            "**Evidence:**",
        ):
            assert field in decision
        if "**Status:** Observed" in decision:
            assert "**Rationale:** Not documented." in decision


def test_public_api_reference_covers_exports_and_supported_methods() -> None:
    text = CODEBASE.read_text(encoding="utf-8")
    section = text.split('<a id="public-api-reference"></a>', 1)[1].split(
        '<a id="principal-workflows"></a>', 1
    )[0]

    exported_symbols = (
        "ThematicAtlases.collector.AtlasCollector",
        "ThematicAtlases.collector.TraceMetadataResumer",
        "ThematicAtlases.filterer.ACCESSIONS",
        "ThematicAtlases.filterer.AGENTIC_CURATOR",
        "ThematicAtlases.filterer.AtlasFilterer",
        "ThematicAtlases.filterer.PUBLICATIONS",
        "ThematicAtlases.filterer.PUBLICATION_TEXTS",
        "ThematicAtlases.filterer.PUBLICATION_TEXT_REF",
        "ThematicAtlases.filterer.PublicationTextReviewer",
        "ThematicAtlases.filterer.REVIEW_FILTERS",
        "ThematicAtlases.harmonizer.AtlasHarmonizer",
        "ThematicAtlases.wrappers.ArrayExpressWrapper",
        "ThematicAtlases.wrappers.EuropePMCWrapper",
        "ThematicAtlases.wrappers.GEOWrapper",
        "benchmark_ThematicAtlases.ThematicReviewerBenchmark",
    )
    supported_methods = (
        "Atlas.create_atlas",
        "Atlas.collect_datasets",
        "Atlas.harmonize_datasets",
        "Atlas.resume",
        "Atlas.amend_queries",
        "Atlas.archive_existing_runs",
        "CheckpointStore.request_retries",
    )
    for symbol in exported_symbols + supported_methods:
        assert symbol in section


def test_principal_workflows_cover_supported_paths_and_archived_tombstone() -> None:
    text = CODEBASE.read_text(encoding="utf-8")
    section = text.split('<a id="principal-workflows"></a>', 1)[1].split(
        '<a id="extension-and-change-guidance"></a>', 1
    )[0]
    anchors = (
        "workflow-collection",
        "workflow-atlas-creation",
        "workflow-harmonization",
        "workflow-resume-and-retry",
        "workflow-query-amendment-and-archive",
        "workflow-independent-review",
        "workflow-metadata-repair",
        "workflow-fixed-runners",
        "workflow-benchmarking",
    )
    for anchor in anchors:
        assert f'<a id="{anchor}"></a>' in section
    assert section.count("```text") >= len(anchors) * 2


def test_individual_contracts_have_stable_routes() -> None:
    index_text = INDEX.read_text(encoding="utf-8")
    codebase_text = CODEBASE.read_text(encoding="utf-8")
    anchors = (
        "interface-thematic-atlas-cli",
        "interface-python-atlas",
        "interface-focused-runners",
        "decision-checkpointed-traces",
        "decision-shared-publication-texts",
        "decision-delegated-model-work",
        "decision-safe-run-archival",
        "type-atlas",
        "type-atlas-document",
        "type-atlas-run-store",
        "type-atlas-collector",
        "type-publication-text-reviewer",
        "type-atlas-harmonizer",
        "type-checkpoint-store",
        "type-europe-pmc-wrapper",
        "type-geo-wrapper",
        "type-thematic-reviewer-benchmark",
        "workflow-collection",
        "workflow-atlas-creation",
        "workflow-harmonization",
        "workflow-resume-and-retry",
        "workflow-query-amendment-and-archive",
        "workflow-independent-review",
        "workflow-metadata-repair",
        "workflow-fixed-runners",
        "workflow-benchmarking",
    )

    for anchor in anchors:
        assert f'<a id="{anchor}"></a>' in codebase_text
        assert re.search(
            rf"- id: {re.escape(anchor)}\n"
            rf"  title: .+\n"
            rf"  anchor: {re.escape(anchor)}\n"
            rf"  purpose: .+\n"
            rf"  keywords: .+",
            index_text,
        ), f"{anchor} lacks a complete index route"


def test_public_api_contracts_are_source_linked_and_classified() -> None:
    text = CODEBASE.read_text(encoding="utf-8")
    section = text.split('<a id="public-api-reference"></a>', 1)[1].split(
        '<a id="principal-workflows"></a>', 1
    )[0]

    for symbol in (
        "TracePublicationReviewResumer",
        "DevTraceWriter",
        "GoogleCredentialPreflight",
        "RetryTags",
        "CheckpointedPubmedFetcher",
        "CheckpointedINSDCFetcher",
        "EnrichmentAuditor",
        "build_atlas_summary",
        "summary_path",
        "load_query_catalog",
        "workflow_activity_lock",
    ):
        assert symbol in section

    assert "Formal exports" in section
    assert "Supported importable production helpers" in section
    assert "Evidence gap" in section
    assert "../src/" in section


def test_principal_workflows_have_complete_contract_sections() -> None:
    text = CODEBASE.read_text(encoding="utf-8")
    section = text.split('<a id="principal-workflows"></a>', 1)[1].split(
        '<a id="extension-and-change-guidance"></a>', 1
    )[0]
    anchors = (
        "workflow-collection",
        "workflow-atlas-creation",
        "workflow-harmonization",
        "workflow-resume-and-retry",
        "workflow-query-amendment-and-archive",
        "workflow-independent-review",
        "workflow-metadata-repair",
        "workflow-fixed-runners",
        "workflow-benchmarking",
    )

    for position, anchor in enumerate(anchors):
        marker = f'<a id="{anchor}"></a>'
        start = section.index(marker)
        end = (
            section.index(f'<a id="{anchors[position + 1]}"></a>', start)
            if position + 1 < len(anchors)
            else len(section)
        )
        workflow = section[start:end]
        assert "#### Numbered stages" in workflow
        assert "#### Pseudocode" in workflow
        assert "#### Evidence" in workflow
        assert "```text" in workflow
        assert re.search(r"\]\(\.\./(?:src/|run_)", workflow)


def test_docs_correct_known_runtime_claims_and_layout() -> None:
    text = CODEBASE.read_text(encoding="utf-8")

    assert "40,000 raw hits before cross-query deduplication" in text
    assert "reviewer.review_relevancy" in text
    assert "reviewer.review(" not in text
    assert "PublicationTextReviewer.review(" not in text
    assert "PublicationTextReviewer.review_relevancy" not in text
    assert "selects normal resume, offline audit" in text
    assert "oldd/` contains" not in text
    for path in (
        "collector/resume.py",
        "filterer/resume.py",
        "wrappers/enrichment.py",
        "query_catalog.py",
        "run_archive.py",
        "credentials.py",
    ):
        assert path in text


def test_harmonize_datasets_documentation_matches_ast_call_flow() -> None:
    source = (ROOT / "src" / "ThematicAtlases" / "atlas.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    atlas_class = next(
        node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "Atlas"
    )
    method = next(
        node
        for node in atlas_class.body
        if isinstance(node, ast.FunctionDef) and node.name == "harmonize_datasets"
    )
    calls = {
        ast.unparse(node.func)
        for node in ast.walk(method)
        if isinstance(node, ast.Call)
    }

    assert "self._harmonizer.harmonize_datasets" in calls
    assert all(not call.endswith(".harmonize_jsons") for call in calls)
    workflow = CODEBASE.read_text(encoding="utf-8").split(
        '<a id="workflow-harmonization"></a>', 1
    )[1].split('<a id="workflow-resume-and-retry"></a>', 1)[0]
    assert "AtlasHarmonizer.harmonize_datasets" in workflow
    assert "AtlasHarmonizer.harmonize_jsons" not in workflow

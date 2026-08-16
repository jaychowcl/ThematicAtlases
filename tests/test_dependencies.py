from pathlib import Path
import ast
import importlib
import inspect
import tomllib


ROOT = Path(__file__).resolve().parents[1]


def test_pyproject_declares_direct_runtime_and_development_dependencies() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))[
        "project"
    ]
    dependencies = project["dependencies"]

    assert "google-auth>=2,<3" in dependencies
    assert "requests>=2.31,<3" in dependencies
    assert "agentic-curator>=4.3,<5" in dependencies
    assert "meta-standards-converter>=5.2.1,<6" in dependencies
    assert not any("git+" in value for value in dependencies)
    assert "pytest>=8" in project["optional-dependencies"]["dev"]


def test_package_exposes_current_release_version() -> None:
    package = importlib.import_module("ThematicAtlases")

    assert package.__version__ == "4.3.0"


def test_requirements_file_delegates_to_runtime_project_metadata() -> None:
    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")

    assert requirements.splitlines() == ["-e ."]
    assert "pytest" not in requirements


def test_installation_documentation_covers_runtime_and_development() -> None:
    for path in (ROOT / "README.md", ROOT / "docs" / "codebase.md"):
        text = path.read_text(encoding="utf-8")
        assert "pip install -r requirements.txt" in text
        assert 'pip install -e ".[dev]"' in text
        assert ".env/bin/python -m pytest -q" in text


def test_resume_wiring_has_no_method_local_or_mutual_component_imports() -> None:
    paths = [
        ROOT / "src/ThematicAtlases/collector/collector.py",
        ROOT / "src/ThematicAtlases/collector/resume.py",
        ROOT / "src/ThematicAtlases/filterer/review.py",
        ROOT / "src/ThematicAtlases/filterer/resume.py",
    ]
    offenders = []
    for path in paths:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        for function in (
            node
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        ):
            for node in ast.walk(function):
                if isinstance(node, ast.ImportFrom) and (
                    node.module or ""
                ).startswith(("ThematicAtlases.collector", "ThematicAtlases.filterer")):
                    offenders.append((path.name, function.name, node.module))
    assert offenders == []
    assert "ThematicAtlases.collector" not in paths[1].read_text(encoding="utf-8")
    assert "ThematicAtlases.filterer" not in paths[3].read_text(encoding="utf-8")


def test_public_collector_handler_boundary_has_explicit_return_type() -> None:
    from ThematicAtlases.collector import AtlasCollector

    assert inspect.signature(AtlasCollector.metadata_handler).return_annotation == "Any"

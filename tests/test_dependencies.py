from pathlib import Path
import tomllib


ROOT = Path(__file__).resolve().parents[1]


def test_pyproject_declares_direct_runtime_and_development_dependencies() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))[
        "project"
    ]
    dependencies = project["dependencies"]

    assert "google-auth>=2,<3" in dependencies
    assert "requests>=2.31,<3" in dependencies
    assert any(value.startswith("agentic-curator @ git+") for value in dependencies)
    assert any(
        value.startswith("meta-standards-converter @ git+")
        for value in dependencies
    )
    assert project["optional-dependencies"]["dev"] == ["pytest>=8"]


def test_requirements_file_delegates_to_runtime_project_metadata() -> None:
    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")

    assert requirements.splitlines() == ["-e ."]
    assert "pytest" not in requirements


def test_installation_documentation_covers_runtime_and_development() -> None:
    for path in (ROOT / "README.md", ROOT / "docs" / "codebase.md"):
        text = path.read_text(encoding="utf-8")
        assert "pip install -r requirements.txt" in text
        assert 'pip install -e ".[dev]"' in text

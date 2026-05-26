# ThematicAtlases Codebase Handoff

This document describes the fresh live package skeleton at the repository root. The previous implementation is archived under `old/` and is reference-only until code is deliberately ported back into the live package.

The current implemented path is intentionally small:

```text
import ThematicAtlases -> construct ThematicAtlas -> serialize with to_dict()
```

<a id="project-purpose-and-layout"></a>
## Project Purpose And Layout

`ThematicAtlases` will provide tools for building thematic atlases of biomedical datasets. The current root package is a clean foundation for future development, not a port of the archived workflow.

```text
src/ThematicAtlases/
├── __init__.py
├── _version.py
├── atlas.py
├── clients/
├── models/
└── pipelines/
```

Supporting files:

```text
pyproject.toml
README.md
LICENSE
tests/test_package.py
docs/
old/
```

<a id="runtime-behavior"></a>
## Runtime Behavior

- The package requires Python `>=3.10`.
- The live package currently has no runtime dependencies.
- The package uses a `src/` layout with setuptools package discovery.
- `old/` is not imported by live package code.

<a id="public-api"></a>
## Public API

The public import surface is:

```python
from ThematicAtlases import ThematicAtlas, __version__
```

`ThematicAtlas` is a dataclass with:

- `name: str`
- `description: str = ""`
- `metadata: dict[str, Any]`

`metadata` uses `default_factory=dict` so instances do not share mutable state.

<a id="atlas-model"></a>
### Atlas Model

`ThematicAtlas.to_dict()` returns:

```python
{
    "name": self.name,
    "description": self.description,
    "metadata": dict(self.metadata),
}
```

The method returns a shallow copy of `metadata`.

<a id="extension-points"></a>
## Extension Points

The package includes empty namespace packages for planned development:

- `clients`: future external API clients.
- `models`: future domain and data models.
- `pipelines`: future atlas-building workflows.

These packages intentionally contain no implementation yet.

<a id="test-plan"></a>
## Test Plan

Run the smoke test suite:

```bash
python3 -m pytest
```

Current coverage checks:

- Package imports.
- Version export.
- `ThematicAtlas` construction.
- `to_dict()` output.
- Independent default `metadata` dictionaries.

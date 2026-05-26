# ThematicAtlases Codebase Handoff

This document describes the current live package skeleton at the repository root. The previous implementation is archived under `oldd/` and is reference-only until code is deliberately ported into the live package.

The current implemented path is intentionally minimal:

```text
import ThematicAtlases
```

`src/ThematicAtlases/atlas.py` contains an `Atlas` class stub for the next development pass, but there is no implemented atlas workflow yet.

<a id="project-purpose-and-layout"></a>
## Project Purpose And Layout

`ThematicAtlases` will provide tools for building thematic atlases of biomedical datasets. The current root package is a fresh foundation, not a port of the archived workflow.

Live package files:

```text
src/ThematicAtlases/
├── __init__.py
└── atlas.py
```

Root project files:

```text
pyproject.toml
README.md
LICENSE
.gitignore
```

Development docs:

```text
docs/codebase.md
docs/index.md
docs/dev.md
docs/memory.md
docs/burndown.md
```

There is currently no live `tests/` directory and no live config or data directory.

<a id="runtime-and-packaging"></a>
## Runtime And Packaging

- `pyproject.toml` uses `setuptools.build_meta`.
- Project metadata names the package `ThematicAtlases`.
- Version metadata is `0.1.0`.
- Python requirement is `>=3.10`.
- License metadata is `GPL-3.0-or-later`.
- Runtime dependencies are currently empty.
- The `dev` optional dependency group contains `pytest>=8`.
- The package uses a `src/` layout with setuptools package discovery.

<a id="public-api"></a>
## Public API

`src/ThematicAtlases/__init__.py` currently contains only the package docstring:

```python
"""Public package interface for ThematicAtlases."""
```

It does not currently export `Atlas`, `ThematicAtlas`, `__version__`, or any other symbol.

The only class currently present in live package code is `Atlas` in `src/ThematicAtlases/atlas.py`. Import callers must use:

```python
from ThematicAtlases.atlas import Atlas
```

<a id="atlas-stub"></a>
### Atlas Stub

`class Atlas` is a placeholder for the future atlas workflow object.

Current methods:

- `__init__(metadata: dict)`: accepts metadata but does not store it yet.
- `collect_jsons()`: placeholder, returns `None`.
- `filter_jsons(filter_criteria: dict)`: placeholder, returns `None`.
- `harmonize_jsons(harmonization_criteria: dict)`: placeholder, returns `None`.

All methods currently use `pass`; there are no side effects, validation, data collection, filtering, or harmonization behaviors implemented yet.

<a id="archive-reference"></a>
## Archive Reference

`oldd/` contains the archived previous implementation, generated outputs, old docs, and old environment artifacts. Treat it as source material to inspect and cannibalize deliberately, not as live package code.

Live code should not import from `oldd/`. If behavior is restored from the archive, port it into `src/ThematicAtlases/` with tests and updated docs.

<a id="test-and-verification-status"></a>
## Test And Verification Status

There are no live tests at the repository root right now.

Useful checks for the current skeleton:

```bash
python3 -m py_compile src/ThematicAtlases/__init__.py src/ThematicAtlases/atlas.py
```

Future behavior work should add tests near the new implementation before treating the package as stable.

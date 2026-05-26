# Development Workflow

Agent-readable workflow guide for exploring, editing, documenting, and verifying a codebase. This file captures reusable development habits and this repository's documentation navigation pattern; detailed implementation behavior belongs in `docs/codebase.md`.

## Purpose

- Help agents and developers make targeted, low-drift changes.
- Prefer implemented behavior over roadmap intent.
- Keep development guidance separate from exhaustive API or module behavior.
- Make investigation, editing, verification, and handoff repeatable.

## Source Of Truth Order

- First: live source, live tests, and build/configuration files.
- Second: current architecture and handoff documentation.
- Third: user-facing docs and examples.
- Fourth: notes, generated artifacts, old outputs, and scratch files.
- When docs and code disagree, inspect the live implementation and tests before deciding whether the task is a code change, docs fix, or test update.

## Exploration Workflow

- Explore before editing.
- Start from the smallest useful entrypoint: command, public API, failing test, config, or caller named in the task.
- Use fast search tools for discovery and then read the narrowest relevant ranges.
- Follow real execution flow before changing behavior: input boundary -> orchestration -> focused handler/helper -> output boundary.
- Identify side effects early, especially network calls, file writes, database writes, subprocesses, caches, and global state.
- Prefer existing extension points before adding new branching or new abstractions.
- Confirm assumptions with source and tests rather than stale notes.

## Documentation Navigation

This repository uses two development docs together:

- `docs/codebase.md` is the narrative implementation handoff. It explains current behavior, architecture, public or semi-public callables, caveats, and test coverage.
- `docs/index.md` is the agent navigation manifest into `docs/codebase.md`. It lets an agent jump to relevant ranges without scanning the whole handoff.

Use them like this:

- Find a matching record in `docs/index.md` by `id`, `title`, `anchor`, `keywords`, or `lines`.
- Read the targeted `docs/codebase.md` range.
- Treat `anchor` as the stable reference and `lines` as a fast but fragile hint.
- After reading the docs range, inspect the live source and tests that own the behavior.
- If `docs/codebase.md` changes, refresh affected `docs/index.md` line ranges.

`docs/codebase.md` sections should use a stable HTML anchor immediately before the heading:

```markdown
<a id="short-kebab-anchor"></a>
## Short Section Title

Implementation notes...
```

`docs/index.md` records should use this shape:

```yaml
- id: short-kebab-anchor
  title: Short Section Title
  lines: START-END
  anchor: short-kebab-anchor
  keywords: keyword, lookup, hints
```

Record rules:

- `id` and `anchor` should match unless there is a deliberate reason not to.
- `anchor` must match an anchor in `docs/codebase.md`.
- `lines` should cover the section's current range.
- `keywords` should include likely search terms an agent would use.
- Refresh ranges after edits that shift headings or section boundaries.

## Coding Conventions

- Match the local style before introducing a new one.
- Keep changes narrow and behavior-focused.
- Preserve public and semi-public interfaces unless the task explicitly changes them.
- Prefer structured parsers, serializers, and existing helper APIs for structured data.
- Keep side effects easy to mock and close to the boundary where they belong.
- Add abstractions only when they remove real duplication, clarify ownership, or match an existing local pattern.
- Avoid broad refactors while fixing narrow behavior.
- Preserve unrelated worktree changes; do not revert or rewrite work you did not make.

## Testing Workflow

- Add or update tests near the changed behavior.
- Mock external systems unless live integration behavior is explicitly requested.
- Prefer focused tests first, then broader test suites when feasible.
- Include regression tests for bug fixes and compatibility tests for refactors.
- Verify failure paths as well as successful paths when behavior crosses process, network, filesystem, or serialization boundaries.
- If a test command cannot run, report the exact command and blocker.

## Documentation Workflow

- Document implemented behavior, not planned work.
- Update documentation when behavior, architecture, public or semi-public interfaces, data shape, command behavior, configuration, or maintenance caveats change.
- Keep detailed implementation behavior in the handoff docs, not in this workflow guide.
- Keep navigation metadata in sync with the documentation it indexes.
- After documentation edits, spot-check anchors, headings, and representative line ranges.

## Change Workflow

- Read the task and identify the smallest behavior change that satisfies it.
- Explore the relevant code, tests, and docs before editing.
- Make the change in the owning module or layer.
- Update tests and docs that describe or protect the changed behavior.
- Run focused verification first, then broader verification when practical.
- Summarize what changed, what was verified, and any residual risk or skipped checks.

## Maintenance Caveats

- Generated files and scratch artifacts may be useful examples but should not outrank live source and tests.
- Older notes may describe past architecture; validate before relying on them.
- Global state and external services can make tests order-sensitive or environment-sensitive.
- Documentation line ranges are intentionally fragile; anchors are the durable navigation layer.
- Commented legacy code is reference only unless the task explicitly restores it.

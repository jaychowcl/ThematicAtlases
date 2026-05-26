# Persistent Agent Memory

## Purpose

- Durable, project-agnostic working memory for future sessions.
- Use as preference/context hints, not as a substitute for live source, tests, docs, or user instructions.
- If memory conflicts with current evidence or higher-priority instructions, trust the current evidence/instructions.

## Operating Principles

- Explore before editing; inspect the smallest relevant surface first.
- Preserve user work and unrelated changes in dirty worktrees.
- Keep changes scoped to the requested behavior.
- Prefer implemented behavior over stated intent until the user asks to change it.
- Verify before summarizing; state exact blockers when verification cannot run.
- Avoid destructive actions unless explicitly requested and clearly understood.

## Source Of Truth

- Live source, tests, configs, schemas, and generated interfaces outrank stale notes.
- Current docs are useful orientation, but source and tests decide ambiguity.
- Generated artifacts and examples are secondary unless the task targets them.
- When references disagree, determine whether the task needs a code fix, test fix, docs fix, or clarification.

## Planning And Execution

- Use a plan when the user asks for one or when implementation choices matter.
- Make plans decision-complete: goal, key changes, interfaces/data flow, tests, assumptions.
- Once implementation is requested and context is sufficient, execute end to end.
- Prefer reasonable defaults over blocking questions unless a decision materially changes behavior.
- Keep compatibility unless the user explicitly chooses a breaking change.

## Coding Habits

- Match local style, naming, module boundaries, and existing helper APIs.
- Add abstractions only when they reduce real complexity or match established patterns.
- Prefer structured parsers/serializers/APIs over ad hoc string manipulation.
- Keep side effects near boundaries and easy to mock.
- Make narrow edits; avoid drive-by refactors.
- Preserve public or semi-public behavior unless changing it is the point.

## Testing Habits

- Add or update tests near changed behavior.
- Run focused tests first, then broader checks when feasible.
- Mock external systems by default; use live integration only when explicitly requested.
- Test failure paths for network, filesystem, process, serialization, and global-state boundaries.
- Regression tests should pin the bug or behavior being changed.

## Documentation Habits

- Document implemented behavior, not aspirations.
- Update docs when behavior, architecture, interfaces, data shapes, commands, configuration, or caveats change.
- If a repo has navigation/index docs, keep anchors and ranges synchronized with edited docs.
- Keep memory compact; put detailed project behavior in project-specific docs.

## Communication Preferences

- Be concise and concrete.
- Summaries should name what changed and what was verified.
- Mention tests or checks by command/result when useful.
- Call out residual risk and skipped verification plainly.
- Do not bury blockers; state them directly with the next useful action.

## Caveats

- Stale docs, old notes, and commented legacy code can mislead; validate before relying on them.
- Global state, caches, file writes, subprocesses, and network calls can create hidden coupling.
- Formatting/codegen tools may mutate more than expected; inspect before and after.
- In a dirty worktree, assume unfamiliar changes are user-owned unless proven otherwise.

# Project Rules Index

> Claude: read this index at session start to know which rules files apply to your current task.

| File | Scope | Consult when... |
|------|-------|-----------------|
| `branch-commit-discipline.md` | Git workflow, commit sizing, commit message style, testing requirements, PR readiness, release/"What's New" checklist, session handoff, when to close | Starting a session, branching, writing or reviewing any commit, shipping a user-facing change, about to open a PR, ending a session |
| `data-pipeline.md` | CSV conventions, rank formulas, delta sign convention, momentum score formula, empty CSV handling | Touching `scripts/compute_deltas.py`, `scripts/collect.py`, or any CSV read/write logic |

## Quick orientation

- **Starting a session** → `branch-commit-discipline.md` § Session-start checklist
- **About to commit** → `branch-commit-discipline.md` § Commit message style guide + Testing requirements
- **Touching data logic** → `data-pipeline.md`
- **Ending a session** → `branch-commit-discipline.md` § Session handoff checklist

# Commit Discipline, Testing, and Session Handoff

## Keep commits small and focused

Each commit represents one logical, self-contained change. A reader must be able to understand what changed and why from the diff alone, without reading surrounding commits.

**Sizing guide:**
- A single bug fix → one commit
- A new helper function + its test → one commit
- A new script feature (e.g., new delta metric) → one commit per script touched, or one commit if tightly coupled
- Refactors are separate commits from feature work — never bundle them

**Signs a commit is too large:**
- The commit message needs "and" to describe what changed
- The diff touches more than 2–3 unrelated concerns
- You can't describe it in a single imperative sentence

**Workflow: branch → slice → commit → push**
1. Branch from current default (see `git-workflow.md`)
2. Work on ONE logical slice at a time
3. Write or update the test alongside the code (not after)
4. Run tests — must pass before committing: `pytest tests/ -q`
5. Commit with a conventional prefix (`feat/fix/docs/chore/test`)
6. Update session logs after each working block (see below)
7. Push; open a draft PR if one doesn't exist

---

## Testing requirements

Every code change to `scripts/` must include a corresponding test change in `tests/`. No exceptions for "trivial" changes — if you touched logic, add or update a test.

### Coverage expectations by change type

| Change type | Minimum |
|---|---|
| New pure function | Happy path + at least one edge case (empty input, NaN, boundary) |
| Modified computation | Update existing test OR add a regression test for the specific fix |
| New CSV read/write path | Test with `io.StringIO` or `pytest`'s `tmp_path` — no real filesystem I/O |
| Bug fix | Add a test that would have caught the bug before the fix |
| Dashboard-only change | No test required; note it explicitly in the commit message |

### Test infrastructure

- Test runner: `pytest` (in `requirements.txt`)
- Test directory: `tests/`
- Naming: `tests/test_<script_name>.py`
- Run before every commit: `pytest tests/ -q`

### Testable pure functions in this codebase

These functions have no I/O side-effects — test them directly without touching the filesystem:

| Function | Key edge cases to cover |
|---|---|
| `compute_deltas.find_nearest_date` | Empty list, exact match, within tolerance, beyond tolerance |
| `compute_deltas.compute_ranks` | Rank 1 = highest perf; NaN goes to bottom |
| `compute_deltas.compute_momentum` | Score bounds 0.0–1.0; single-row returns NaN; all-NaN column |
| `compute_deltas._fmt` | NaN → `""`, `None` → `""`, valid float passes through |

### Minimal fixture pattern

```python
import pandas as pd
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

SNAPSHOT = pd.DataFrame({
    "name": ["Tech", "Energy", "Finance"],
    "perf_week": [2.0, 1.0, 3.0],
    "perf_month": [5.0, None, 2.0],
    "perf_quarter": [1.0, 2.0, 3.0],
    "perf_half": [1.0, 2.0, 3.0],
    "perf_year": [1.0, 2.0, 3.0],
    "perf_ytd": [1.0, 2.0, 3.0],
    "perf_day": [1.0, 2.0, 3.0],
})
```

---

## Session handoff — end of every working block

A "working block" ends when you push a commit, finish a feature slice, or are about to stop. Always complete the handoff before ending the session.

### After each push / end of feature slice

**`.claude/session-notes.md`** — overwrite with current state (not additive; keep it as a single current snapshot):
- What was done this block (reference commit SHAs or branch name if useful)
- What was discovered (gotchas, environment constraints, data quirks)
- Current blockers — be specific: what failed, what was tried
- Prioritized next steps — top 3, concrete enough to act on without re-reading this session's full transcript

**`.claude/WORK_LOG.md`** — append a milestone entry when:
- A new script or feature works end-to-end
- A significant data milestone is hit (first week of data, first successful GH Actions run, etc.)
- A dashboard tab or visualization is added
- A CI/workflow change lands

Entry format:
```
## YYYY-MM-DD — <short description>
<1–3 sentences: what now works, any caveats>
```

### Session-end checklist

Before closing the session, verify all of the following:
- [ ] All working changes committed and pushed
- [ ] `session-notes.md` reflects current state (not 3 commits ago)
- [ ] `WORK_LOG.md` updated if a milestone was reached
- [ ] Draft PR is open if any new commits were pushed this session
- [ ] `git status` is clean — no untracked files containing work
- [ ] Tests pass: `pytest tests/ -q`

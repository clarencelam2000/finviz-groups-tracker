# Branch, Commit Discipline, Testing, and Session Handoff

## Session-start checklist

Run these before doing anything else:

```bash
git fetch origin
git log --oneline origin/claude/elegant-babbage-hlxnfy -5   # see if Actions pushed data overnight
git status                                                    # confirm clean working tree
```

Then check branch position:
```bash
git log --oneline HEAD ^origin/claude/elegant-babbage-hlxnfy    # commits you have that default doesn't
git log --oneline origin/claude/elegant-babbage-hlxnfy ^HEAD    # commits default has that you don't
```

- Second command shows commits → rebase first: `git rebase origin/claude/elegant-babbage-hlxnfy`
- First command is empty → nothing new; work from here, no PR needed yet

---

## Branch lifecycle

- **New work**: always branch from `origin/claude/elegant-babbage-hlxnfy`, never from a stale local ref
- **Keep branches short**: land them before starting the next session — parallel branches on the same work is the failure mode to avoid
- **After merge**: delete the source branch (GitHub UI if `git push --delete` returns 403)
- **Identical to default**: if `git rev-parse HEAD` == `git rev-parse origin/claude/elegant-babbage-hlxnfy`, skip creating a PR

Before creating a new branch, verify work isn't already landed:
```bash
git fetch origin
git diff origin/claude/elegant-babbage-hlxnfy -- scripts/   # empty diff = already done
```

---

## PR readiness

Mark every PR as ready for review immediately after opening it. Only leave it as a draft if you're explicitly mid-task with more commits coming, or waiting on user input before proceeding.

You should mark PRs as ready for review more often than not.

---

## Amendment policy

**If the PR is unmerged**: amend freely and force-push — the PR updates automatically.

**If the PR is already merged**: force-pushing is futile. Amendments sit stranded on the
feature branch and never reach default. Do not try to amend; open a new follow-up PR instead:

```bash
git checkout -B <new-branch> origin/claude/elegant-babbage-hlxnfy
# make the fix
git push -u origin <new-branch>
# open PR: title "fix: <description> (follow-up to #NNN)"
```

**Post-merge verification** — after every merge, confirm the intended code actually landed:

```bash
git fetch origin
git log --oneline origin/claude/elegant-babbage-hlxnfy | head -3   # merge commit present?
git show origin/claude/elegant-babbage-hlxnfy:docs/index.html | grep "key_identifier"
```

A missing identifier means the wrong commit was merged (e.g. the pre-amend version).
Catch it immediately and open a follow-up PR rather than discovering it sessions later.

---

## Cutting a release (PWA "What's New")

**Hard rule: code change + `releases.json` entry + `sw.js` cache bump must all land in the
same PR.** Splitting them across PRs creates gaps where the feature ships with a stale cache,
or the release dot fires before the code is live. If you catch yourself opening a separate PR
for "just the cache bump" or "just the release notes", stop — that's the failure mode.

The only exception: housekeeping PRs (typos, session notes, refactors) with no user-facing
change skip the release surface entirely.

When a PR ships a user-facing change, update the release surface in the **same PR** — all
three together, or the unseen-update dot and cache will desync:

1. Prepend an entry to `docs/releases.json` `releases[]` (newest-first), `version` =
   `YYYY.MM.DD` (or `YYYY.MM.DD.N` for a second/third release on the same calendar day),
   with `title`, `tag` (`feature|fix|data|improvement`), optional `tab`, and `notes[]`.
2. Set top-level `current` to the new `version`.
3. Bump `CACHE` in `docs/sw.js`.

**Pre-commit check**: if your diff touches `docs/index.html` with a user-facing change, confirm
`docs/releases.json` and `docs/sw.js` are also staged before committing.

Glossary copy: the `GUIDE` constant in `docs/index.html` is kept **verbatim-synced** with the
User one-liners in `knowledge/moaty-metrics.md`. Adding a metric ⇒ add its `GUIDE` entry.
`tests/test_guide_releases.py` guards both the sync and `current === releases[0].version`.
Full rationale: CLAUDE.md § Automation and `planning/whats-new-and-guide.md`.

## Keep commits small and focused

Each commit is one logical, self-contained change. A reader must understand what changed and why from the diff alone — no surrounding context needed.

**Sizing guide:**
- A single bug fix → one commit
- A new helper function + its test → one commit
- A new script feature → one commit per script, or one if tightly coupled
- Refactors are separate from feature work — never bundle them

**Signs a commit is too large:**
- The message needs "and" to describe what changed
- The diff touches more than 2–3 unrelated concerns
- You can't describe it in one imperative sentence

**Workflow:**
1. Branch from current default
2. Work on ONE logical slice at a time
3. Write or update the test alongside the code (not after)
4. Run tests — must pass before committing: `python3 -m pytest tests/ -q`
5. Commit (see style guide below)
6. Update session logs after each working block
7. Push; open a draft PR if one doesn't exist

---

## Commit message style guide

**Format:**
```
<prefix>: <imperative summary under 50 chars>

<optional body: why, not what — blank line above>
```

**Prefix conventions:**
| Prefix | When to use |
|--------|-------------|
| `feat:` | New functionality |
| `fix:` | Bug correction |
| `docs:` | Documentation only |
| `design:` | Design docs / ADRs proposing or recording a design (architecture, UX, data-model decisions) — use instead of `docs:` when the doc's purpose is the design itself, not just documenting existing behavior |
| `chore:` | Housekeeping (gitignore, deps, session notes) |
| `test:` | Tests only, no logic change |
| `refactor:` | Code restructure, no behavior change |
| `data:` | Auto-generated data commits (GitHub Actions only — don't replicate manually) |
| `ops:` | Scheduler, workflow, secrets, or deploy changes (cron expressions, `deploy-workers.yml`, GitHub Actions config) |
| `spike:` | Exploratory/throwaway work not meant to be the final shape — e.g. an abandoned draft, a probe to answer a question |
| `process:` | Dev-workflow/rules changes — this file, PR template, CI ignore-list conventions, session-handoff process |

**PR titles use the same prefix table as commits** — one convention, not two. Look at
`git log --oneline` before naming a PR if unsure which prefix fits; drift between commit
prefixes and PR titles has happened before (some merged PRs shipped with no prefix at all).

If a PR is part of a named phase (e.g. "Phase 3d", "Phase B") from a planning doc, append it
as a parenthetical suffix, not a competing prefix — it shouldn't fight `feat:`/`fix:` for the
first-token slot: `feat: Focus liquidity floor + earnings-risk penalty (Phase 3d)`.

Standalone strategy/direction docs (no code shipping) belong in `planning/` or
`knowledge/decisions/` as an ADR — tag these `design:`, not `docs:`, since the doc's purpose is
the design itself, not documenting existing behavior. Use `docs:` for changes that document
already-shipped code (README updates, CLAUDE.md edits, docstrings).

**Imperative mood** — write the summary as a command, not a description:
- `add rank_day metric to delta schema` ✓
- `adds rank_day metric` ✗
- `added rank_day metric` ✗

**Summary line rules:**
- 50 characters or fewer
- No period at the end
- Lowercase after the prefix colon

**Body (optional):** Use when the *why* isn't obvious from the diff. One blank line after the summary. Focus on reasoning, constraints, or non-obvious tradeoffs — not a restatement of what the code does.

**Examples:**
```
feat: add rank_day metric to delta schema

rank_day was missing from DELTA_COLUMNS; existing CSVs auto-migrate
via ensure_deltas_csv() header mismatch detection.
```
```
fix: momentum score NaN when all-NaN column present

mean() over a mix of valid and all-NaN columns returned NaN for the
whole row. Exclude all-NaN columns before averaging.
```
```
test: add integration tests for compute_for_group

Uses tmp_path kwargs so tests don't touch real data/ files.
```
```
chore: session handoff — sprint complete, PR #3 merged
```

---

## Testing requirements

Every code change to `scripts/` must include a corresponding test change in `tests/`. No exceptions for "trivial" changes — if you touched logic, add or update a test.

### Coverage by change type

| Change type | Minimum |
|---|---|
| New pure function | Happy path + at least one edge case (empty input, NaN, boundary) |
| Modified computation | Update existing test OR add a regression test for the specific fix |
| New CSV read/write path | Test with `io.StringIO` or `pytest`'s `tmp_path` — no real filesystem I/O |
| Bug fix | Add a test that would have caught the bug before the fix |
| Dashboard-only change | No test required; note it explicitly in the commit message |

### Test infrastructure
- Runner: `pytest` (in `requirements-dev.txt`)
- Directory: `tests/`
- Naming: `tests/test_<script_name>.py`
- Run before every commit: `python3 -m pytest tests/ -q`

### Testable pure functions in this codebase

| Function | Key edge cases |
|---|---|
| `compute_deltas.find_nearest_date` | Empty list, exact match, within tolerance, beyond tolerance |
| `compute_deltas.compute_ranks` | Rank 1 = highest perf; NaN goes to bottom |
| `compute_deltas.compute_momentum` | Score 0.0–1.0; single-row → NaN; all-NaN column excluded |
| `compute_deltas._fmt` | NaN → `""`, None → `""`, valid float passes through |

### New Playwright test files must be added to the CI ignore list

The `test` job in `.github/workflows/tests.yml` runs `pytest tests/ -v` with an explicit
`--ignore=` list — it does **not** run `playwright install chromium`, so any test file that
does `from playwright.sync_api import sync_playwright` will fail there with "Executable
doesn't exist" (no browser binary), not with an assertion failure. As of this writing the
ignored files are `test_collect_parsing.py`, `test_functional_playwright.py`,
`test_pwa_picks_hod.py`, `test_pwa_picks_atr_earnings.py`, `test_pwa_focus_scoring.py`,
`test_pwa_picks_chart.py`, `test_pwa_lookup_signal.py`, and `test_pwa_ai_group_chips.py`.
The workflow file is the source of truth — this list is a snapshot and has drifted before
(it was 4 entries stale as of the 2026-07-10 process audit).

**Rule:** any *new* `tests/test_*.py` file that imports Playwright must be added to that
same `--ignore=` list in the same PR that adds the file. This was missed once (PR #232 —
`tests/test_pwa_picks_chart.py` shipped without the ignore line, CI job `test` went red,
fixed in a same-day follow-up commit) — treat a red `test` job with a Playwright
"executable doesn't exist" error as this exact failure mode, not a real regression.

Locally this is invisible if you happen to have Chromium already installed (`pip install
playwright && python3 -m playwright install chromium`), since the test then just runs and
passes — the gap only shows up in CI. Verify before pushing:
```bash
grep -l "sync_playwright" tests/test_*.py
grep "ignore=" .github/workflows/tests.yml
# every file in the first list must appear in the second
```

> **Known gap (separate issue, don't confuse the two):** verifying a *new* Playwright test
> inside a Claude Code cloud session hits a different problem — the pinned `playwright==1.44.0`
> expects a Chromium revision the cloud sandbox doesn't have pre-installed under that name.
> This is a sandbox-only fact, not a CI fact (CI's `playwright install chromium --with-deps`
> step handles it fine there). See `knowledge/investigations/playwright-cloud-session-testing.md`
> for the full root-cause writeup and working-harness pattern, including a symlink trick to
> verify without touching any committed file.

---

## Session handoff — end of every working block

A working block ends when you push a commit, finish a feature slice, or are about to stop.

### Always do before ending

> These files live in `.session/` (not `.claude/`) so Claude can edit them without permission prompts.

**`.session/session-notes.md`** — **append** a new `---` delimited block. Header: `## YYYY-MM-DD — <workstream description>` (use the workstream topic, not the branch name — branches are ephemeral). Include: status (safe-to-close or blocking-on), what landed, any blockers, next steps. Do NOT replace existing entries. The file holds the last 4 sessions; a human reviewer periodically moves older entries to `.session/archive/session-notes-archive.md` — you don't manage the archive.

**`.session/WORK_LOG.md`** — retired, do not update.

**`.session/SPRINT.md`** — move completed tasks to Done, add new tasks to Backlog if discovered.

### Session-end checklist
- [ ] All working changes committed and pushed
- [ ] `session-notes.md` — new entry appended (date + workstream header, status, what landed, next steps)
- [ ] `SPRINT.md` board reflects current task states
- [ ] **PR open for every commit on the branch** — run `git log --oneline origin/claude/elegant-babbage-hlxnfy..HEAD` to confirm nothing is stranded
- [ ] `git status` clean — no untracked files containing work
- [ ] Tests pass: `python3 -m pytest tests/ -q`
- [ ] **Post-merge spot-check**: for each PR merged this session, verify a key identifier from the change is visible in default — catches the "amended after merge" failure mode before it compounds:
  ```bash
  git show origin/claude/elegant-babbage-hlxnfy:docs/index.html | grep "key_identifier"
  ```

### Session-notes commit ordering trap

**Never push session-notes commits to a feature branch after its last PR is already merged.**
Commits pushed after the last PR is merged are stranded — they sit on the feature branch but have no path into the base branch.

**Rule:** Update `session-notes.md` (and `SPRINT.md`) *before* merging the last PR of a session. Either:
- Include the notes update in the last substantive PR (commit it, then merge), or
- Open an immediate follow-up chore PR for the notes commit before ending the session

To check for stranded commits at any time:
```bash
git log --oneline origin/claude/elegant-babbage-hlxnfy..HEAD
```
An empty result = nothing stranded. Any output = open a PR.

### Session notes MUST land on the default branch — not just your working branch

**Pushing session notes to `claude/blissful-brahmagupta-*` (or any feature branch) without merging them is the same as never writing them.** The next Claude reads from `claude/elegant-babbage-hlxnfy`. Notes stranded on a feature branch are invisible.

The mandatory sequence at session end:
1. Commit session notes to your working branch
2. Open a PR targeting `claude/elegant-babbage-hlxnfy` (or reuse the last open one)
3. **Merge that PR** — "pushed" is not enough
4. Verify: `git log --oneline origin/claude/elegant-babbage-hlxnfy | head -3` must show your notes commit

The session-end checklist item "PR open for every commit on the branch" already covers this — but the specific failure mode to avoid is thinking the work is done after `git push` without creating and merging the PR.

---

## Session length — when to close vs. continue

**Keep sessions short and focused.** Context window degradation is real: as a session grows, earlier instructions fade and Claude starts contradicting earlier decisions. One focused session per logical feature or investigation beats one long sprawling session.

### Signs it's time to wrap up and start fresh
- The task you came in to do is complete and committed
- You've been in the session for a while and context feels noisy
- A new unrelated topic has come up — don't pile it onto an existing session
- `/context` shows you're past ~50% context used

### Signs it's NOT safe to close yet
- There's an open PR with unresolved review comments
- CI is failing and a fix is in progress
- A task is mid-slice — code changed but test not yet written, or not yet committed
- You asked the user a question and are waiting on their answer
- A rebase or merge conflict is unresolved

### What to tell the user

When wrapping up, Claude should explicitly say one of:
- **"Safe to close"** — everything is committed, pushed, PR is open, no open threads
- **"Don't close yet"** — state specifically what's unfinished or what needs their input first

This is also reflected in the `session-notes.md` Current Status block so the next session can orient instantly.

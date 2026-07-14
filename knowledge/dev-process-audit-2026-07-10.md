# Dev-Process Audit — 2026-07-10

**Scope:** CI/CD workflows, testing standards, documentation rules, git-history reality-check
against the process described in `CLAUDE.md` and `.claude/rules/`. Conducted as a staff-engineer
review; exploration fanned out to subagents, findings verified before inclusion (one false
positive — a supposedly nonexistent `requests==2.33.1` pin — was checked against PyPI and dropped).

**Overall verdict:** This repo's process maturity is unusually high for a solo project — ADRs,
sprint board, session handoffs, release-triplet discipline, trading-day-aware data conventions,
and triple-documented constants are all *real and mostly followed*, not aspirational. The audit
found no correctness-critical failures. The weaknesses cluster in three themes:

1. **Rules that rely on memory instead of machines** (no lint gate, doc snapshots of CI config
   that drift, branch deletion that never happens).
2. **Docs that assert state instead of pointing at the source of truth** — every stale claim
   found was a duplicated fact (ignore-list contents, LB-FF1 status, retry semantics).
3. **A growing blast radius around the default-branch name** (`claude/elegant-babbage-hlxnfy`
   hardcoded in 20 files, including CI and deploy config).

---

## Fixed in this audit's PR

| Fix | Where |
|---|---|
| Duplicate **ADR-005** renumbered → `ADR-009-etf-classification-curated-first.md` (both ADR-005s were dated 2026-06-20); renumber note added in the doc; live references updated (`CLAUDE.md`, `worker/CLAUDE.md`). Archive/SPRINT historical mentions left as-is. | `knowledge/decisions/` |
| Stale Playwright `--ignore` list in the rules doc (said 4 files; workflow has 8) — updated and marked the workflow as source of truth. | `.claude/rules/branch-commit-discipline.md` |
| `data-pipeline.md` still described LB-FF1 (window-literal derivation) as pending; it shipped 2026-06-18 (PR #110). Updated, residual `_20d` literals tracked as LB-FF1-RESIDUAL. | `.claude/rules/data-pipeline.md` |
| Ambiguous "Retry 3x before failing" in § Automation clarified: retry is *inside* `collect.py` (3 fetch attempts w/ backoff); there is no workflow-level job retry. | `CLAUDE.md` |
| Backlog items AUD-1…AUD-5 + LB-FF1-RESIDUAL added. | `.session/SPRINT.md` |

---

## Open findings (prioritized)

### High

**H1. Branch hygiene has completely failed — and it strands session notes.**
144 remote branches; 142 unmerged into default. The rules mandate delete-after-merge; it
essentially never happens. Worse, at least 3 branches (`chore/session-handoff-2026-06-10`,
`chore/session-notes-pr50-merged`, `claude/ai-analysis-resource-exhausted-k5yjmo`) carry
session-handoff commits that never reached the default branch — the exact "stranded notes"
failure mode `branch-commit-discipline.md` warns about, confirmed live. → **AUD-1**: recover
stranded notes, bulk-delete, and enable GitHub's *"Automatically delete head branches"* repo
setting so the rule enforces itself.

**H2. Zero automated code-quality enforcement.**
No ruff/black/flake8/mypy/pre-commit config anywhere; CI runs pytest only. The project imposes
strict *manual* discipline (3-place constant docs, TODO IDs, commit style) but automates none
of it. Discipline that isn't automated decays — this audit's stale-doc findings are the proof.
→ **AUD-3**: a permissive ruff gate in `tests.yml` is a one-hour job and the highest-leverage
single addition available.

### Medium

**M1. Data-commit race coverage is incomplete.** `collect.yml` and `collect_picks.yml` share
the `finviz-data-commit` concurrency group, but `generate_ai.yml` also writes `data/` under its
own separate group — a third, unserialized writer. And `collect.yml`'s commit step lacks the
`git pull --rebase` that `collect_picks.yml` has, so it loses a run's data if a human PR merge
lands between checkout and push. → **AUD-4**.

**M2. `backfill.py` and `export_db.py` have zero tests** — the only uncovered `scripts/` files.
`export_db.py` is a `delta_columns()` schema consumer, so a schema-migration bug there is
invisible to CI. → **AUD-2**.

**M3. `COLLECTED_AT_CRON_UTC` violates the 3-place documentation rule** (in-code +
`scripts/CLAUDE.md` only; absent from README's table and root CLAUDE.md). Underlying ambiguity:
the rule says "CLAUDE.md" but picks constants live in `scripts/CLAUDE.md` — decide whether
subdirectory CLAUDE.md files satisfy the rule and write it into the rule. → **AUD-5**.

**M4. The default-branch rename (D1) is bigger than it looks.** `elegant-babbage` appears in
20 files — including `.github/workflows/tests.yml`, `deploy-workers.yml`, and
`worker-cron/wrangler.toml` (`DISPATCH_REF`), where a missed reference breaks CI/deploy
*silently*. When D1 happens, treat `grep -rl "elegant-babbage"` as a mandatory preflight and
update workflows + wrangler.toml in the same change.

**M5. Workflows with `contents: write` / `id-token: write` use floating major-tag actions**
(`actions/checkout@v4` etc.). Acceptable risk for a solo project, but pinning to commit SHAs
in `generate_ai.yml` (OIDC) and `deploy-workers.yml` (Cloudflare token) is cheap insurance.

### Low / informational

- `tests.yml` never runs on pushes *to* the default branch (branches-ignore) — so the four
  data-commit workflows get zero CI on their pushes. Currently fine (data-only), but worth an
  explicit comment in the workflow stating that's intentional.
- `collect.yml`'s commit step runs `if: always()` — a failed verify still pushes a `data:`
  commit (with failure logged). Appears intentional; document it if so.
- Monster files: `docs/index.html` (5,716 lines) and `scripts/generate_ai.py` (1,598 lines).
  No action forced now, but every PWA feature raises the cost of the eventual split.
- `test_collect_parsing.py` sits in the Playwright ignore list without importing
  `sync_playwright` — verify why (transitive fixture?) or it's a dead ignore entry.
- SPRINT.md Done section has no archival policy yet (fine at 44 lines; add a policy line
  before it isn't).
- `data:` commits are ~76% of default-branch history; `.git` is 9.8M — no action until
  `data/` approaches ~50–100M.

### What's working well (keep doing it)

- **Release-triplet rule: 100% conformance** in the sampled window (every `docs/index.html`
  change shipped with `releases.json` + `sw.js` in the same commit).
- **TODO discipline: perfect** — only 2 TODOs repo-wide, both with live SPRINT IDs.
- **Session-notes + archive cadence is alive** (archived 2026-07-04) — on the default branch.
- **ADR practice is alive** (9 ADRs, latest touched 2026-07-03) and genuinely consulted.
- **`delta_config.py` single-source-of-truth holds**: all three claimed consumers import it.
- **Empty-CSV guards** are consistently applied (`.empty` idiom throughout).
- **Commit messages** on default conform to the style guide (small sample — only 8 non-data
  commits exist; most history lives in squashed PRs).

---

## The lasting principle

Every stale doc found by this audit was a *duplicated fact*: the ignore list copied into a
rules file, a status claim copied out of the sprint board, retry semantics restated away from
the code. **When documenting configuration or CI behavior, point at the source of truth
("see the `--ignore` list in tests.yml") instead of copying its contents** — or, if the copy
is genuinely valuable (as the 3-place constant rule is), add a test that fails on drift, like
`test_guide_releases.py` already does for the Guide/releases sync. That anti-drift-test
pattern is the best idea in this repo; apply it to more of the rules.

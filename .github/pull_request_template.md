<!--
Keep sections that don't apply, but mark them "N/A — <why>" instead of deleting.
An explicit N/A tells the reviewer you considered it; a missing section doesn't.
-->

## Summary

<!-- 2-4 sentences: what changed and why. Link the SPRINT.md task ID, planning doc, or issue. -->

## Project status: before → after

<!-- One line each. Where does this leave the project relative to the plan?
     e.g. "Before: Picks Focus list ignored HoD basis. After: Phase B shipped; HoD work complete." -->
- **Before:**
- **After:**

## What changed

<!-- Bullet list by file/area. Call out anything non-obvious a reviewer would otherwise have to reverse-engineer from the diff. -->

## How it was verified

<!-- Be specific: test counts, commands run, manual end-to-end steps. "Tests pass" alone is not enough. -->
- [ ] `python3 -m pytest tests/ -q` passes (state the count; note any pre-existing failures, e.g. Playwright-in-cloud)
- [ ] New/changed logic in `scripts/` has a corresponding test change in `tests/` (house rule — no exceptions)
- [ ] Manual verification performed (describe what you exercised and what you observed):

## What the owner should verify after merge

<!-- The one or two things a human should eyeball to confirm this landed correctly —
     a specific PWA screen, a CSV column, a workflow run. Make it copy-paste checkable. -->

## Release surface (user-facing changes only)

<!-- Hard rule: all three land in THIS PR, never split. Mark N/A for housekeeping/pipeline-only PRs. -->
- [ ] `docs/releases.json` — new entry prepended, `current` bumped
- [ ] `docs/sw.js` — `CACHE` version bumped
- [ ] `GUIDE` glossary updated if a metric was added/changed (synced verbatim with `knowledge/moaty-metrics.md`)

## Ops / operational impact

<!-- Anything that changes how the system runs day-to-day. Mark N/A if pure code. -->
- [ ] No change to schedules, workflows, or secrets — **or** the change is described here:
- [ ] Data schema change? If deltas/snapshots/picks columns changed: migration/backfill story stated
- [ ] Worker (`worker/` or `worker-cron/`) touched? Note that `deploy-workers.yml` auto-deploys on merge
- [ ] New Playwright test file? It's added to the `--ignore=` list in `.github/workflows/tests.yml` (same PR)
- [ ] Configurable constants added/renamed? Triple-documented: in-code comment + README § Configurable parameters + CLAUDE.md

## Product / UX check (PWA or dashboard changes)

<!-- Mark N/A for pipeline-only PRs. -->
- [ ] Exercised the changed flow in a real browser (not just unit tests)
- [ ] Empty/missing-data states handled (no fake neutrals, no crashes on header-only CSVs)
- [ ] Existing UI conventions followed (`↗` external / `›` internal nav, silence-is-no-signal, etc.)

## Deferred / leftover items

<!-- Anything discussed but intentionally NOT done here. Each item must be tracked
     (SPRINT.md task ID or issue #) — nothing lives only in this PR description. -->

## What's next (and what comes before it)

<!-- The immediate next step after this merges, and any prerequisite/ordering constraint.
     e.g. "Next: Phase C toggle persistence — but only after PICKS-STATE-PERSIST merges." -->

## Housekeeping

- [ ] Commits are small, focused, imperative-mood (see `.claude/rules/branch-commit-discipline.md`)
- [ ] `.session/SPRINT.md` reflects task state; session notes will land on the default branch (not stranded on this feature branch)
- [ ] No stranded commits: `git log --oneline origin/<default>..HEAD` is fully covered by this PR

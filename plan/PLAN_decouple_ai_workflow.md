# Plan: Decouple AI Analysis Workflow from Daily Snapshot Workflow

**Status:** Approved — ready for implementation  
**Created:** 2026-06-13  
**Branch:** `claude/decouple-ai-snapshot-workflow-7m75ex`  
**Base:** `origin/claude/elegant-babbage-hlxnfy`  
**Location:** `plan/PLAN_decouple_ai_workflow.md` (committed to repo)

---

## Context & Motivation

The daily `collect.yml` workflow bundles four distinct concerns into a single job: scrape (Playwright/Chromium, ~3–4 min), verify row counts (~5 sec), compute deltas (~5 sec), and generate AI analysis (7 Gemini API calls, 13s rate-limit delays, ~5–10 min). The AI step has **no dependency on Playwright or the live scraper** — it only reads committed CSV files. Bundling it causes:

- Any `workflow_dispatch` to test/retry AI changes must also install Chromium and run the scraper (wasted 3–4 min, requires Finviz to be reachable).
- When the scraper fails, AI analysis is also blocked even though the prior day's CSVs are sufficient.
- `GEMINI_API_KEY` is exposed in the scraper workflow unnecessarily.
- AI cannot be triggered independently (e.g., after a prompt change, model change, key rotation, or schema update).

**Intended outcome:** A separate `generate_ai.yml` workflow that runs automatically after each successful snapshot (via `workflow_run`) and can be triggered independently via `workflow_dispatch`. `collect.yml` is reduced to: scrape → verify → compute deltas → log → commit.

---

## Interaction with PR46 Plan (`plan/PLAN_smart_regeneration_pydantic.md`)

PR46 (merged 2026-06-12) contains an approved plan with these tasks that touch overlapping files:

| PR46 Task | Interaction with this plan |
|-----------|---------------------------|
| **1.1** Add `_has_new_delta_data()` to `generate_ai.py` | **Compatible / prerequisite.** Script-only change. Should be implemented before or alongside this plan. |
| **1.2** Add `--force-ai` / `FORCE_AI` flag to `generate_ai.py` | **Compatible / prerequisite.** Script-only change. My `generate_ai.yml` will pass `--force-ai` via a `workflow_dispatch` input. |
| **1.3** Add `force_ai` input to `collect.yml` + wire to AI step | **Superseded by this plan.** This plan removes the AI step from `collect.yml` entirely. The `force_ai` input belongs in `generate_ai.yml` instead. No change to `collect.yml` for this feature. |
| **Phase 2** Schema enrichment, few-shot, validation logging | **Fully compatible / parallel.** Pure `generate_ai.py` changes; no workflow YAML interaction. |

**Sequencing recommendation:** Implement PR46 Tasks 1.1 and 1.2 (script-only) in the same or prior PR to this one. This plan's `generate_ai.yml` wires up the `--force-ai` flag via a `workflow_dispatch` input, fulfilling PR46 Task 1.3's intent without touching `collect.yml`.

---

## Scope of Changes

| File | Action |
|------|--------|
| `.github/workflows/collect.yml` | Modify: remove AI step, remove `AI_GEN_OUTCOME` env var, simplify log step |
| `.github/workflows/generate_ai.yml` | Create: new standalone AI workflow |
| `plan/PLAN_decouple_ai_workflow.md` | Create: this file, committed to repo |
| `scripts/generate_ai.py` | **No changes** — script already handles decoupled invocation gracefully |
| `tests/` | **No changes** — infrastructure-only; existing 100+ tests cover all logic |

---

## Phase 0: Pull Latest + Commit This Plan (do first)

**Purpose:** Ensure the working branch is up to date with the default branch (PR46 was merged overnight), and externalize the plan as a durable committed artifact before any code changes.

**Steps:**
1. `git fetch origin`
2. `git rebase origin/claude/elegant-babbage-hlxnfy` (or branch from it fresh)
3. Write `plan/PLAN_decouple_ai_workflow.md` (this file) to the repo
4. `git add plan/PLAN_decouple_ai_workflow.md`
5. `git commit -m "docs: execution plan for AI workflow decoupling"`
6. `git push -u origin claude/decouple-ai-snapshot-workflow-7m75ex`
7. Open draft PR if not already open

**Acceptance criteria:**
- [ ] Local branch is at or ahead of `origin/claude/elegant-babbage-hlxnfy`
- [ ] `plan/PLAN_decouple_ai_workflow.md` exists in the repo with this content
- [ ] PR is open (draft is fine)

---

## Phase 1: Modify `collect.yml`

### Purpose / What it fixes
Removes `GEMINI_API_KEY` from the scraper workflow, eliminates the 5–10 min AI wall-clock time from each snapshot run, and reduces `collect.yml` to a pure data-collection concern.

### Detailed description

**Remove the "Generate AI analysis" step entirely** (currently after the deltas step):
```yaml
- name: Generate AI analysis
  id: ai_gen
  if: steps.deltas.outcome == 'success'
  env:
    GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}
  run: python scripts/generate_ai.py
```

**In the `Log fetch result` step:**
- Remove `AI_GEN_OUTCOME: ${{ steps.ai_gen.outcome }}` from `env:` block
- Remove the `ai_run_summary.json` read block; replace with:
  ```python
  ai_outcome = ""
  ai_fields_missing = ""
  ```
- Remove the schema migration block — already applied to all existing rows; `generate_ai.yml` will carry this forward if ever needed
- Keep `LOG_COLUMNS` unchanged: `ai_outcome` and `ai_fields_missing` columns remain but are always written as `""` in snapshot rows (no schema break)

### Acceptance criteria
- [ ] `collect.yml` has no reference to `GEMINI_API_KEY`
- [ ] `collect.yml` has no `ai_gen` step id
- [ ] `collect.yml` log step does not read `ai_run_summary.json`
- [ ] `LOG_COLUMNS` in log step still contains `ai_outcome` and `ai_fields_missing`
- [ ] YAML validates: `python -c "import yaml; yaml.safe_load(open('.github/workflows/collect.yml'))"`
- [ ] `grep -n "GEMINI_API_KEY" .github/workflows/collect.yml` → no output

### Alternatives considered

**Alt A (chosen): Remove AI step; always write empty `ai_*` in snapshot log.**  
Pros: Zero schema change to `fetch_log.csv`; historical rows remain valid.  
Cons: Snapshot rows have empty `ai_*` columns (readable via `trigger` column context).

**Alt B: Remove `ai_*` columns entirely from `fetch_log.csv`.**  
Rejected: Breaking schema change; corrupts 14+ existing rows; breaks dashboard/analysis code.

**Alt C: Move AI to a separate job within `collect.yml`.**  
Rejected: Doesn't enable independent triggering; job still couples Playwright to AI setup. Doesn't solve "test AI without scraper" use case.

### Happy path
`collect.yml` runs on schedule → snapshot CSVs updated → deltas computed → log row written with `ai_outcome=""` → commit pushed. Runtime drops from ~12 min to ~5 min.

### Edge cases
- `ai_run_summary.json` from a prior run exists on disk: the new log step ignores it — harmless.
- `workflow_dispatch` on `collect.yml` with `GEMINI_API_KEY` still in repo secrets: secret is unused, no risk.
- `collect.yml` fails before deltas step: log step runs (`if: always()`), writes `outcome="failure"`, `ai_outcome=""`. Correct.

### Dependencies
- No dependency on Phase 2. Can be deployed first. If `generate_ai.yml` doesn't exist yet, AI simply doesn't run until Phase 2 is deployed.

### Error / failure cases
- Any lingering reference to `${{ steps.ai_gen.outcome }}` in `collect.yml` would evaluate to empty string in GitHub Actions (missing step id) — benign but confusing. Remove all references cleanly.

### Follow-up backlog items
- Reduce `collect.yml` `timeout-minutes` from 30 to 15 (AI removal frees ~10 min buffer).

---

## Phase 2: Create `generate_ai.yml`

### Purpose / What it fixes
Provides an independently triggerable, Playwright-free workflow for AI analysis. Enables testing AI changes (prompt edits, model changes, key rotation, force-regeneration) without running the scraper.

### Detailed description

Create `.github/workflows/generate_ai.yml`:

```yaml
name: Generate AI Analysis
on:
  workflow_run:
    workflows: ["Daily Snapshot"]
    types: [completed]
  workflow_dispatch:
    inputs:
      force_ai:
        type: boolean
        default: false
        description: 'Force regeneration even if no new delta data detected'

permissions:
  contents: write

env:
  FORCE_JAVASCRIPT_ACTIONS_TO_NODE24: 'true'

jobs:
  generate:
    if: >
      github.event_name == 'workflow_dispatch' ||
      github.event.workflow_run.conclusion == 'success'
    runs-on: ubuntu-22.04
    timeout-minutes: 20
    steps:
      - uses: actions/checkout@v4
        with:
          ref: ${{ github.event.workflow_run.head_branch || github.ref }}

      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'

      - name: Install dependencies
        run: pip install -r requirements.txt
        # No playwright install — generate_ai.py never imports Playwright

      - name: Generate AI analysis
        id: ai_gen
        env:
          GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}
        run: |
          FLAGS=""
          if [ "${{ github.event.inputs.force_ai }}" = "true" ]; then
            FLAGS="--force-ai"
          fi
          python scripts/generate_ai.py $FLAGS

      - name: Log AI result
        if: always()
        env:
          AI_GEN_OUTCOME: ${{ steps.ai_gen.outcome }}
        run: |
          python - <<'EOF'
          import csv, json, os
          from datetime import datetime, timezone
          from pathlib import Path
          import pytz

          eastern = pytz.timezone("US/Eastern")
          run_date = datetime.now(eastern).strftime("%Y-%m-%d")
          timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

          def count_today_rows(csv_path, run_date):
              p = Path(csv_path)
              if not p.exists(): return ""
              with open(p) as f:
                  return len([r for r in csv.DictReader(f) if r.get("date") == run_date])

          sectors_rows    = count_today_rows("data/sectors/snapshots.csv", run_date)
          industries_rows = count_today_rows("data/industries/snapshots.csv", run_date)
          ai_gen_outcome  = os.environ.get("AI_GEN_OUTCOME", "")

          ai_outcome = ""
          ai_fields_missing = ""
          summary_path = Path("data/ai_run_summary.json")
          if summary_path.exists():
              try:
                  s = json.loads(summary_path.read_text())
                  ai_outcome = s.get("outcome", "")
                  ai_fields_missing = s.get("fields_missing", "")
              except Exception:
                  ai_outcome = "error_reading_summary"
          elif ai_gen_outcome == "skipped":
              ai_outcome = "skipped"
          elif ai_gen_outcome == "failure":
              ai_outcome = "step_failed"

          LOG_COLUMNS = ["timestamp", "run_date", "trigger", "run_id", "outcome",
                         "sectors_rows", "industries_rows", "step_failed",
                         "ai_outcome", "ai_fields_missing"]

          log_path = Path("data/fetch_log.csv")
          write_header = not log_path.exists() or log_path.stat().st_size == 0
          with open(log_path, "a", newline="", encoding="utf-8") as f:
              writer = csv.DictWriter(f, fieldnames=LOG_COLUMNS, extrasaction="ignore")
              if write_header: writer.writeheader()
              writer.writerow({
                  "timestamp": timestamp,
                  "run_date": run_date,
                  "trigger": os.environ.get("GITHUB_EVENT_NAME", ""),
                  "run_id": os.environ.get("GITHUB_RUN_ID", ""),
                  "outcome": ai_outcome or ai_gen_outcome,
                  "sectors_rows": sectors_rows,
                  "industries_rows": industries_rows,
                  "step_failed": "" if ai_gen_outcome == "success" else ai_gen_outcome,
                  "ai_outcome": ai_outcome,
                  "ai_fields_missing": ai_fields_missing,
              })
          print(f"Logged ai={ai_outcome!r} fields_missing={ai_fields_missing!r}")
          EOF

      - name: Commit and push
        if: always()
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git pull --rebase origin ${{ github.ref_name }}
          git add data/
          git diff --cached --quiet || git commit -m "data: AI analysis $(TZ=America/New_York date +%Y-%m-%d)"
          git push
```

### Key design decisions

**`workflow_run` + `workflow_dispatch` (not cron).**  
`workflow_run` is event-driven — fires within seconds of `collect.yml` completing, no race condition. `workflow_dispatch` enables manual/test invocations. `workflow_run` only fires on the default branch, which is where data commits land. Cron was rejected due to race conditions if scraper runs late.

**`workflow_dispatch.inputs.force_ai`.**  
Fulfills PR46 Task 1.3's intent (force-regeneration UI toggle) but placed in the correct workflow. Passes `--force-ai` to `generate_ai.py` (which PR46 Tasks 1.1/1.2 add). If `generate_ai.py` doesn't yet have `--force-ai` support, passing the flag is harmless (argparse will error, step fails — an acceptable failure mode that prompts proper sequencing).

**`ref: ${{ github.event.workflow_run.head_branch || github.ref }}`.**  
For `workflow_run`, checks out the branch `collect.yml` ran on (has fresh committed data). For `workflow_dispatch`, falls back to the selected branch.

**`git pull --rebase` before commit.**  
`collect.yml` commits and pushes data moments before `generate_ai.yml` starts. Without rebase, the AI push fails on fast-forward check. Rebase is safe: AI only writes `data/ai/`, `data/ai_run_*.json`, `data/fetch_log.csv` — no overlap with snapshot CSV files.

**No `playwright install`.**  
`requirements.txt` includes the `playwright` Python package but it installs fine without `playwright install chromium`. `generate_ai.py` never imports Playwright. Saves ~2–3 min of Chromium download per run.

**`timeout-minutes: 20`.**  
7 API calls × 13s inter-call delay = ~91s minimum. With 3-retry exponential backoff (30s+60s+120s) and runner overhead: realistic ceiling ~12 min. 20 min provides buffer.

**Two rows per day in `fetch_log.csv`.**  
Snapshot row: `trigger=schedule`, `ai_outcome=""`. AI row: `trigger=workflow_run`, `ai_outcome=complete|partial|skipped|failed`. The `trigger` column distinguishes them. Additive, backward compatible.

### Acceptance criteria
- [ ] File exists at `.github/workflows/generate_ai.yml`
- [ ] `workflows: ["Daily Snapshot"]` matches `name:` in `collect.yml` exactly (case-sensitive)
- [ ] `if:` condition correctly handles both `workflow_dispatch` and `workflow_run`
- [ ] `workflow_dispatch` input `force_ai` exists with type boolean
- [ ] Install step does NOT contain `playwright install chromium`
- [ ] `git pull --rebase` present in commit step
- [ ] YAML validates: `python -c "import yaml; yaml.safe_load(open('.github/workflows/generate_ai.yml'))"`
- [ ] `grep "playwright install" .github/workflows/generate_ai.yml` → no output

### Alternatives considered

**Alt A (chosen): `workflow_run` + `workflow_dispatch`.**  
Event-driven, no race condition, independently triggerable.

**Alt B: Separate cron (30 min after snapshot cron).**  
Rejected: Race condition if scraper runs late (runner queue, retries). Misses the 2 PM UTC and 11:35 PM UTC snapshot cron triggers.

**Alt C: Separate job within `collect.yml`.**  
Rejected: Job still shares workflow context; `workflow_dispatch` on `collect.yml` would skip scraper but not easily; doesn't enable PR46 Task 1.2's `--force-ai` via a clean UI.

### Happy path
1. `collect.yml` fires at 22:05 UTC → scrapes, computes deltas, commits, exits success.
2. `generate_ai.yml` `workflow_run` event fires within seconds → checks out repo with fresh data → `pip install` (~30s, no Playwright) → `generate_ai.py` runs → writes `data/ai/YYYY-MM-DD.json`, `ai_run_summary.json`, `ai/index.json` → logs to `fetch_log.csv` → commits and pushes.
3. Dashboard reads `data/ai/index.json` — data is current.

### Edge cases

**`workflow_dispatch` with no snapshot data for today (e.g., weekend).**  
`generate_ai.py` reads the most recent snapshot date, not `date.today()`. Uses last available trading day's data. Correct.

**`workflow_dispatch` with `GEMINI_API_KEY` not set.**  
`generate_ai.py` exits 0 with `outcome="no_key"`. Log step records that. No AI JSON written. Commit step finds no changes. Correct.

**`collect.yml` fails (Finviz down).**  
`workflow_run` fires with `conclusion != 'success'`, `if:` condition rejects it. `generate_ai.yml` does not run. AI uses prior day's data on next successful run.

**`generate_ai.py` fails mid-way (partial completion).**  
On next `workflow_run`, `generate_ai.py` detects incomplete output and resumes missing fields only (existing incremental completion logic — unchanged by this plan).

**`--force-ai` passed before PR46 Tasks 1.1/1.2 land.**  
`generate_ai.py` doesn't yet have `argparse` — passing an unrecognized arg causes exit 1. The `ai_gen` step fails. Log step writes `ai_outcome="step_failed"`. Acceptable — prompts correct sequencing.

**`git pull --rebase` conflict (theoretically impossible).**  
Only `generate_ai.yml` writes `data/ai/` — no concurrent writers. If it did fail, GitHub emails job failure notification. No data loss — AI JSON files were already written; only the commit failed.

**`workflow_run` on a non-default-branch `collect.yml` run.**  
`workflow_run` only triggers for workflows running on the default branch. Correct.

### Dependencies
- Functionally independent of Phase 1 (can be deployed simultaneously or after).
- PR46 Tasks 1.1/1.2 should be deployed before using `force_ai` input (otherwise step fails gracefully as described in edge cases).

### Error / failure cases
- **YAML name mismatch:** If `workflows: ["Daily Snapshot"]` doesn't match `name:` in `collect.yml` exactly, `workflow_run` never fires.
- **Gemini quota exceeded:** Existing retry logic handles it; `ai_run_summary.json` shows `outcome="partial"`. Next day's `workflow_run` completes missing fields.
- **Push rejected:** `git pull --rebase` prevents this. If it fails anyway, GitHub emails the actor. No data loss.

### Follow-up backlog items
- Add `--date YYYY-MM-DD` flag to `generate_ai.py` so `workflow_dispatch` can regenerate a specific past date.
- Reduce `collect.yml` `timeout-minutes` from 30 → 15 (AI removal frees ~10 min headroom).
- Update `.session/SPRINT.md` to mark this decoupling complete once merged.

---

## Phased Execution Checklist

### Phase 0 — Pull latest, commit this plan
- [ ] `git fetch origin && git rebase origin/claude/elegant-babbage-hlxnfy`
- [ ] Create `plan/` directory if missing
- [ ] Write this file to `plan/PLAN_decouple_ai_workflow.md`
- [ ] `git commit -m "docs: execution plan for AI workflow decoupling"`
- [ ] `git push -u origin claude/decouple-ai-snapshot-workflow-7m75ex`
- [ ] Open draft PR if not already open

### Phase 1 — Modify collect.yml
- [ ] Remove "Generate AI analysis" step
- [ ] Remove `AI_GEN_OUTCOME` from log step env
- [ ] Replace `ai_run_summary.json` read block with `ai_outcome = ""; ai_fields_missing = ""`
- [ ] Remove schema migration block from log step
- [ ] `python -c "import yaml; yaml.safe_load(open('.github/workflows/collect.yml'))"` → no error
- [ ] `grep -n "GEMINI_API_KEY" .github/workflows/collect.yml` → no output
- [ ] `python3 -m pytest tests/ -q` → all pass
- [ ] `git commit -m "chore: remove AI step from collect workflow"`
- [ ] Push

### Phase 2 — Create generate_ai.yml
- [ ] Create `.github/workflows/generate_ai.yml` with full content above
- [ ] `python -c "import yaml; yaml.safe_load(open('.github/workflows/generate_ai.yml'))"` → no error
- [ ] `grep "playwright install" .github/workflows/generate_ai.yml` → no output
- [ ] Confirm `workflows: ["Daily Snapshot"]` matches `name:` in `collect.yml`
- [ ] `python3 -m pytest tests/ -q` → all pass
- [ ] `git commit -m "feat: add standalone generate_ai workflow"`
- [ ] Push

### Phase 3 — Verify in GitHub Actions (post-merge)
- [ ] Trigger `workflow_dispatch` on `collect.yml` → confirm no AI step in log, runtime ≤ 8 min
- [ ] Inspect `data/fetch_log.csv` newest row: `ai_outcome=""`, `ai_fields_missing=""`
- [ ] Check Actions tab: `generate_ai.yml` auto-triggered via `workflow_run` after step above
- [ ] `data/fetch_log.csv` has two new rows for same `run_date` (one from each workflow)
- [ ] Trigger `workflow_dispatch` on `generate_ai.yml` standalone → completes ≤ 20 min, no Chromium download in logs
- [ ] `data/ai/YYYY-MM-DD.json` and `data/ai/index.json` updated
- [ ] Dashboard AI Insights section loads correctly

---

## Verification Commands

```bash
# YAML syntax
python -c "import yaml; yaml.safe_load(open('.github/workflows/collect.yml'))"
python -c "import yaml; yaml.safe_load(open('.github/workflows/generate_ai.yml'))"

# No GEMINI_API_KEY in scraper workflow
grep -n "GEMINI_API_KEY" .github/workflows/collect.yml        # → (empty)

# No Playwright in AI workflow
grep -n "playwright install" .github/workflows/generate_ai.yml  # → (empty)

# Workflow name matches trigger exactly
grep "^name:" .github/workflows/collect.yml                    # → name: Daily Snapshot
grep "workflows:" .github/workflows/generate_ai.yml            # → ["Daily Snapshot"]

# All tests pass (no logic changes)
python3 -m pytest tests/ -q
```

---

## Rollback Strategy

If the decoupling causes problems:
1. Restore `Generate AI analysis` step to `collect.yml` from git history (`git show HEAD~1:.github/workflows/collect.yml`).
2. Delete `generate_ai.yml`.
3. Restore the `ai_run_summary.json` read block in the log step.

`fetch_log.csv` may have some rows with empty `ai_outcome` from the decoupled window — acceptable, doesn't break schema.

`generate_ai.py` is unchanged throughout, so any issues are confined to workflow YAML only.

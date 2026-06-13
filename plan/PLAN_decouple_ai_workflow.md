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

PR46 (merged 2026-06-12) contains tasks that touch overlapping files:

| PR46 Task | Interaction with this plan |
|-----------|---------------------------|
| **1.1** Add `_has_new_delta_data()` to `generate_ai.py` | Compatible / parallel. Script-only. |
| **1.2** Add `--force-ai` / `FORCE_AI` flag to `generate_ai.py` | Compatible / parallel. Script-only. This plan uses the `FORCE_AI` env var (already checked by `generate_ai.py`) rather than the `--force-ai` CLI flag — no sequencing dependency on PR46 1.2. |
| **1.3** Add `force_ai` input to `collect.yml` | **Superseded.** The input goes in `generate_ai.yml` instead. `collect.yml` is not touched for this feature. |
| **Phase 2** Schema enrichment, few-shot, validation logging | Fully compatible / parallel. Pure `generate_ai.py` changes; no workflow YAML interaction. |

---

## Scope of Changes

| File | Action |
|------|--------|
| `.github/workflows/collect.yml` | Modify: remove AI step, remove `AI_GEN_OUTCOME` env var, simplify log step |
| `.github/workflows/generate_ai.yml` | Create: new standalone AI workflow |
| `scripts/generate_ai.py` | **No changes** |
| `tests/` | **No changes** — infrastructure-only; existing tests cover all logic |

---

## Phase 0: Pull Latest + Commit This Plan (done)

1. `git fetch origin && git rebase origin/claude/elegant-babbage-hlxnfy`
2. Write this file to `plan/PLAN_decouple_ai_workflow.md`
3. Commit, push, open draft PR

---

## Phase 1: Modify `collect.yml`

### What changes

**Remove the "Generate AI analysis" step entirely** (currently lines 95–105):
```yaml
# DELETE this entire step:
- name: Generate AI analysis
  id: ai_gen
  if: steps.deltas.outcome == 'success'
  env:
    GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}
  run: |
    FLAGS=""
    if [ "${{ github.event.inputs.force_ai }}" = "true" ]; then
      FLAGS="--force-ai"
    fi
    python scripts/generate_ai.py $FLAGS
```

**Remove `force_ai` workflow input** from `on.workflow_dispatch.inputs` — it moves to `generate_ai.yml`.

**In the `Log fetch result` step:**
- Remove `AI_GEN_OUTCOME: ${{ steps.ai_gen.outcome }}` from `env:`
- Replace the `ai_run_summary.json` read block with `ai_outcome = ""; ai_fields_missing = ""`
- Remove the schema migration block — already applied to all existing rows
- Keep `LOG_COLUMNS` unchanged: `ai_outcome` and `ai_fields_missing` columns remain, always written as `""` in snapshot rows (no schema break)

### Acceptance criteria
- [ ] `collect.yml` has no reference to `GEMINI_API_KEY`
- [ ] `collect.yml` has no `ai_gen` step id
- [ ] `collect.yml` log step does not reference `ai_run_summary.json`
- [ ] `LOG_COLUMNS` still contains `ai_outcome` and `ai_fields_missing`
- [ ] `python -c "import yaml; yaml.safe_load(open('.github/workflows/collect.yml'))"` → no error
- [ ] `grep -n "GEMINI_API_KEY" .github/workflows/collect.yml` → no output

### Alternatives considered

**Alt A (chosen): Remove AI step; always write empty `ai_*` in snapshot log.**  
Zero schema change to `fetch_log.csv`; snapshot rows distinguish themselves via `trigger` column.

**Alt B: Remove `ai_*` columns from `fetch_log.csv`.**  
Rejected: breaking schema change; corrupts 14+ existing rows.

**Alt C: Separate job within `collect.yml`.**  
Rejected: doesn't enable independent triggering; doesn't solve "test AI without scraper."

---

## Phase 2: Create `generate_ai.yml`

### Design decisions

**`workflow_run` + `workflow_dispatch` (not cron).**  
`workflow_run` is event-driven — fires within seconds of `collect.yml` completing. `workflow_dispatch` enables independent invocations. Cron was rejected: race condition if scraper runs late. Note: `workflow_run` only fires when `collect.yml` runs on the default branch — this is the expected behaviour (data commits only land on the default branch).

**Checkout uses `head_sha`, not `head_branch`.**  
`github.event.workflow_run.head_sha` pins to the exact commit `collect.yml` produced. Using `head_branch` is a race condition: a second push between `collect.yml`'s commit and this workflow's checkout would cause the AI to run against the wrong data.

**`concurrency:` group to prevent parallel run conflicts.**  
A `workflow_dispatch` and a `workflow_run` could fire close together. Both write to `data/ai/YYYY-MM-DD.json` and then push. Without a concurrency group the second push fails or overwrites the first. Use `cancel-in-progress: false` to queue rather than kill.

**`FORCE_AI` env var, not `--force-ai` CLI flag.**  
`generate_ai.py` already checks `os.getenv("FORCE_AI")`. Setting it from the workflow input works today without any PR46 dependency. The `--force-ai` CLI flag (added by PR46 Task 1.2) can coexist; this plan doesn't use it.

**`timeout-minutes: 30`.**  
Happy path: 7 calls × 13s = ~91s. True worst case: 7 calls, each retrying 3× at 30s+60s+120s backoff = 7 × 210s = ~1470s ≈ 24.5 min plus overhead. 20 min is insufficient. 30 min provides safe headroom.

**No Playwright install.**  
`generate_ai.py` never imports Playwright. `requirements.txt` includes the `playwright` Python package, which installs without `playwright install chromium`. Saves ~2–3 min per run.

**`generate_ai.yml` does NOT write to `fetch_log.csv`.**  
`fetch_log.csv` is a snapshot health log — one row per snapshot run. Appending AI rows would break any query assuming one row per run date. `generate_ai.py` already writes `data/ai_run_summary.json` and `data/ai_run_log.jsonl` as its operational record; that's sufficient. The log step in `generate_ai.yml` only needs to emit console output for the Actions log.

**`git pull --rebase` before commit.**  
`collect.yml` commits snapshot data moments before `generate_ai.yml` starts. Rebase is safe: no file overlap between the two workflows' writes.

### Workflow skeleton

```yaml
name: Generate AI Analysis
on:
  workflow_run:
    workflows: ["Daily Snapshot"]   # must match name: in collect.yml exactly
    types: [completed]
  workflow_dispatch:
    inputs:
      force_ai:
        type: boolean
        default: false
        description: 'Force regeneration even if no new delta data detected'

permissions:
  contents: write

concurrency:
  group: generate-ai
  cancel-in-progress: false

env:
  FORCE_JAVASCRIPT_ACTIONS_TO_NODE24: 'true'

jobs:
  generate:
    if: >
      github.event_name == 'workflow_dispatch' ||
      github.event.workflow_run.conclusion == 'success'
    runs-on: ubuntu-22.04
    timeout-minutes: 30

    steps:
      - uses: actions/checkout@v4
        with:
          ref: ${{ github.event.workflow_run.head_sha || github.sha }}

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
          FORCE_AI: ${{ github.event.inputs.force_ai == 'true' && '1' || '' }}
        run: python scripts/generate_ai.py

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

### Acceptance criteria
- [ ] File exists at `.github/workflows/generate_ai.yml`
- [ ] `workflows: ["Daily Snapshot"]` matches `name:` in `collect.yml` exactly (case-sensitive)
- [ ] `if:` condition handles both `workflow_dispatch` and `workflow_run`
- [ ] Checkout uses `head_sha`, not `head_branch`
- [ ] `concurrency:` group present with `cancel-in-progress: false`
- [ ] `timeout-minutes: 30`
- [ ] `FORCE_AI` env var wired from `force_ai` input
- [ ] No `playwright install` in any step
- [ ] `git pull --rebase` present in commit step
- [ ] `python -c "import yaml; yaml.safe_load(open('.github/workflows/generate_ai.yml'))"` → no error

### Edge cases

**`workflow_dispatch` with no snapshot data for today (e.g. weekend).**  
`generate_ai.py` reads the most recent snapshot date, not `date.today()`. Uses last available trading day's data. Correct.

**`workflow_dispatch` with `GEMINI_API_KEY` not set.**  
`generate_ai.py` exits 0 with `outcome="no_key"`. No AI JSON written. Commit step finds no changes. Correct.

**`collect.yml` fails (Finviz down).**  
`workflow_run` fires with `conclusion != 'success'`; the `if:` condition rejects it. AI runs on next successful snapshot.

**`generate_ai.py` fails mid-way (partial completion).**  
On next `workflow_run`, existing incremental completion logic resumes missing fields only.

**Concurrent `workflow_dispatch` + `workflow_run`.**  
`concurrency:` group queues the second run; no push conflict.

**`workflow_run` on a non-default-branch `collect.yml` run.**  
`workflow_run` only triggers for the default branch. Correct.

---

## Implementation sequencing

**Phase 1 and Phase 2 should land in a single PR** — they touch different files with no conflict. Two commits, one PR:

1. `chore: remove AI step from collect workflow`
2. `feat: add standalone generate_ai workflow`

Merging both together eliminates the window where AI doesn't run at all. There is no reason to split them across separate PRs.

---

## Phased Execution Checklist

### Phase 0 — done
- [x] Branch at or ahead of `origin/claude/elegant-babbage-hlxnfy`
- [x] `plan/PLAN_decouple_ai_workflow.md` committed

### Phase 1 — Modify collect.yml
- [ ] Remove "Generate AI analysis" step
- [ ] Remove `force_ai` input from `on.workflow_dispatch.inputs`
- [ ] Remove `AI_GEN_OUTCOME` from log step env
- [ ] Replace `ai_run_summary.json` read block with `ai_outcome = ""; ai_fields_missing = ""`
- [ ] Remove schema migration block from log step
- [ ] `python -c "import yaml; yaml.safe_load(open('.github/workflows/collect.yml'))"` → no error
- [ ] `grep -n "GEMINI_API_KEY" .github/workflows/collect.yml` → no output
- [ ] `python3 -m pytest tests/ -q` → all pass
- [ ] Commit: `chore: remove AI step from collect workflow`

### Phase 2 — Create generate_ai.yml
- [ ] Create `.github/workflows/generate_ai.yml` per skeleton above
- [ ] `python -c "import yaml; yaml.safe_load(open('.github/workflows/generate_ai.yml'))"` → no error
- [ ] `grep "playwright install" .github/workflows/generate_ai.yml` → no output
- [ ] `grep "head_branch" .github/workflows/generate_ai.yml` → no output
- [ ] `python3 -m pytest tests/ -q` → all pass
- [ ] Commit: `feat: add standalone generate_ai workflow`
- [ ] Push both commits; open (or update) draft PR

### Phase 3 — Verify in GitHub Actions (post-merge)
- [ ] `workflow_dispatch` on `collect.yml` → no AI step in log, runtime ≤ 8 min
- [ ] `fetch_log.csv` newest row: `ai_outcome=""`, `ai_fields_missing=""`
- [ ] Actions tab: `generate_ai.yml` auto-triggered via `workflow_run`
- [ ] `workflow_dispatch` on `generate_ai.yml` standalone → completes ≤ 30 min, no Chromium in logs
- [ ] `data/ai/YYYY-MM-DD.json` and `data/ai/index.json` updated
- [ ] Dashboard AI Insights section loads correctly

---

## Verification Commands

```bash
# YAML syntax
python -c "import yaml; yaml.safe_load(open('.github/workflows/collect.yml'))"
python -c "import yaml; yaml.safe_load(open('.github/workflows/generate_ai.yml'))"

# No GEMINI_API_KEY in scraper workflow
grep -n "GEMINI_API_KEY" .github/workflows/collect.yml     # → (empty)

# No Playwright in AI workflow
grep -n "playwright install" .github/workflows/generate_ai.yml  # → (empty)

# head_sha used (not head_branch)
grep "head_sha" .github/workflows/generate_ai.yml           # → must appear

# Concurrency group present
grep "concurrency" .github/workflows/generate_ai.yml        # → must appear

# Workflow name matches trigger exactly
grep "^name:" .github/workflows/collect.yml                 # → name: Daily Snapshot
grep "workflows:" .github/workflows/generate_ai.yml         # → ["Daily Snapshot"]

# All tests pass
python3 -m pytest tests/ -q
```

---

## Rollback Strategy

If the decoupling causes problems:

1. Restore `Generate AI analysis` step to `collect.yml` from git history:  
   `git show HEAD~1:.github/workflows/collect.yml > .github/workflows/collect.yml`
2. Delete `generate_ai.yml`.
3. Restore the `ai_run_summary.json` read block and `AI_GEN_OUTCOME` env var in the log step.

`fetch_log.csv` may have some rows with empty `ai_outcome` from the decoupled window — acceptable, doesn't break schema. `generate_ai.py` is unchanged throughout, so any issues are confined to workflow YAML only.

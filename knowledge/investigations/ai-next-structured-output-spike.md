# AI-NEXT-P0c — structured-output spike: can `gemini-3.5-flash` hold the pack contract?

**Status:** ⏳ **Awaiting the run.** Methodology, corpus, and the decision rule are settled and
committed; the numbers are not, because the run needs Vertex/AI-Studio credentials and per
`CLAUDE.md` cannot execute from a Claude Code cloud session. Everything below the "Results" line
is a placeholder to be filled by whoever runs it.

**Task:** `.session/SPRINT.md` → `AI-NEXT-P0c` · **AC:** `planning/ai-next-user-stories.md` → US-P0c
**Contract under test:** `planning/ai-evidence-pack-schema.md` §3 (model output) and §3.1 (the four
validation rules) · **Harness:** `scripts/spike_structured_output.py` (shipped with P0a)

---

## 1. What this spike decides — and what it cannot

It selects **which of three renderer designs** we build. It has no cancel branch.

| Drop rate after retry-once (`full` cohort) | Design selected |
|---|---|
| ≤ 5% | Slot filling, **batched** calls — cheapest and fastest |
| 5–15% | Slot filling, **per-row** calls only — slower, identical product |
| > 15% | **Renderer-owned templates** — the model returns `kind` + `cites` only, and the app owns the sentence wording |

All three ship an AI-selected, fully-cited read on the Morning card. The third merely moves
phrasing from the model to the app, which is the *safer* product — less fluent, not less useful.

> This framing is a correction. The schema originally called it a "go/no-go", which reads as
> though a bad result kills the workstream. It does not, and the wording was fixed in schema §3.2
> and the SPRINT row on 2026-09-06 so nobody re-reads that risk into it.

**Why a spike at all:** this repo already tried forced-JSON mode once and backed it out
(`knowledge/.../ai-tab-daily-note.md`). Building a renderer on an unmeasured assumption that the
model holds a stricter contract than that one would repeat the mistake.

## 2. Corpus (US-P0c AC1)

Built by `_load_corpus()` from real `data/picks/sessions/{morning,pre_close}.csv` history.

- **Scope filter matches production** (US-P2a AC2): a row is sampled only if its status is
  actionable (`triggered` / `gapped_through` / `reclaim`) **or** its status changed vs the prior
  read. Measuring the drop rate on `setting_up` rows production never sends would flatter it.
- **Prior-row pairing matches production**: a `morning` row's prior is the *previous day's*
  `pre_close`; a `pre_close` row's prior is the *same day's* `morning`.
- **Deterministic** — `--seed` fixes the sample so a re-run measures the same corpus.
- **Shared `context` is included** (all rows for the latest sampled date + all 144 industries),
  because a spike run without it would measure a materially smaller prompt than production sends.

Verified with `--dry-run` on 2026-09-06 (no API spend):

```
corpus: 60 packs  cohorts={'full': 30, 'thin': 30}
statuses={triggered: 13, gapped_through: 13, reclaim: 12, failed_breakout: 9,
          invalidated: 7, setting_up: 6}
status_changed=37
shared prefix: 20,964 bytes (byte-identical across packs) · per-row tail: ~2,872 bytes
```

That clears US-P0c AC1 on every count: ≥50 packs (60), all actionable statuses present, and ≥10
status-changed rows (37).

### 2a. The cohort split, and why it exists

The Finviz setup block was only added to the session stores partway through the history:

| Columns | First date | Rows |
|---|---|---|
| `RSI`, `Volatility W/M`, `Rel Volume`, `52W High` | 2026-09-01 | 478 |
| `Price`, `SMA20`, `SMA50`, `ATR` | 2026-09-03 | 234 |
| everything else | 2026-08-10 | 2,408 |

So packs come in two shapes, and one blended rate would hide that:

- **`full`** — carries the setup block. This is the production-shaped pack, and **the cohort the
  thresholds in §1 are read against.**
- **`thin`** — setup block absent, those fields omitted from the pack with a `notes` caveat.
  Measures whether the model misbehaves around omitted fields (invents them, cites ids that
  aren't there) — real information the full cohort cannot give.

Owner decision, 2026-09-06. Rejected alternatives: waiting ~2 weeks for depth (no reason to block
the workstream), and running on the 234 full-field rows alone (2 trading days is too narrow a
sample to hang a threshold on, and it tests nothing about null handling).

### 2b. Known limitation — state it, don't bury it

The sampled rows span many dates, but the shared `context` block is built from a single date. So
the spike is a valid test of **contract adherence** (do slots resolve, do cites stay in the pack,
does the model keep digits out of `text`) and **not** a test of reasoning quality — for most rows
the broad context is not that row's own session. Do not quote this spike as evidence the prose is
*good*, only that it is *well-formed*. Judging quality needs the owner reading real output on the
Morning tab, which is P2b.

## 3. How to run it

Cannot run from a Claude Code cloud session (no Vertex creds; see `CLAUDE.md`). Locally or in
GitHub Actions, same auth ladder as `generate_ai.py`:

```bash
# Vertex express key (preferred)
GOOGLE_GENAI_USE_VERTEXAI=true GOOGLE_API_KEY=... \
    python3 scripts/spike_structured_output.py --limit 60

# or AI Studio
GEMINI_API_KEY=... python3 scripts/spike_structured_output.py --limit 60

# corpus/prompt inspection only, no API calls — this part DOES run anywhere
python3 scripts/spike_structured_output.py --dry-run --limit 60
```

Roughly 60–120 calls (retry-once on failures). It writes
`knowledge/investigations/ai-next-structured-output-spike.json` with per-call detail plus a
summary, and prints a markdown table ready to paste into §4 below.

`DailyQuotaExhaustedError` propagates rather than being swallowed — a truncated run must not be
mistaken for a measured result.

---

## 4. Results

> **Not yet run.** Paste the harness's printed table here, then complete §5–§7.

| Cohort | n | validated 1st try | validated after retry | **dropped** | median latency |
|---|---|---|---|---|---|
| full (2026-09-03+) | — | — | — | — | — |
| thin (setup block absent) | — | — | — | — | — |
| **all** | — | — | — | — | — |

**Selected renderer design (read against the `full` cohort):** —

**Rejections by rule:** — (which of the four §3.1 rules the model actually trips is the most
actionable output here: a concentration in one rule is usually a prompt fix, not a model limit)

### 4a. Batching (US-P0c AC3)

Per-row vs 5-row vs 10-row calls, to set P2's ≤10-min budget from data rather than guesswork.

| Mode | calls for a 40-row session | drop rate | wall clock |
|---|---|---|---|
| per-row | 40 | — | — |
| batch-5 | 8 | — | — |
| batch-10 | 4 | — | — |

> **Not yet implemented in the harness.** The current script measures per-row only. Batching is a
> small addition to `run()` (group N packs into one call, one `statements` array per subject) and
> should be written *after* the per-row numbers land — if per-row already clears the 10-minute
> budget, batching is an optimisation nobody needs to build. Tracked as **AI-NEXT-P0c-BATCH** in
> `.session/SPRINT.md`.

### 4b. Projected wall clock for a 40-row session (US-P0c AC4)

—

## 5. Three example outputs (US-P0c AC4)

**Good (validated first try):** —

**Retried (failed once, passed on retry):** —

**Dropped (failed twice):** —

## 6. Decision

—

## 7. Follow-through

- Write the outcome into the `AI-NEXT-P0c` SPRINT row.
- If the >15% fallback path is taken, amend `planning/ai-evidence-pack-schema.md` §3 **in the same
  PR** (US-P0c AC5) — the contract's `text`/`slots` fields become renderer-owned and the schema
  must say so.
- Unblocks `AI-NEXT-P0b` (shared renderer) and `AI-NEXT-P2a` (Morning pipeline).

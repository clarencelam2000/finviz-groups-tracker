# ADR-006: AI call capture & visibility — two-tier, committed-not-gitignored

- **Status:** Accepted (plan approved; implementation on hold)
- **Date:** 2026-06-22
- **Context PR:** #154
- **Supersedes / relates to:** `planning/ai-capture-and-visibility.md`,
  `planning/ai-architecture-revamp.md`

## Context

`scripts/generate_ai.py` makes ~11 Gemini calls per run. The exact **(input data block,
prompt, raw response, parsed output)** for each call is never persisted — only status,
latency, and call counts land in `data/ai_run_log.jsonl`. This makes a bad briefing
undebuggable without a local re-run, makes prompt edits invisible in review, and leaves
users with conclusions they can't trace back to the underlying signals.

The pure `serialize_*()` / `build_*_prompt()` functions are a clean seam: capture can be
added as additive plumbing, no refactor of generation logic.

## Decision

1. **Two-tier capture from one hook** in `generate_for_group()`:
   - **Tier 1 — provenance** (`data/ai/provenance/{date}.json`): the input data block only.
     Small, deterministic-from-CSV, **committed permanently**. Powers a user-facing PWA
     "Behind this" drawer.
   - **Tier 2 — debug capture** (`data/ai/debug/{date}.json`): full prompt + raw response +
     parsed output + token usage + latency. Dev-facing; powers preview/diff/eval.

2. **Committed, not gitignored, with rolling retention.** Both tiers are committed. Tier 2
   keeps a **rolling 30-day window in `HEAD`** (`CAPTURE_RETENTION_DAYS`); older files are
   pruned from `HEAD` but remain recoverable in git history. Capture is gated by
   `--capture` / `AI_CAPTURE` (ON in CI, off by default locally).

3. **`_call_api()` returns a `CallResult(text, usage, latency)` dataclass** instead of a
   bare string, so usage/latency reach the capture hook cleanly.

4. **Token-spending paths are quarantined.** Live evaluation lives in a separate
   `scripts/eval_ai.py`, never on the nightly path; the highest-value guard (output group
   names must appear in the input block) is fully offline.

5. **Vertex express API key** (`GOOGLE_API_KEY`) as a third auth path, sidestepping AI
   Studio 429s and ADC.

## Alternatives considered

- **Gitignore Tier-2 (original draft).** Rejected: ephemeral CI/cloud runners reclaim
  uncommitted files, so nightly captures would be lost. VP flagged this directly.
- **Commit Tier-2 unbounded.** Workable (~12 MB/yr) but noisier working tree; rolling
  retention keeps `HEAD` clean while git history preserves everything.
- **`_call_api` returns a tuple / side-channel dict.** Rejected in favor of the dataclass:
  self-documenting, easy to extend, minimal test churn (assert on `.text`).
- **Streamlit "AI Lab".** Rejected — VP doesn't use Streamlit; a static vanilla-JS viewer
  reuses the existing PWA stack with no new dependency.
- **PWA `?debug=1` serving Tier-2.** Deferred — GitHub Pages is public; serving prompts
  needs an authenticated endpoint, not a flag.

## Consequences

- **Positive:** every call is auditable; prompt edits diff in PRs (snapshot tests); users
  can see the data behind each insight; a token-cost paper trail accrues while credits are
  free; nothing is lost to ephemeral runners.
- **Cost:** nightly commits grow by ~33 KB/day of Tier-2 (bounded ~1 MB by the 30-day
  window); a small, recoverable prune runs each capture.
- **Reversible:** capture is flag-gated and additive — disable by not passing `--capture`;
  remove by deleting one helper + one call site. No one-way door.

## Open items

- Provenance granularity (verbatim block vs. structured per-signal) — verbatim for v1.
- Optional CI-artifact upload of full Tier-2 for long-term archive — add once eval is live.
- CI repo secret for `GOOGLE_API_KEY` on the nightly path — TODO at Phase 7.

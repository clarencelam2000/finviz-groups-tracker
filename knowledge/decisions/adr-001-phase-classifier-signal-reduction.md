# ADR-001: Phase classifier receives curated signal summary, not raw snapshot table

**Date**: 2026-06-15
**Status**: Accepted — watch first live run

## Context

Before the PR #94 freeform-note rebuild, `build_phase_prompt` fed the phase
classifier a full serialized snapshot of all sectors (every perf column for every
sector). This gave the model maximum context for labelling the rotation phase
(Early / Mid / Late / Defensive), but it also meant ~150 raw numbers per call —
most of which are redundant given our derived signals.

The PR #94 rebuild replaced this with curated signal blocks:
- `serialize_strength_signals` output (breadth one-liner + all-green names + sustained leaders)
- `serialize_momentum_leaders` output (top-5 by momentum_score)

The phase prompt still suggests the four canonical labels so the PWA color map
and 14-day history strip stay intact.

## Decision

Accept the reduced-context approach. The curated blocks contain the signals that
most reliably distinguish rotation phases:

| Phase | Key signal in curated block |
|---|---|
| Early | Few all-green, momentum leaders are cyclicals |
| Mid | Broad all-green, high breadth, growth/tech in leaders |
| Late | All-green narrowing (breadth drops), energy/materials leading |
| Defensive | Breadth low, utilities/healthcare in sustained-strong block |

The model should be able to infer the phase correctly from these. Reducing input
tokens also cuts cost per call.

## Alternatives considered

**Keep full raw snapshot**: More raw data, but most of it is noise for a
four-label classifier. Also inconsistent with the plan's stated goal of curated
signal blocks for all prompts.

**Hybrid — add explicit "sector list sorted by YTD rank"**: Would help surface
Defensive signal (Utilities at rank 1 is clearer than "breadth low"). Deferred
until first live run shows a miss.

## Consequences

1. **Watch item**: The Defensive phase requires utilities/healthcare to appear in
   the `sustained_strong` block (top-N by rank_month/quarter/half). If they rank
   just outside top-N, the classifier may see no Defensive signal and guess
   Mid/Late instead. Check the first few live runs against market context.

2. **Easy fallback**: If classification accuracy is poor, add a compact
   "sectors by YTD rank" one-liner to `build_phase_prompt` — a single sorted
   list of 11 names is ~30 tokens. No architecture change needed.

3. **Smaller input = lower cost**: Typical phase prompt is now ~300–400 tokens
   down from ~600–700. With 1 phase call per day, savings are negligible in
   absolute terms but correct directionally.

## First-run checklist

After the first successful `generate_ai.yml` run post-PR-#94:
- [ ] Open `data/ai/<date>.json`, check `sectors.rotation_phase.label`
- [ ] Does it match your qualitative read of where we are in the cycle?
- [ ] Are the Defensive names (Utilities / Healthcare / Consumer Staples) present
      in the `serialize_strength_signals` output for that date?
- [ ] If wrong two days in a row → add the sorted-by-YTD-rank one-liner to the
      phase prompt and retest.

# Plan: Sector → Industry Hierarchy Feature Roadmap

**Status:** Paused 2026-06-25 in favor of the Stock Picks workstream; resuming 2026-07-02.
Phase 1 shipped and live. Phase 2 was built in full but never merged — see below.
**Owner:** VP sign-off required before each tier  
**Last updated:** 2026-07-02  
**Prerequisite:** `data/finviz_sector_industry_map.json` ✅ Merged (PR #171)

---

## ⚠️ Current State (read this first — 2026-07-02)

This workstream was paused after Phase 1 shipped so the team could build the Stock Picks
feature (Focus scores, Ariel Hernandez criteria, HoD toggle, charts deep-links — see
`planning/stock-picks-from-leading-groups.md` and the Picks section of `.session/SPRINT.md`).
Picks absorbed ~150 commits on default in the meantime. Two things changed that this plan
needs to account for before anyone resumes building:

**1. Phase 1 is done and live.** TASK-6B + INS-7 (Streamlit sidebar filter + breadth metric)
shipped in PR #177, as this doc already recorded.

**2. A *different, lighter* version of Feature B shipped independently — not from this plan's
Phase 2 sequence.** Commit `122a4d1` ("fix: add sector breadth table to PWA Strength tab",
merged, live) added a sector breadth **table** to the PWA Strength tab (Industries view) —
timeframe-togglable (week/month/quarter/half), reusing the `rank_ytd ≤ n/2` threshold. This
was scoped as a fast-follow to PR #177 to bring Streamlit's breadth metric to the PWA, not as
an implementation of this plan's Feature B (which specifies a breadth *bar on sector cards in
the Today tab*). It covers similar ground but in a different tab with a different UX.

**3. Features A + B + F were actually built in full — but the PR was never merged and is now
stale.** Draft **PR #178** (`claude/fervent-thompson-rlvfs1`, branched right after PR #177)
implements exactly what Phase 2 of this plan specifies: expand-in-place drill-down (Feature A),
a fill-bar + count on sector cards in the Today tab (Feature B), and sector-relative rank shown
in the drill-down (Feature F) — with the VP UX decisions from 2026-06-24 baked into the PR body
(expand-in-place chosen over a new tab; count+mini-bar chosen for the breadth detail; sector
rank shown in drill-down only). It sat untouched when the team pivoted to Picks and is now
**177 commits behind default** with GitHub reporting `mergeable_state: dirty`.

I dry-ran the merge in a scratchwork worktree to find out how bad this actually is (verified,
not just GitHub's cached mergeability flag): **6 files conflict** — `.session/WORK_LOG.md`,
`.session/session-notes.md`, `docs/index.html`, `docs/releases.json`, `docs/sw.js`, and this
plan file (add/add). Five of the six are mechanical (session-notes appends, a releases.json
prepend, and a `sw.js` CACHE version bump — PR #178 targets `finviz-v30`, default is now at
`finviz-v48`). **`docs/index.html` has a real semantic conflict, not just a textual one:**
PR #178 introduces its own taxonomy-loading path (`loadTaxonomyAndBreadth()`,
`computeSectorBreadth(industryDelta, taxonomy)`) that duplicates — under similar names but a
different signature — the taxonomy-loading and breadth-computation logic the Strength-tab
table (`122a4d1`, already merged) added independently (`loadTaxonomy()`,
`computeSectorBreadth(delta, taxonomy, rankCol)`). Landing PR #178 requires reconciling these
two code paths (one shared taxonomy loader, keep both render targets since they serve
different tabs) — not a blind conflict-resolution pass.

**Recommendation: don't discard PR #178 and don't rebuild it from scratch.** The code is real,
tested against the VP's actual UX decisions, and Feature A (drill-down) isn't replicated
anywhere else on default. The fix is a rebase-and-reconcile session: rebase
`claude/fervent-thompson-rlvfs1` onto current default, merge the two taxonomy loaders into one,
keep the Strength-tab table and add the Today-tab bar/drill-down alongside it, bump the release
triplet to today's date and current cache version, then land it. Estimate: ~1 session. Until
that happens, do **not** start a fresh implementation of Feature A/B/F — the work already
exists.

---

## Executive Summary

The sector→industry taxonomy map is now in the codebase (PR #171). This single artifact
unlocks the largest feature surface in this product's roadmap. Every item in this document
is a consumer of data we already compute — the only missing piece was the hierarchy itself.

Before this, sectors and industries were two disconnected flat lists. The hierarchy turns
them into a tree, and a **tree is what makes capital rotation navigable** instead of just
observable. The difference between "interesting" and "actionable."

This document is the single source of truth for:
1. What the map is and where it came from (§ Foundation)
2. The complete feature set it unlocks — 21 distinct features (§ Feature Catalogue)
3. Build order and priorities (§ Recommended Sequence)
4. VP decision points and scope gates (§ Decision Points)

Any teammate picking this up cold should be able to answer "what do I build next and why"
from this document alone.

---

## Foundation: What We Have

### The Map (✅ Done — PR #171)

```
data/finviz_sector_industry_map.json   — structured dict + metadata
data/finviz_sector_industry_map.csv    — flat (finviz_sector, finviz_industry) pairs
```

**Source:** fasiha/finviz-git-scraper — a Finviz treemap archive fetched via
plain HTTP (no Playwright, no Cloudflare). Authoritative because it reads Finviz's own internal
taxonomy directly. IMPORTANT NOTE: the data is stale and last updated in March 2025. However, the sector to industry mappings are still usable.

**Coverage:**
- 11 sectors, 145 industries
- 144/144 of our tracked industries match (100%)
- 1 extra: `Infrastructure Operations` (Industrials) — new Finviz addition not yet in our CSVs
- Validated against `data/industries/snapshots.csv` at generation time

**Load pattern (shared across all consumers):**
```python
import json
from pathlib import Path
TAX = json.loads(Path("data/finviz_sector_industry_map.json").read_text())["sectors"]
# TAX = {"Technology": ["Semiconductors", "Software - Application", ...], ...}
```

There is no re-seeding path via fasiha/finviz-git-scraper - the repo is effectively unmaintained.

**Staleness tripwire (not yet built):** A future task should add a warning in `collect.py` or
a nightly test when a live industry name is missing from the map — so taxonomy drift is caught
before it silently corrupts breadth denominators.

### Immediately Unblocked (Sprint Board)

| ID | Feature | Effort |
|----|---------|--------|
| INS-7 | Sector Breadth metric — "7 of 11 Technology industries are top-half" | M |
| TASK-6B | Streamlit sidebar sector filter | S |

Both are coded out in the sprint board. Build these first; they validate the map works
end-to-end and unblock everything below.

---

## Feature Catalogue

Features are grouped by the problem they solve. Read the groups in order — each group
builds on the last. Within a group, features are ordered by effort and impact.

---

### Tier 1 — Navigation (reduce mental load)

The core problem today: 144 industries as a flat ranked list. Users manually
cross-reference sectors. These features collapse that.

**A. Drill-down navigation in PWA** *(M effort)*
Tap a sector card → it expands inline to show its constituent industries, ranked, with
deltas. Currently a user comparing "is Energy strong because of Oil & Gas or Solar?"
must tab-switch and mentally cross-reference. One tap-to-expand closes that gap.
This is the single biggest UX win from the hierarchy — it changes how the app *feels*.

**B. Breadth bar on sector cards** *(S effort)*
A one-line visual on each sector card: "7/11 industries top-half ↑". Zero extra
navigation required — the signal is right on the card. Pure mental-load reduction.
This is the MVP version of INS-7 in the PWA (INS-7 is the Streamlit version).

**C. Leaders & Laggards mini-list within sector** *(S effort)*
On the drill-down (feature A), surface the #1 and last-place industry for that sector.
Turns a 144-row scan into "here's where to look." Most sectors have 8–25 industries —
users want the poles, not a ranked scroll.

**F. Rank within sector alongside rank within universe** *(S effort)*
An industry ranked 60/144 universe-wide might be #2 of 11 in Basic Materials. Both
numbers tell a different story. Show both. Adds interpretive context at zero compute
cost — the data is already there.

**G. Sector-relative coloring** *(S effort)*
Color industries by how they rank *against their sector peers*, not just the universe.
Surfaces "best house on a bad street" — an industry that's holding up well even as its
sector is down. Useful when whole sectors are under pressure.

---

### Tier 2 — Signal (make things actionable)

These features answer *what should I do with this information*.

**D. Divergence alerts / Rotation Radar tab** *(M effort)*
Auto-surface the setups where sector headline and industry breadth *disagree*:
- "Sector is green, only 2/12 industries participating" → narrow, fragile rally
- "Sector is flat, 9/12 industries quietly turning up" → accumulation / early rotation

These are the highest-signal patterns in rotation analysis and are completely invisible
in flat lists. A dedicated tab or card type that filters for these divergences is the
feature that makes someone *open the app daily*. We have all the data to compute this now.

**E. Breadth-confirmed momentum** *(S effort)*
We already compute `momentum_confirmed = momentum_score × rank_agreement` (strength
gated by cross-timeframe consistency). Add a second gate: industry momentum confirmed
by sector breadth. A strong industry inside a strengthening sector is a materially
better signal than a lone mover in a weak sector.
New column: `momentum_breadth_confirmed` in `deltas.csv`.

**J. Sector consistency / "trust score"** *(S effort)*
We have `rank_agreement` and `rank_trend_slope` per group. Roll these up over a sector's
industries: is this sector's leadership *steady* or *whipsawing*? A sector breakout backed
by 3 weeks of consistent breadth improvement deserves more confidence than one that
flickered up yesterday. Show as a "Steady / Mixed / Choppy" badge on sector cards.

**M. Crowding / concentration warning** *(S effort)*
The inverse of breadth: flag when a sector's entire gain is carried by one or two industries.
"Technology +2.1% — driven entirely by Semiconductors (+8.4%). 10/12 other industries flat
or negative." This is a late-stage, fragile-rally risk signal — the thing every momentum
dashboard is missing. It's breadth's evil twin and costs nothing extra to compute.

**P. Sector rank ÷ industry spread tension** *(S effort)*
A sector ranked #2 overall whose industries are *scattered* (some top, some bottom) is
fundamentally different from a #2 sector where all 12 industries are in the top 20. Surface
the intra-sector spread of industry ranks. Flags when headline sector rank is misleading.

**Q. "Quiet movers" — pre-breakout breadth screen** *(M effort)*
Filter for sectors/industries with *improving breadth AND rising trend slope but still
middling headline rank*. These are the things about to show up on everyone else's radar.
A momentum tool that only surfaces what's already #1 is late by definition. This is
genuinely early-signal territory. Pure consumer of `rank_trend_slope` + breadth.

**R. Market-wide breadth gauge** *(S effort)*
Aggregate breadth across all 11 sectors into one number: "68% of industries top-half and
rising." A market risk-on/risk-off dial. One glance answers "should I even be leaning in?"
Natural top-of-PWA home screen placement. The highest-level mental-load reducer of all.

---

### Tier 3 — Retention (earn the daily open)

These features change whether users come back tomorrow. They depend on Tier 1 and 2
being built first — they're the payoff layer.

**H. Rotation flow map** *(L effort)*
The signature feature. A Sankey / flow visualization: capital leaving fading sectors
→ entering emerging ones, over a chosen lookback. We already have `regime_short_long`
(emerging vs. fading signal) per group — the hierarchy lets us aggregate to sector level
and *show the money moving*. This is the one screenshot that makes someone send the app
to a friend. Answers the entire premise of the product in a single picture.

**I. "What changed since you last looked" digest** *(M effort)*
Store the user's last-viewed timestamp in PWA local storage (zero backend). On open, lead
with: "Since Tuesday: Energy breadth 4→9, Semis entered top 10, Utilities rolled over."
This is the highest-leverage mental-load reducer possible. It does the diffing users
currently do in their head and is the thing that earns a daily open.
The hierarchy makes the digest *narratable* ("the Energy move is broad") vs. a wall of
144 row-deltas. The underlying comparison logic already exists in our delta columns.

**K. Natural-language daily brief** *(M effort)*
Feed the hierarchy + deltas to the AI briefing layer (already in `generate_ai.py`).
Current AI brief is group-by-group. With sector context it can narrate: "Defensives are
quietly rotating in — Utilities and Consumer Defensive both saw breadth jump while Tech
narrowed to mega-cap leadership." Grounded in structured numbers so hallucination risk
is low. Turns a 5-minute scan into a 15-second read.
**Note:** `generate_ai.py` is the integration point. The briefing prompt template is
the only thing that changes — no schema migration needed.

**L. Watchlist with hierarchy-aware alerts** *(M effort)*
Let users star industries *or* whole sectors. Alert logic gets smart: "your starred
industry just became #1 in its sector" or "the sector containing 3 of your watched
industries just turned." Personalization + actionability, still backend-free (PWA local
storage). Depends on feature A (drill-down) being built first for UX coherence.

**T. Time-travel / replay slider** *(L effort)*
A scrubber on the rotation flow map (feature H) that lets users drag through the last N
sessions and watch breadth shift sector to sector. Rotation is inherently temporal — a
snapshot undersells it. Seeing Energy drain and Utilities fill over two weeks is visceral
in a way a table never is. The data is already in our append-only CSVs; this is purely
a rendering problem. Aspirational; build after H.

**V. Shareable sector cards** *(S effort)*
Render a single sector's breadth + leaders + flow as a clean image for sharing/screenshot.
Zero-cost growth loop. The hierarchy is what makes one card tell a self-contained story
(sector headline + its industries + breadth bar = complete picture). Currently no single
card does this.

---

### Tier 4 — Stock Bridge

**O. Sector → Industry → Stocks** *(M effort)*
The missing last mile. The hierarchy closes the loop: sector → industry → *the actual
tickers in it*. Tap "Semiconductors is leading" → see NVDA, AVGO, AMD.
The plumbing already exists: FMP `/screener` endpoint + Cloudflare Worker `/stocks`
endpoint is already planned as TICKER-5 in the sprint board. The hierarchy is the
navigation entry point that makes TICKER-5 feel natural rather than bolt-on.
**Note:** This is Phase 7 of the Ticker Lookup plan. Do not start until TICKER-4 is
validated in production.

---

### Tier 5 — Trust & Honesty

These are small but important. Users who might trade off this tool live or die on trust.

**S. Coverage honesty in UI** *(S effort)*
The map covers 144/145 of our tracked industries. Rather than hide the 1 gap, show it:
"Breadth based on 11/12 mapped industries." Small trust-building touch with outsized
credibility impact on users who notice data quality.

**U. Smart empty/early-data states** *(S effort)*
We're still young on history — 50d deltas are NaN for many groups. Instead of blank cells,
use the hierarchy to degrade gracefully: "50-day breadth available in 31 sessions" or fall
back to the longest window we do have. Turns the cold-start period into something that
feels intentional.

**N. Historical analog / "this looks like"** *(L effort, deferred)*
Match the current breadth-rotation fingerprint against past setups. Aspirational — needs
6+ months of data. The hierarchy is the prerequisite so it's noted here to ensure we
don't architect ourselves out of it. Revisit ~Q4 2026.

---

## Recommended Build Sequence

### COMPLETED - Phase 1 — Validate the map works (1–2 sessions)
Build the two immediately unblocked sprint items. These are the "does the plumbing work"
check before investing in the larger surface.

| Priority | ID | Feature | Effort | File(s) |
|----------|----|---------|--------|---------|
| 1 | TASK-6B | Streamlit sidebar sector filter | S | `dashboard/app.py` |
| 2 | INS-7 / B | Sector Breadth (Streamlit + PWA bar) | M | `dashboard/app.py`, `docs/index.html` |

### Phase 2 — Navigation layer (1–2 sessions)

**A, B, and F are already built** — see PR #178 (`claude/fervent-thompson-rlvfs1`), open as a
draft, unmerged, 177 commits stale as of 2026-07-02. Do not re-implement; rebase and reconcile
per the § Current State note above. C and R below are the only genuinely un-started items.

| Priority | ID | Feature | Effort | File(s) | Status |
|----------|----|---------|--------|---------|--------|
| 3 | A | PWA drill-down navigation | M | `docs/index.html` | ✅ Built, unmerged — PR #178 |
| 4 | F | Rank within sector | S | `docs/index.html` | ✅ Built, unmerged — PR #178 (shown in drill-down only, per VP decision) |
| — | B | Breadth bar on sector cards | S | `docs/index.html` | ✅ Built, unmerged — PR #178. Note: a *different* breadth table shipped separately to the Strength tab (`122a4d1`, merged) — not the same UX, both are wanted. |
| 5 | C | Leaders & Laggards mini-list | S | `docs/index.html` | Not started |
| 6 | R | Market-wide breadth gauge | S | `docs/index.html` | Not started |

### Phase 3 — Signal layer (1–2 sessions)
The features that make things actionable. D is the headline.

| Priority | ID | Feature | Effort | File(s) |
|----------|----|---------|--------|---------|
| 7 | D | Divergence alerts / Rotation Radar | M | `docs/index.html`, `dashboard/app.py` |
| 8 | M | Crowding / concentration warning | S | `docs/index.html`, `dashboard/app.py` |
| 9 | J | Sector consistency trust score | S | `docs/index.html`, `dashboard/app.py` |
| 10 | Q | Quiet movers screen | M | `docs/index.html`, `dashboard/app.py` |

### Phase 4 — Retention layer (2–3 sessions)
The features that earn daily opens. I before K; H is the showpiece.

| Priority | ID | Feature | Effort | File(s) |
|----------|----|---------|--------|---------|
| 11 | I | Since-last-look digest | M | `docs/index.html` (local storage only) |
| 12 | K | AI brief with sector context | M | `scripts/generate_ai.py` |
| 13 | H | Rotation flow map | L | `docs/index.html`, `dashboard/app.py` |
| 14 | L | Hierarchy-aware watchlist alerts | M | `docs/index.html` |

### Phase 5 — Polish and bridge (ongoing)
| Priority | ID | Feature | Effort | Notes |
|----------|----|---------|--------|-------|
| 15 | G | Sector-relative coloring | S | After Phase 2 |
| 16 | E | Breadth-confirmed momentum column | S | Requires `compute_deltas.py` change |
| 17 | P | Rank tension indicator | S | After Phase 3 |
| 18 | V | Shareable sector cards | S | After Phase 4 |
| 19 | S | Coverage honesty | S | Any time |
| 20 | U | Smart empty states | S | Any time |
| 21 | O | Sector→Industry→Stocks bridge | M | After TICKER-4 validated |
| 22 | T | Replay slider | L | After H |
| 23 | N | Historical analog | L | Defer to Q4 2026+ |

---

## Decision Points (VP)

Before starting each phase, confirm:

**Phase 1 gate: ✅ PASSED 2026-06-24.** Map validated (100% match), TASK-6B + INS-7 shipped
(PR #177).

**Phase 2 gate (feature A): ✅ DECIDED 2026-06-24, captured in PR #178's body.** Expand-in-place
on the existing Today tab sector cards was chosen over a new "Sectors" tab (lower effort, no new
tab to maintain). Breadth detail: count + mini-bar. Sector rank: shown in drill-down only. No
new decision needed — just land the PR (see § Current State).

**Phase 3 gate (feature D):** Decide whether Rotation Radar is a new tab or a section within
Today tab. A new tab signals product-level importance; a section is faster to ship. Recommend
new tab — it's the headline feature and deserves the real estate. **Linked decision:** Feature A
was built as expand-in-place on the Today tab (not a new tab), which makes the Today tab the de
facto sector-navigation home. Feature D's new-tab-vs-section call should be made with that in
mind, not in isolation — a second nav pattern for essentially the same underlying data (sector
cards + industry breadth) risks an incoherent nav model. Decide A's and D's tab placement in the
same conversation.

**Phase 4 gate (feature H):** Flow map requires a charting library decision.
Options: D3.js Sankey (full control, ~300 lines), Observable Plot (simpler), or a static
SVG approximation (fastest). **Constraint to weigh before picking:** the PWA (`docs/index.html`)
is a single static file with no bundler and no npm — D3 is an npm-distributed library, and
d3-sankey is a separate package from D3 core, so "D3.js Sankey" here means either a CDN import
of the full bundle (~500KB+) or introducing a build step neither of which exist today. Observable
Plot has a CDN ESM build that works in plain `<script type="module">` with no build step — the
lower-friction option for this codebase's actual constraints. Decide before starting H.

**Phase 4 gate (feature I):** Before coding, pick the implementation approach — this determines
whether I is really M effort or closer to L:
- **Snapshot-on-visit:** store computed breadth values (not just a timestamp) in localStorage
  each time the user visits, diff against the previous snapshot on next open.
- **Replay-from-CSV:** store only a timestamp; on open, find the nearest historical row in the
  already-fetched delta CSVs and recompute breadth retroactively.
Replay-from-CSV avoids stale-localStorage-value risk but requires more non-trivial JS logic over
the full CSV history already in memory. Pick one and scope Feature I's effort against it before
starting.

**Phase 4 gate (feature K):** AI brief with sector context requires prompt engineering
iteration. Budget 1 session for prompt iteration before treating K as "done."

**Feature E note:** `momentum_breadth_confirmed` requires more than a schema/header change —
same as PIPE-1's `momentum_score` discontinuity fix, adding a new column to `deltas.csv` means
a full historical recompute (`compute_deltas.py --date <d>` per existing date) or the column is
NaN for all existing history. Budget for the recompute pass, not just the column addition.

**Feature B PWA constant:** When Feature B's Today-tab breadth bar lands (via PR #178), the
"top-half" threshold (`n/2`, currently inlined in both the Strength-tab table and PR #178's
drill-down) should become a named constant documented in CLAUDE.md's PWA display-thresholds
table, matching `REGIME_THRESHOLD` / `ACCEL_STRONG` / etc. It isn't currently.

**Staleness tripwire (anytime):** Add a check in `collect.py` or a nightly test that warns
when a live industry name is missing from `finviz_sector_industry_map.json`. Without this,
taxonomy drift causes silent breadth denominator errors. Assign to any session with spare
capacity — it's an S effort.

---

## Architectural Principles

**The map is a data artifact, not a hardcoded dict.**
The original sprint items (INS-7, TASK-6B) scoped the mapping as a hardcoded dict inside
`dashboard/app.py`. PR #171 correctly promoted it to a committed file in `data/`. This was
the right call. Reasons:

1. The PWA (JS), Streamlit (Python), Worker (JS), and AI pipeline (Python) all need it.
   A dict in one file can't be shared across all four.
2. It survives ephemeral cloud containers (committed to repo).
3. The cross-validation logic in `seed_taxonomy.py` is only possible because the artifact is
   a file with a known path — a hardcoded dict has no equivalent integrity check.

**Corollary:** Any future feature that needs the map should load it from the JSON file, not
copy the contents inline. The JSON load is cheap (~1ms) and keeps a single source of truth.

**Future: `finviz_sector` column on industry rows (deferred).**
Once the map is validated in production (Phase 1), consider adding a `finviz_sector` column
to `data/industries/snapshots.csv` at collect time. This enables `groupby("finviz_sector")`
directly on the deltas DataFrame — useful for `compute_deltas.py` breadth columns. Deferred
until the map is proven stable to avoid a schema migration on bad data. Track as a separate
planning item if/when we need server-side breadth aggregation. Tag any future touchpoint with
`# TODO(HIR-SCHEMA): see PLAN_sector_industry_hierarchy.md § finviz_sector column` so it
surfaces to whoever is next in `compute_deltas.py` or `collect.py`.

---

## Sprint Board Updates

The following sprint entries need updating based on this plan:

| ID | Old description | Update needed |
|----|----------------|---------------|
| INS-7 | "Hardest feature. Needs static mapping." | ✅ Completed |
| TASK-6B | "Effort is mostly cataloguing." | ✅ Completed |
| (new) | Divergence Radar (feature D) | Add as new backlog item HIR-D |
| (new) | Market breadth gauge (feature R) | Add as new backlog item HIR-R |
| (new) | Since-last-look digest (feature I) | Add as new backlog item HIR-I |
| (new) | Rotation flow map (feature H) | Add as new backlog item HIR-H |
| (new) | Breadth-confirmed momentum col (feature E) | Add as new backlog item HIR-E |
| (new) | Staleness tripwire | Add as S-effort anytime item |

---

## Files Changed / Owned by This Plan

| File | Change | Phase |
|------|--------|-------|
| `data/finviz_sector_industry_map.json` | ✅ Exists | Foundation |
| `data/finviz_sector_industry_map.csv` | ✅ Exists | Foundation |
| `scripts/seed_taxonomy.py` | ✅ Exists | Foundation |
| `tests/test_seed_taxonomy.py` | ✅ Exists | Foundation |
| `dashboard/app.py` | Sector filter sidebar, breadth metric, divergence tab | Phase 1–3 |
| `docs/index.html` | ✅ Strength-tab breadth table live (`122a4d1`). Drill-down + Today-tab breadth bar built, unmerged (PR #178). Radar, digest, flow map still to build. | Phase 2–4 |
| `scripts/compute_deltas.py` | `momentum_breadth_confirmed` column (feature E) | Phase 5 |
| `scripts/generate_ai.py` | Sector context in briefing prompt (feature K) | Phase 4 |
| `scripts/collect.py` | Staleness tripwire (future) | Phase 5 |

---

## Appendix: Feature ID Reference

| ID | Name | Tier | Effort |
|----|------|------|--------|
| A | PWA drill-down navigation | Navigation | M |
| B | Breadth bar on sector cards (PWA) | Navigation | S |
| C | Leaders & Laggards mini-list | Navigation | S |
| D | Divergence alerts / Rotation Radar tab | Signal | M |
| E | Breadth-confirmed momentum column | Signal | S |
| F | Rank within sector | Navigation | S |
| G | Sector-relative coloring | Navigation | S |
| H | Rotation flow map | Retention | L |
| I | Since-last-look digest | Retention | M |
| J | Sector consistency trust score | Signal | S |
| K | AI brief with sector context | Retention | M |
| L | Hierarchy-aware watchlist alerts | Retention | M |
| M | Crowding / concentration warning | Signal | S |
| N | Historical analog (deferred) | — | L |
| O | Sector→Industry→Stocks bridge | Bridge | M |
| P | Rank tension indicator | Signal | S |
| Q | Quiet movers screen | Signal | M |
| R | Market-wide breadth gauge | Navigation | S |
| S | Coverage honesty in UI | Trust | S |
| T | Replay slider | Retention | L |
| U | Smart empty/early-data states | Trust | S |
| V | Shareable sector cards | Retention | S |

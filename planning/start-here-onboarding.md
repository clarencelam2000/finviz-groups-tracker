# Plan: "Start Here" intro / onboarding for the PWA

> **Status:** 📋 **Approved, not yet implemented.** This document is the complete plan of
> record. Implementation lands in follow-up PR(s) on branch `claude/focused-curie-1rbub7`.
> Sibling doc: `planning/whats-new-and-guide.md` (the hub this builds on).

---

## 1. Context — why we're building this

A non-technical first-time user (the VP's friend) opened the PWA and couldn't tell **what
it is, what it's for, or why tracking group strength matters**. The two existing in-app
help surfaces both assume the user *already* understands the product:

- **What's New** (`docs/releases.json` → hub) — release notes, for returning users.
- **Guide** (`GUIDE` constant in `docs/index.html` → hub) — a metric-by-metric glossary;
  it explains *terms*, not the *point* of the product.

There is no front door for a newcomer: no statement of motivation, no "why groups," no
orientation to the tabs.

This is, in effect, the onboarding work the original hub plan explicitly **deferred**
(`planning/whats-new-and-guide.md` §8: "a per-tab walkthrough" and "where the data comes
from"). We now build the motivation + orientation layer on top of that foundation.

**Intended outcome:** a short, friendly **"Start Here"** intro that (1) explains *why
groups matter* with a credible citation, (2) explains *what makes this different from
Finviz* (our proprietary derived layer), and (3) gives a one-line tour of the 6 tabs. It
shows **once automatically on first launch** as a swipeable full-screen carousel, and is
**re-openable anytime** as a third section in the existing hub.

### 1a. Decisions locked with the VP (this is settled scope)

| Question | Decision |
|----------|----------|
| **Format** | *Combine* a first-run full-screen **carousel** **and** a persistent **"Start Here" section in the hub**. Both render one shared content source. **No new bottom tab** (tab bar stays at 6 — adding a 7th crowds mobile, same reasoning as `whats-new-and-guide.md` §3). |
| **Scope** | Why groups matter → What's different from Finviz → 6-tab tour. (Excludes the deferred "where data comes from" + FAQ for now — see §6.) |
| **The stat** | Cite a **real, swing-trading-oriented figure** (below), not a vague claim. |

### 1b. The citation (verified during planning)

William O'Neil / Investor's Business Daily — the CANSLIM swing/growth methodology:

> "37% of a stock's price movement is directly tied to the performance of the industry
> group the stock is in. Another 12% is due to strength in its overall sector. Therefore,
> about half of a stock's move is due to the strength of its respective group."

Chosen because it is **swing-trading-relevant by origin** (O'Neil's *How to Make Money in
Stocks* / IBD), which is the user's framing. We cite it inline as: *"~half of a stock's
move comes from its industry group + sector (William O'Neil / IBD)."*

Sources:
- https://www.tradingwithrayner.com/23-trading-rules-by-william-j-oneil/ (Rule 23)
- https://www.williamoneil.com/proprietary-ratings-and-rankings/

> **Maintenance note:** the figure and its source live canonically in the new
> `knowledge/product-intro-copy.md` (see §4) so the in-app copy never drifts from the
> attribution.

---

## 2. Content — the 5 slides / sections

One canonical content array drives **both** the carousel and the hub section. Copy is
short, plain-English, mobile-first. Wording below is the design intent; final strings are
fixed in implementation and kept verbatim-synced with `knowledge/product-intro-copy.md`.

1. **Welcome.** "Finviz Tracker — see where the market's money is actually moving." One line
   on what the app is: it watches every sector & industry and surfaces the ones gaining
   strength.
2. **Why groups matter.** The O'Neil/IBD stat: *about half* of any stock's move comes from
   its **industry group + sector** (37% group + 12% sector), not the company itself. So the
   highest-leverage question isn't "is this stock good?" — it's "is its group strong?"
   Citation shown inline.
3. **What's different from Finviz.** Finviz (and most group trackers) show **today's
   snapshot** — who's winning *right now*. We keep the history and track **how the rankings
   change over time**, so you can spot capital **rotating into** a group *before* the
   headline numbers move. That derived layer — momentum, rotation, relative strength vs the
   S&P 500 — is the proprietary part you won't find on Finviz.
4. **Your 6 tabs (the tour).** One line each, each with an optional "Open →" deep-link:
   - **Today** — every group, sorted by strength.
   - **Movers** — biggest rank climbers/fallers (rotation in progress).
   - **Momentum** — broad strength across all timeframes + the Rotation (emerging vs fading) view.
   - **Strength** — proven, sustained leaders.
   - **AI** — a plain-English daily rotation briefing.
   - **Lookup** — type any ticker; see if its group is a tailwind or headwind.
5. **You're set.** "Tap the ⓘ icon anytime for the Guide (what every number means) or to
   replay this intro." A **"Get started →"** button closes the carousel.

> **UX inspiration:** the standard first-run carousel (Robinhood / Duolingo style) — 4–5
> swipeable slides, progress dots, a persistent **Skip**, Back/Next. Deliberately short;
> the per-metric depth already lives in the Guide.

---

## 3. Architecture — reuse the hub primitives, add one overlay

The hub system already provides most of what we need (`docs/index.html`): a slide-up
`#hub-overlay` / `#hub-sheet`, section-switcher buttons (`.hub-section-btn` →
`setHubSection()`), `openHub(section, anchorId)`, header ⓘ button, first-run localStorage
seeding, and `switchTab()` for deep-links. We **extend** it, not fork it.

### 3a. Files to modify

| File | Change |
|------|--------|
| `docs/index.html` | **(a)** `WELCOME` content constant near `GUIDE` (~line 337): array of `{id, title, body, tab?}` slides — single source for carousel + hub. **(b)** Third hub-section button `data-section="welcome"` ("Start Here") in the switcher (~line 242) + a `renderWelcome(mode)` branch in `setHubSection()`, including a "Replay intro" affordance. `mode` is `'carousel'` (full-screen horizontal scroll-snap) or `'hub'` (vertical prose sections matching `renderWhatsNew` layout) — same `WELCOME` array, two render paths in one function. **(c)** New `#intro-overlay` full-screen carousel primitive (sibling of `#hub-overlay`, ~line 234): horizontal scroll-snap slides + progress dots + Skip / Back / Next / Get-started, built from `renderWelcome('carousel')`. **(d)** `fvt_intro_seen_v1` localStorage key + `getIntroSeen` / `setIntroSeen`; on boot auto-open the carousel once when unset, then set it. **(e)** Per-slide "Open →" and the final "Get started" button each call `switchTab()` **and then immediately dismiss the carousel** (`setIntroSeen(); hideIntroOverlay()`). Dismissing on tab-link is a **two-way door** (tracked: SPRINT.md `ONBOARD-DL-UX`): user navigates away → carousel is gone; they re-open anytime via hub "Start Here". Add a one-line code comment at the dismiss call: `// ONBOARD-DL-UX: dismiss-on-deeplink; revisit if users want to browse back mid-tour`. |
| `docs/sw.js` | Bump `CACHE` to next version (currently `finviz-v18` → `v19`) so the new shell ships (release-bump rule). |
| `docs/releases.json` | Prepend a release entry (`tag:"feature"`, `title:"Start Here intro"`); bump top-level `current` to it. `tests/test_guide_releases.py` asserts `current === releases[0].version`. |
| `knowledge/product-intro-copy.md` | **New.** Canonical home for the intro narrative + the O'Neil citation + a "kept in sync with the `WELCOME` constant in `docs/index.html`" note — mirrors how `knowledge/moaty-metrics.md` anchors `GUIDE`. |
| `README.md`, `CLAUDE.md` | Document the `WELCOME` constant, the `fvt_intro_seen_v1` key, and first-run behavior (project rule: configurable/stateful items documented in code + README + CLAUDE.md). |
| `.session/SPRINT.md`, `.session/WORK_LOG.md` | Sprint task + milestone entry. |

### 3b. `localStorage` key versioning policy

`fvt_intro_seen_v1` is the key for this feature's lifetime. Bump to `v2` only if the
intro content changes substantially enough that existing users should see it again (e.g.,
a new tab is added and the tour needs updating). Minor copy edits do **not** warrant a
bump — they don't justify re-nagging users who already dismissed it. Record any key bump
as a `feat:` commit with an explicit rationale; do not bump silently.

### 3c. First-run conflict avoidance

On a brand-new install, `applyUnseenIndicator()` already **seeds** `fvt_seen_release_v1`
silently and shows **no** What's-New banner. So the only first-run surface is our intro
carousel — no double-popup. The carousel uses its own independent key
(`fvt_intro_seen_v1`); clearing one doesn't affect the other.

### 3d. Reuse, don't reinvent
- Slides/sections render via the same vanilla-JS string templating as `renderWhatsNew()` /
  `renderGuideSheet()`.
- Tab deep-links reuse `switchTab()` — the same mechanism What's New entries already use via
  their `tab` field.
- The carousel overlay mirrors the existing `#hub-overlay` show/hide pattern (`.hidden` +
  `requestAnimationFrame` transform) — no new animation system.
- Visual language matches the app: `bg-slate-900` shell, `bg-slate-800` cards, `rounded-xl`,
  `text-sky-400` accents, emerald/red for positive/negative (consistent with `perfColor()`).

---

## 4. Source-of-truth & anti-drift

`knowledge/product-intro-copy.md` is the canonical copy + citation; the `WELCOME` constant
in `docs/index.html` is kept **verbatim-synced** to it (same discipline as
`moaty-metrics.md` ↔ `GUIDE`). Two anti-drift tests enforce this:

1. **Tab ID test** — every `tab` field in a `WELCOME` slide must be one of the 6 real tab
   ids; a renamed or removed tab can't silently break the tour.
2. **Copy sync test** — the `body` strings in `WELCOME` match the corresponding lines in
   `knowledge/product-intro-copy.md` verbatim (mirrors `test_guide_one_liners_match_metrics_md`
   for the `GUIDE` constant). This is the enforcement mechanism for the "verbatim-synced"
   claim — without it, the sync is convention-only and will drift.

---

## 5. Verification (for the implementation PR)

**Automated (pytest + Playwright, local-server + route-intercept pattern from CLAUDE.md
"What Playwright in cloud unlocks"):**

Tests ship alongside their feature commit — not batched at the end:

- **With commit 1** (WELCOME constant + hub section): extend `tests/test_guide_releases.py`
  (or a sibling `tests/test_pwa_intro.py`):
  - `releases.current === releases[0].version` (existing assertion, stays green)
  - The new intro release entry parses and has required fields
  - Every `tab` in a `WELCOME` slide is one of the 6 real tab ids (tab ID anti-drift)
  - `WELCOME` slide `body` strings match `knowledge/product-intro-copy.md` verbatim
    (copy sync, mirrors `test_guide_one_liners_match_metrics_md`)

- **With commit 2** (carousel overlay + first-run logic): new `TestPWAIntro` Playwright
  class using the local-server + route-intercept fixture pattern:
  - `fvt_intro_seen_v1` unset → carousel auto-opens on load
  - Skip / Get-started dismisses it
  - Stays dismissed across reload (localStorage persists)
  - "Open →" on a slide calls `switchTab()` **and** dismisses the carousel
  - Hub "Start Here" section renders the same content
  - "Replay intro" re-opens the carousel

- `python3 -m pytest tests/ -q` green before each commit. The 3 pre-existing
  `TestPWALookbackWindows` failures are tracked as `PWATEST-LOOKBACK` in SPRINT.md and
  are unrelated to this feature — do not treat them as a gate for these commits.

**Manual smoke:** serve `docs/` locally, clear localStorage, reload → carousel appears;
swipe through; tap a tab link → lands on that tab; reopen via ⓘ → "Start Here".

---

## 6. Out of scope for this pass (deferred — with reasons)
- **"Where the data comes from"** (Finviz source, weekday-EOD cadence, no weekend/holiday
  rows). Still deferred — it tracks pipeline behavior and needs its own maintenance
  discipline (same reason as `whats-new-and-guide.md` §8).
- **FAQ** — kept out to keep the first content set small and high-confidence.
- **Forced replay on every update** — the intro is first-run-only + manually re-openable;
  no nag.

---

## 7. Implementation commit slicing (per `.claude/rules/branch-commit-discipline.md`)
1. `feat:` `WELCOME` constant + "Start Here" hub section + anti-drift / copy-sync tests.
   _(Tests ship with the feature they cover, not batched at end.)_
2. `feat:` first-run carousel overlay + `fvt_intro_seen_v1` auto-open/dismiss + `TestPWAIntro` Playwright coverage.
3. `docs:` / `chore:` `knowledge/product-intro-copy.md`, README + CLAUDE.md; release cut
   (`releases.json` entry + `current` + `sw.js` `CACHE` bump — all three together).
4. Session handoff: `session-notes.md` / `WORK_LOG.md` / `SPRINT.md`.

All on `claude/focused-curie-1rbub7`; PRs target `claude/elegant-babbage-hlxnfy`.

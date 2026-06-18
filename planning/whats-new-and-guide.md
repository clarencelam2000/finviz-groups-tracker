# Plan: "What's New" + "Guide / Glossary" for the PWA (and dashboard fast-follow)

> **Status:** Approved design plan, not yet implemented. This document is the blueprint for a
> future implementation session. No UI/UX code has been written. The content/data file
> (`docs/releases.json`) and the glossary copy are the source of truth everything else reads from.

## Context — why this is being added

Tools and dashboards almost universally have two things this project currently lacks:

1. **A "What's New" / release notes surface** — so users notice features land (movers,
   momentum, AI tab, ticker lookup were all shipped silently). Right now the only version
   signal is `sw.js`'s `CACHE = 'finviz-v9'` string and the dev-facing `.session/WORK_LOG.md`.
2. **A "Guide / What it means" glossary** — the app surfaces *proprietary* calculated metrics
   (momentum_score, momentum_confirmed, regime_short_long, momentum_accel, rank_trend_slope,
   rank deltas, sustained strength, all-green, rank floor) plus color/arrow/threshold glyphs
   that are meaningless without explanation. Authoritative copy already exists in
   `knowledge/moaty-metrics.md` (explicitly written to feed an in-app "why this matters"
   glossary) but is not surfaced in the product.

Intended outcome: a single content source feeding **one discoverable hub** in the PWA, with
contextual deep-links from each tab — and a lighter mirror in the Streamlit dashboard.

## Approved decisions

- **PWA surface = Variant A — "Hub + contextual deep-links."** An `ℹ️` icon in the header
  opens a slide-up sheet (the hub) with two segmented sections: **What's New** | **Guide**.
  The tab bar stays at 6 — no 7th tab. Each existing tab gets a tiny "why this matters" link
  that deep-links *into* the hub, scrolled to the relevant metric. What's New shows an
  unseen-update dot on the `ℹ️` icon + a one-time dismissible banner after a version bump.
- **Release-notes source of truth = curated `docs/releases.json`** (not derived from
  WORK_LOG). Hand-curated, user-facing tone, separate from dev notes.
- **Glossary scope = Option 1** — proprietary metrics (reusing `moaty-metrics.md` one-liners)
  + a short "how to read a card" walkthrough + a color/arrow/threshold legend. Option-3
  extras (data-provenance section, FAQ, per-tab walkthrough) are an explicit fast-follow, not
  in this pass.

## Architecture / data model

### 1. Release notes — `docs/releases.json` (new file; the source of truth)
Curated, newest-first array. The PWA fetches it (same-origin under `docs/`, so it works via
the service worker cache-first path — no `raw.githubusercontent` CSV path needed). Shape:

```jsonc
{
  "current": "2026.06.18",          // current version id; bump on each release
  "releases": [
    {
      "version": "2026.06.18",
      "date": "2026-06-18",
      "title": "Guide & What's New",
      "tag": "feature",             // feature | fix | data | improvement
      "tab": "momentum",            // OPTIONAL: deep-links the entry to a tab
      "notes": [
        "New ℹ️ Guide explains every metric and color.",
        "What's New now flags updates with a dot."
      ]
    }
  ]
}
```

- **Versioning convention:** `YYYY.MM.DD` (human-scannable, monotonic, no separate semver to
  maintain). Document this convention in `README.md` § Configurable parameters and `CLAUDE.md`.
- **"Unseen" tracking:** store last-seen `current` in `localStorage` under a new key
  `fvt_seen_release_v1` (mirrors existing `PREFS_KEY = 'fvt_prefs_v1'` convention in
  `docs/index.html`). Dot/banner shows when `releases.current !== storedSeen`.
- **Coupling note to document:** bumping a release = (a) prepend entry to `releases.json`,
  (b) set `current`, (c) bump `sw.js` `CACHE` so the new shell/JSON aren't served stale.
  Add this 3-step checklist to `CLAUDE.md` § Automation and `.claude/rules/`.

### 2. Glossary — content embedded in `docs/index.html`
Glossary copy is small and stable, and the PWA can't read `knowledge/*.md` at runtime. Define
a single JS data structure near the top constants (alongside `REGIME_THRESHOLD` etc., ~L244)
e.g. `const GUIDE = { metrics: [...], legend: [...], howto: [...] }`, each metric entry keyed
by an `id` (e.g. `momentum_score`) so tab links can deep-link via `#guide-momentum_score`.
Content is **copied from `knowledge/moaty-metrics.md`** ("User one-liner" text) — do not
re-author. `knowledge/moaty-metrics.md` remains the canonical written source; add a comment
in both places noting they must stay in sync (the in-code-comment rule from CLAUDE.md).

### 3. Hub sheet — reuse existing patterns, add a sheet primitive
- **Render:** vanilla JS string templating, matching `renderToday()` etc. New
  `renderGuideSheet()` / `openHub(section, anchorId)` functions.
- **Accordions:** reuse the existing `<details>`/`.glossary-chevron` pattern from
  `lookupGlossary()` (docs/index.html ~L1639) for each metric entry.
- **Sheet container:** add one fixed-position slide-up overlay (CSS transform/opacity, same
  approach as the toast/error overlay patterns) — there is no modal system today, so this is
  the one genuinely new UI primitive.
- **Header icon:** add `ℹ️` button to the header (the bar above `#tab-bar`, ~L58) with a dot
  badge element toggled by the unseen-release check.
- **Contextual links:** each tab's render function appends a small "why this matters →" link
  that calls `openHub('guide', '<metric-id>')`.

## Files to modify / create

| File | Change |
|------|--------|
| `docs/releases.json` | **New.** Curated release entries + `current` version. |
| `docs/index.html` | Header `ℹ️` button + dot; slide-up sheet markup; `GUIDE` content const; `renderGuideSheet`/`openHub`; localStorage seen-version logic; "why this matters" links in each `render*()`. |
| `docs/sw.js` | Bump `CACHE`; add `releases.json` to precache list (currently only `/` + `manifest.json`). |
| `knowledge/moaty-metrics.md` | Add a sync note pointing at the `GUIDE` const in index.html. |
| `README.md`, `CLAUDE.md`, `.claude/rules/` | Document version convention + the 3-step release-bump checklist. |
| `.session/WORK_LOG.md` / `SPRINT.md` | Add the "Guide + What's New" milestone / sprint tasks. |

### Dashboard (secondary / fast-follow — same source of truth)
`dashboard/app.py` (8 tabs today, no help section). Lighter mirror:
- Sidebar expander **"ℹ️ Guide & Glossary"** rendering the same metric definitions (read from
  the shared text source) — reuse `moaty-metrics.md` content.
- A **"What's New"** expander that reads `docs/releases.json` (local file path) and lists the
  latest entries.
- No deep-linking needed on desktop. This keeps PWA primary, dashboard a thin reflection.

## A+ refinements (folded in)

These are the high-leverage upgrades worth building from day one — each closes a drift or
UX gap cheaply:

1. **Legend renders live thresholds, not prose.** The color/arrow/threshold legend reads the
   actual constants (`REGIME_THRESHOLD`, `ACCEL_STRONG/SLIGHT`, `SLOPE_STRONG/SLIGHT`) from the
   JS scope and prints their current values. The glossary can never drift from behavior, and it
   auto-satisfies CLAUDE.md's "document configurable items everywhere" rule.

2. **What's New bullets can be actionable.** A release note entry may carry an optional
   `"tab"` field (e.g. `"momentum"`); tapping the entry closes the sheet and `switchTab()`s
   there. Announcement → the actual feature in one tap.

3. **First-visit seeding (no backlog nag).** On first run with no stored version, seed
   `fvt_seen_release_v1` to `releases.current` so brand-new users don't see a "new!" dot for the
   entire history — only genuine future updates flag. The dot clears on **open** (not forced
   dismiss); the post-bump banner is separately dismissible.

4. **Anti-drift doc test.** A test asserts: every metric id referenced by a tab's
   "why this matters" deep-link exists in `GUIDE` (no dead anchors), and every `GUIDE` metric
   has copy. Catches the classic "added a metric, forgot the glossary entry" gap.

5. **Release/cache coupling guard.** A test asserts `releases.json.current === releases[0].version`
   and (PR-level check) that `sw.js`'s `CACHE` was bumped whenever `releases.json` changed —
   guarding the stale-cache footgun structurally, not by memory.

6. **Searchable Guide + graceful degrade.** A small filter input in the hub's Guide section
   (mirrors existing search-filter UX). If `releases.json` fails to fetch (offline), the hub
   still opens to Guide and What's New shows a quiet "couldn't load updates" line — matching the
   app's existing silent-fail ethos (`showError`, SW `.catch(() => {})`).

## Out of scope (explicit fast-follows)
- Option-3 glossary extras: data-provenance section, FAQ, per-tab walkthrough.
- Auto-popup modal for What's New (Variant A uses dot + dismissible banner, not a forced modal).
- Auto-generating releases.json from WORK_LOG.

## Verification (when implemented)
- **PWA functional test** via Playwright using the local-server + route-intercept pattern in
  CLAUDE.md ("What Playwright in cloud unlocks"): serve `docs/`, intercept CSV fetches with
  fixtures, also serve `releases.json`. Assert: `ℹ️` opens the sheet; What's New lists entries;
  glossary accordions expand; a tab "why this matters" link opens the hub scrolled to the right
  anchor; dot disappears after open and persists across reload (localStorage).
- **Unseen-version logic:** unit-test the pure comparison (current vs stored) in isolation if
  extracted; otherwise cover via the Playwright reload assertion.
- **Dashboard:** run streamlit headless + Playwright, assert the Guide and What's New expanders
  render and the latest release title appears.
- **JSON validity:** a tiny test asserting `docs/releases.json` parses and `current` matches the
  newest `releases[0].version`.
- Run `python3 -m pytest tests/ -q` before commit.

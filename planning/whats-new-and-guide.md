# Plan: "What's New" + "Guide / Glossary" for the PWA (and dashboard)

> **Status:** ✅ **First pass implemented** (branch `claude/epic-sagan-njeu84`). The PWA hub,
> `releases.json`, glossary, legend, contextual links, unseen-dot/banner, dashboard mirror,
> docs, and tests are all in place. §8 items remain deferred as planned. See the completion
> checklist at the bottom of this file. Original design brief preserved below.

---

## 1. Context — why we're adding this

The product (a mobile PWA at `docs/index.html` + a Streamlit dashboard at `dashboard/app.py`)
shows sector/industry rankings and a layer of **proprietary calculated metrics** — momentum
score, regime, acceleration, rank-trend slope, rank deltas, and more. Two gaps:

1. **No release-notes / "What's New" surface.** Several features (Movers, Momentum, the AI tab,
   Ticker Lookup, the Rotation sub-view) shipped with zero in-app announcement. Users have no
   way to learn what changed. The only version signal today is the cache-busting string
   `CACHE = 'finviz-v9'` in `docs/sw.js` and the developer-facing `.session/WORK_LOG.md`.

2. **No in-app explanation of what the numbers mean.** The app shows metrics and visual cues
   (colored card edges, up/down arrows, glyphs, regime bars) that are meaningless without a
   key. Authoritative plain-English definitions already exist in `knowledge/moaty-metrics.md`
   (each metric has a written "User one-liner"), explicitly authored to feed an in-app
   glossary — but nothing surfaces them to users yet.

**Intended outcome:** one discoverable in-app **hub** that holds both "What's New" and a
"Guide" (glossary + how-to), fed by a single source of truth, with small contextual links from
each screen that jump into the relevant Guide entry. A lighter version of the same content
appears in the desktop dashboard.

---

## 2. The two features, in plain terms

### 2a. "What's New" (release notes)
A short, reverse-chronological list of user-facing changes ("New Momentum tab", "Faster
loading", etc.). When a new release exists that the user hasn't seen, the app shows a small
**unseen-update dot** on the hub icon and a one-time **dismissible banner**. This is the
pattern most apps use ("What's New in this version").

### 2b. "Guide" (glossary + how-to)
Plain-English definitions of every metric the app displays, a short "how to read a card"
walkthrough, and a **legend** explaining every color/arrow/bar cue. Content is lifted verbatim
from the "User one-liner" lines in `knowledge/moaty-metrics.md` — we do **not** re-write
definitions, to keep one canonical wording.

---

## 3. How users reach it (the chosen UX, fully described)

We evaluated three placements (a dedicated 7th tab; auto-popups + scattered inline help; and a
single hub with contextual links). **We chose the single-hub approach** because the PWA tab bar
already has 6 tabs (Today / Movers / Momentum / Strength / AI / Lookup) and is tight on mobile —
adding a 7th crowds it, and scattering content invites duplication. The chosen design:

- **One `ℹ️` icon in the header** (the bar directly above the tab bar, `#tab-bar` is around
  `docs/index.html:58`). Tapping it opens a **slide-up sheet** ("the hub") with two switchable
  sections: **What's New** and **Guide**.
- **The tab bar stays at 6 — no new tab.**
- **Contextual deep-links:** each existing screen gets a small "why this matters →" link that
  opens the hub directly at the relevant glossary entry (e.g. tapping it next to a momentum
  score opens the hub scrolled to the `momentum_score` definition). This gives contextual help
  *without* duplicating the copy onto every screen — there is exactly one copy, in the hub.
- **Unseen-update indicator:** a dot on the `ℹ️` icon when there's a release the user hasn't
  seen, plus a one-time dismissible banner after an update.

This keeps a single content source with many entry points, rather than copies scattered per
screen.

---

## 4. Architecture & data model

### 4a. Release notes live in a new file: `docs/releases.json`
Hand-curated (user-facing tone), newest-first. It lives under `docs/`, so the PWA fetches it
**same-origin** — it is served by the existing service worker like the rest of the app shell,
with no dependency on the `raw.githubusercontent.com` CSV path the data uses. Shape:

```jsonc
{
  "current": "2026.06.18",          // id of the newest release; drives the "unseen" dot
  "releases": [
    {
      "version": "2026.06.18",      // YYYY.MM.DD — human-scannable, monotonic, no semver to maintain
      "date": "2026-06-18",
      "title": "Guide & What's New",
      "tag": "feature",             // one of: feature | fix | data | improvement
      "tab": "momentum",            // OPTIONAL: if set, tapping the entry jumps to that tab
      "notes": [
        "New ℹ️ Guide explains every metric and color.",
        "What's New now flags updates with a dot."
      ]
    }
  ]
}
```

- **Version convention** `YYYY.MM.DD`: scannable and naturally ordered; avoids maintaining a
  separate semver scheme. Document this in `README.md` (Configurable parameters) and `CLAUDE.md`.
- **"Unseen" tracking:** store the last-seen `current` value in `localStorage` under a new key
  `fvt_seen_release_v1` (this mirrors the app's existing preferences key `PREFS_KEY =
  'fvt_prefs_v1'` in `docs/index.html`). Show the dot/banner whenever `releases.current` differs
  from the stored value.
- **Release-bump checklist (must be documented in `CLAUDE.md` § Automation and a rules file):**
  cutting a release = (a) prepend a new entry to `releases.json`, (b) update `current`, and
  (c) bump `CACHE` in `docs/sw.js` so the new shell + JSON aren't served from a stale cache.
  All three together, every time.

### 4b. Glossary content embedded in `docs/index.html`
The glossary copy is small and stable, and the PWA cannot read `knowledge/*.md` at runtime.
Define one JavaScript data structure near the existing top-of-script constants (alongside
`REGIME_THRESHOLD` etc., around `docs/index.html:243`):

```js
const GUIDE = {
  metrics: [ /* { id, label, oneLiner, detail } per metric, id e.g. "momentum_score" */ ],
  legend:  [ /* color / arrow / bar cues — see §5 */ ],
  howto:   [ /* short "how to read a card" steps */ ],
};
```

Each metric entry is keyed by an `id` (e.g. `momentum_score`) so the contextual links can target
it (e.g. anchor `#guide-momentum_score`). **Copy the text verbatim from the "User one-liner"
lines in `knowledge/moaty-metrics.md`** — do not re-author. Add a short comment in both
`knowledge/moaty-metrics.md` and next to `GUIDE` stating they must stay in sync (per the
in-code-comment rule in `CLAUDE.md`).

The metric set to include (all from `knowledge/moaty-metrics.md`):
`momentum_score`, `momentum_confirmed`, `regime_short_long`, `momentum_accel`,
`rank_trend_slope`, `rank_agreement`, `rank_*` and `rank_*_delta_Nd`, Sustained Strength,
All Green / Breadth, and Rank Floor.

### 4c. The hub itself — reuse what exists, add one new primitive
- **Rendering:** vanilla-JS string templating, matching the existing `renderToday()` /
  `renderMovers()` style. Add `renderGuideSheet()` and `openHub(section, anchorId)`.
- **Accordions:** reuse the existing native `<details>` + `.glossary-chevron` pattern from
  `lookupGlossary()` (around `docs/index.html:1639`) for each metric entry — this is already in
  the codebase and styled.
- **The sheet container is the only genuinely new UI primitive.** There is no modal/sheet system
  today; add one fixed-position slide-up overlay using CSS transform/opacity, following the same
  lightweight approach as the existing toast (`showToast`, ~`docs/index.html:483`) and error
  overlay (`showError`, ~`docs/index.html:744`) patterns.
- **Header icon:** add an `ℹ️` button to the header bar with a small dot badge element toggled by
  the unseen-release check.
- **Contextual links:** in each `render*()` function, append a small "why this matters →" link
  that calls `openHub('guide', '<metric-id>')`.

---

## 5. The color/arrow/bar legend (includes the colored card bar)

The Guide's **legend** section must explain every visual cue. These are not invented — they
already exist in `docs/index.html` and are currently unexplained. The legend should render the
**live threshold constants** (read them from JS scope, do not hard-code the numbers as prose) so
it can never drift from actual behavior, and so it auto-satisfies the CLAUDE.md "document
configurable items everywhere" rule. Cues to document:

- **Colored left bar on cards** *(this is the "colored bar" cue)*. On the **Today** tab the card's
  left edge is colored by the value of the currently-selected perf metric
  (`docs/index.html:801`): emerald > +2%, green (0, +2%], dark-red [−2%, 0], red < −2%, grey when
  no data. Note: dark-red is the mild-negative band (near zero), red is the sharp-negative band
  (< −2%). The distinction matters for the legend — dark-red and red are not interchangeable.
  On the **Rotation** sub-view the cards additionally use a horizontal **regime fill bar**
  (`regimeBar`, ~`docs/index.html:1004`) whose color/length encodes `regime_short_long`
  (emerald = emerging leader, red = fading). Explain both: what the colors mean and what value
  drives them.
- **Trend arrows** (↑ / ↓ next to a name): short-window `rank_ytd` delta direction.
- **Slope glyphs** (↑↑ / ↑ / ~ / ↓ / ↓↓): `rank_trend_slope`, gated by `SLOPE_STRONG = 0.05`
  and `SLOPE_SLIGHT = 0.01`.
- **Acceleration badges** (▲▲ / ▲ / ▼ / ▼▼): `momentum_accel`, gated by `ACCEL_STRONG = 0.08`
  and `ACCEL_SLIGHT = 0.02`.
- **Regime buckets** (Emerging / Established / Fading): `regime_short_long` vs
  `REGIME_THRESHOLD = 0.15`.

---

## 6. Files to create / modify

| File | Change |
|------|--------|
| `docs/releases.json` | **New.** Curated release entries + `current`. |
| `docs/index.html` | Header `ℹ️` button + unseen dot; slide-up hub sheet markup; `GUIDE` content constant; `renderGuideSheet` / `openHub`; localStorage seen-version logic (`fvt_seen_release_v1`); "why this matters →" links in each `render*()`. |
| `docs/sw.js` | Bump `CACHE`; add `releases.json` to the precache list (today it precaches only `/` + `manifest.json`). |
| `knowledge/moaty-metrics.md` | Already has User one-liners for all metrics in the Guide scope. Add a "kept in sync with the `GUIDE` constant in `docs/index.html`" note. |
| `README.md`, `CLAUDE.md`, `.claude/rules/` | Document the `YYYY.MM.DD` version convention and the 3-step release-bump checklist (releases.json entry + `current` + `sw.js` CACHE). |
| `.session/SPRINT.md`, `.session/WORK_LOG.md` | Add the sprint tasks / milestone entry. |
| `tests/` | New tests — see §8. |

### Dashboard (secondary, same source of truth) — `dashboard/app.py`
The Streamlit dashboard has 8 tabs and no help section today. Add a **lighter mirror**, not a
fork of the content:
- A sidebar expander **"ℹ️ Guide & Glossary"** rendering the same metric definitions (sourced
  from `knowledge/moaty-metrics.md`).
- A **"What's New"** expander that reads `docs/releases.json` (local file path) and lists recent
  entries.
- No deep-linking needed on desktop. The PWA is primary; the dashboard reflects it.

---

## 7. Refinements worth building from day one

1. **Legend reads live thresholds** (see §5) — no prose copy of numbers that can rot.
2. **Actionable What's New entries** — the optional `"tab"` field lets an entry deep-link to the
   feature it announces (closes the sheet, calls `switchTab()`).
3. **First-visit seeding (no backlog nag)** — on first run with no stored version, seed
   `fvt_seen_release_v1` to `releases.current` so brand-new users don't get a "new!" dot for the
   entire history. The dot clears on **open** (not a forced dismiss); the post-update banner is
   separately dismissible.
4. **Anti-drift doc test** — assert every metric id referenced by a "why this matters" link
   exists in `GUIDE`, and every `GUIDE` metric has copy. Catches "added a metric, forgot the
   glossary entry."
5. **Release/cache coupling guard** — a test asserting `releases.current === releases[0].version`,
   plus a PR-review reminder that `sw.js` `CACHE` must bump whenever `releases.json` changes.
6. **Searchable Guide + graceful offline degrade** — a small filter input in the Guide section
   (mirrors existing search-filter UX). If `releases.json` fails to load (offline), the hub still
   opens to the Guide, and What's New shows a quiet "couldn't load updates" line — consistent
   with the app's existing silent-fail style (`showError`, and `sw.js`'s `.catch(() => {})`).

---

## 8. Out of scope for the first pass (deferred — with reasons)

These are deliberately left for a follow-up so the first pass stays shippable:

- **A "Where the data comes from" section** — explaining the data source (Finviz), the
  weekday-only 3×/day update cadence, why there are no weekend/holiday rows, and what the
  "Updated 2h ago" freshness label means. Deferred because this content changes when pipeline
  behavior changes (e.g. cron/DST drift) and needs its own maintenance discipline.
- **An FAQ** — e.g. "why is rel_volume blank?", "why did a rank jump?", "momentum_score vs
  momentum_confirmed?". Deferred to keep the first content set small and high-confidence.
- **A per-tab walkthrough** — a short "what each of the 6 tabs is for" tour. Deferred; the
  per-metric glossary covers the highest-value confusion first.
- **A forced What's New popup on every update** — we intentionally use the quieter dot + one-time
  dismissible banner instead, to avoid nagging.
- **Auto-generating `releases.json` from `WORK_LOG.md`** — `WORK_LOG.md` is developer-oriented
  and noisy; release notes are curated by hand for user-facing tone.

---

## 9. Verification (when implemented)

- **PWA functional test** via Playwright, using the local-server + route-intercept pattern
  documented in `CLAUDE.md` ("What Playwright in cloud unlocks"): serve `docs/`, intercept the
  CSV fetches with fixtures, and serve a fixture `releases.json`. Assert: `ℹ️` opens the hub;
  What's New lists entries; tapping an entry with a `tab` field switches tabs; glossary
  accordions expand; a "why this matters →" link opens the hub scrolled to the right anchor; the
  unseen dot clears after opening and stays cleared across reload (localStorage persistence).
- **Unseen-version logic:** unit-test the pure current-vs-stored comparison if extracted;
  otherwise cover it via the Playwright reload assertion.
- **Glossary/anchor integrity:** the anti-drift test from §7.4.
- **`releases.json` validity:** a small test asserting it parses and `current` equals
  `releases[0].version`.
- **Dashboard:** run Streamlit headless + Playwright; assert the Guide and What's New expanders
  render and the newest release title appears.
- Run `python3 -m pytest tests/ -q` before every commit.

---

## 10. Completion checklist (first pass — implemented 2026-06-19)

- [x] `docs/releases.json` created (3 seed entries, `current` = newest).
- [x] `docs/sw.js`: `CACHE` bumped v9 → v10; `releases.json` added to precache.
- [x] `docs/index.html`: header ℹ️ button + unseen dot; one-time dismissible banner;
      slide-up hub sheet (What's New / Guide sections); `GUIDE` constant (11 metrics, verbatim
      one-liners + how-to); `renderWhatsNew`/`renderGuideSheet`/`openHub`/`closeHub`/`buildLegend`;
      `fvt_seen_release_v1` localStorage logic with first-visit seeding; searchable Guide;
      graceful offline degrade; live-threshold legend; "why this matters →" links on Today,
      Movers, Momentum, Strength; `tab` deep-link jumps.
- [x] `dashboard/app.py`: sidebar "ℹ️ Guide & Glossary" (parsed from moaty-metrics.md) +
      "🆕 What's New" (reads releases.json) expanders — no forked copy.
- [x] `knowledge/moaty-metrics.md`: sync note added.
- [x] `README.md`, `CLAUDE.md`, `.claude/rules/`: `YYYY.MM.DD` convention + 3-step release-bump
      checklist documented.
- [x] Tests: `tests/test_guide_releases.py` (anti-drift, releases validity, verbatim sync) +
      `TestPWAHub` Playwright class (hub opens, deep-link scroll, dot/banner show + clear + persist).

### Deferred (still §8): "Where the data comes from", FAQ, per-tab walkthrough, forced popup,
auto-generating releases.json from WORK_LOG.

### Known: 3 pre-existing `TestPWALookbackWindows` Playwright tests fail on the base branch
(LB-FF1 dynamic-button timing) — unrelated to this feature.

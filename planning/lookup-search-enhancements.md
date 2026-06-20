# Lookup Tab — Search Experience Enhancements

> **Status: All ideas complete. Sprints 1–2 (Ideas 1–4) on `claude/ecstatic-davinci-fbtqsp` (PR #131). Sprints 4–6 (Ideas 5–7) on `claude/adoring-noether-xavk0g`.**
> Supersedes the draft in PR #128 — that PR should be closed in favour of this one.
>
> Each idea below is self-contained: rationale, acceptance criteria, and a
> validation checklist a teammate can follow cold. Develop on a fresh branch off
> `claude/elegant-babbage-hlxnfy`; PR back into it. See
> `.claude/rules/branch-commit-discipline.md`.

---

## How this doc relates to `lookup-tab-improvements.md`

`planning/lookup-tab-improvements.md` is about the **result card** — surfacing
moaty derived metrics (rank floor, conviction, breadth, sparkline) *after* a
match resolves. **This doc is about two things:** (1) the search input itself —
what you type, how it resolves, how fast and offline-capable it feels; and (2)
making the result card so rich that you never need to leave the Lookup tab to
understand a group's full context. The two docs are complementary. Where there
is overlap (Ideas 6 and the old deep-link idea from that doc's deferred backlog),
this doc supersedes with fuller acceptance criteria. The old deep-link proposal
from that backlog is explicitly retired here — see Idea 3 (Aggregated Group View).

---

## Background — current state (verified against `docs/index.html`)

- The Lookup tab has **one input** (`#ticker-input`, L216) wired to `doLookup()`
  (L1831) → `lookupTicker()` (L1444) → `fetch(${WORKER_URL}/lookup?t=...)` (L1450).
  **Every resolution is a Cloudflare Worker round-trip.** (`WORKER_URL` at L255.)
- There is **no group (sector/industry) search at all** today. Typing "Semiconductors"
  hits the Worker, which expects a ticker, and fails.
- Meanwhile the PWA *already* downloads and caches the full sector + industry data on
  every load: `state.data.sectors` / `state.data.industries`, each with `.snap`
  (latest snapshot rows), `.delta` (latest delta rows), and `.deltaAll` (full
  history) — populated by `loadGroup()` (L671) inside `loadAndRender()`. That is
  ~11 sector names and ~150 industry names, each carrying live rank, momentum, and
  delta values, **sitting in memory unused by the Lookup tab.**

That asymmetry is the core opportunity: group search and typeahead need **no
network call**. The candidate set is already in memory.

---

## Implementation gotchas — read before writing any Ideas 1–4 code

### Gotcha 1 — `doLookup()` uppercases all input before anything else

`docs/index.html` L1833:
```js
const sym = (input.value || '').trim().toUpperCase();
```

Finviz group names in `state.data.*.snap` are sentence-case: `"Semiconductors"`,
`"Health Care"`, `"Aerospace & Defense"`. The existing `findGroupData()` (L1479)
uses an **exact string match**: `deltas.find(r => r.name === name)`.

**Consequence:** a user types "Semiconductors" → `sym` becomes "SEMICONDUCTORS" →
`findGroupData("SEMICONDUCTORS", ...)` returns null → falls silently through to the
Worker → 404 or wrong result. The group search feature appears to not work at all.

**The fix (use option a — lower blast radius):**

Option (a) — split the flow before the `.toUpperCase()` call:
```js
async function doLookup() {
  const input = document.getElementById('ticker-input');
  const raw = (input.value || '').trim();
  if (!raw) return;
  // Try local group match first (case-insensitive) on raw input
  const groupMatch = findGroupByName(raw);  // new helper, see Idea 1
  if (groupMatch) { /* render local group card */ return; }
  // Fall through to ticker path: uppercase for the Worker
  const sym = raw.toUpperCase();
  // ... existing lookupTicker(sym) flow
}
```

Option (b) — normalize all group names to uppercase at load time in `state.data`
— is not recommended: it requires touching every place that reads `r.name` for
display (renderLookup, group cards, etc.).

**Settle option (a) vs. (b) before writing any Idea 1 code.**

### Gotcha 2 — `findGroupData()` already exists; don't duplicate it

`findGroupData(name, groupKey)` at L1469 already resolves a group name to its
latest `snap` row, `delta` row, and the full `allSnaps` array (for rank context).
It is the building block for Ideas 1 and 3. Idea 1's resolve step is a thin
wrapper: find which group key ("sectors" or "industries") matches the input, then
call `findGroupData()`. Do not write a parallel resolver.

### Gotcha 3 — `state.data` is populated globally, but check before first paint

`loadAndRender()` (L1871) loads both CSVs before any tab renders, so
`state.data.sectors.snap` and `state.data.industries.snap` are populated by the
time a user can type. However, `doLookup()` runs on submit — if someone submits
before `loadAndRender()` completes (race on slow connections), `state.data.*.snap`
may be null. Any group-match logic must null-check: `(state.data[key]?.snap || [])`.

### Gotcha 4 — in-session offline works; cold-start offline does not

Once `loadAndRender()` has fetched the CSVs into memory, going offline mid-session
does not break group lookups — the data is already in `state.data`. The service
worker (`sw.js` L28) **intentionally does not cache CSVs** ("always fetch fresh —
stale data defeats the purpose"), so a cold start while offline will fail to
populate `state.data` and group search will have nothing to work with. This is an
accepted limitation. Do not add CSV caching to `sw.js` to work around it.

---

## Resolved product decisions (do not re-open without VP)

| Question | Decision |
|---|---|
| One unified bar vs. explicit mode toggle? | **Unified smart bar** (Idea 4). One input, auto-detects intent. |
| Ideas 1+2 ship together or separately? | **Together** — typeahead (Idea 2) is what makes local group search (Idea 1) discoverable. Shipping Idea 1 alone creates a silent feature. |
| Sparse data fields in result cards? | **Show `—`** (consistent with Today tab). Do not hide fields with null values. |
| Cold-start offline support? | **No** — accepted limitation. Correct AC wording only; no SW changes. |

---

## Ideas

Ideas are ordered by **recommended implementation sequence** (see Sequencing section).

---

### Idea 1 — Local-first group search

**What:** Let the user type a sector or industry name and resolve it entirely
client-side from `state.data.*.snap`, rendering the aggregated group card (see
Idea 3) with no network call. The Cloudflare Worker is called **only** for ticker
→ company/group mapping.

**Why it matters:** Removes a latency + rate-limit dependency for the most common
"is this group hot?" question. Works during the session even when offline. No
Cloudflare cost.

**Acceptance criteria**
- [ ] Typing a group name (e.g. "Semiconductors", "Technology", "Energy") and
      submitting renders that group's card with zero requests to `WORKER_URL`
      (verify in DevTools Network — no Worker calls).
- [ ] Match is **case-insensitive** on the raw input — do not rely on the
      uppercased `sym` variable (see Gotcha 1). The fix: resolve on raw input
      before the ticker path's `.toUpperCase()` call.
- [ ] Matches both sectors and industries from one input; if both a sector and an
      industry share a name (unlikely but possible), prefer the more specific match
      (industry) or surface both.
- [ ] If the input matches no group, it falls through to the existing Worker ticker
      path with no regression on ticker lookups.
- [ ] Works during the session after initial load, including while offline
      (data is in-memory — no SW CSV caching required).
- [ ] `state.data[key]?.snap` is null-checked before group resolution (Gotcha 3).

**Validation**
- Manual: serve `docs/` locally, DevTools → Network tab open. Type "Semiconductors"
  → submit. Confirm card renders, zero requests to `WORKER_URL`. Cross-check the
  rendered rank and momentum against `data/industries/deltas.csv` latest row for
  "Semiconductors".
- Type "AAPL" → still routes to Worker correctly (ticker regression check).
- Type a nonexistent name ("Foobar") → Worker call fires, returns expected error.

---

### Idea 2 — Autosuggest typeahead dropdown

**What:** As the user types, show a dropdown of substring matches from the
in-memory group list (sectors + industries), styled to the existing slate/sky
theme. Pure local filtering — no API calls during typing.

**Why it matters:** Discovery. Users don't know exact Finviz group names
("Aerospace & Defense", not "Aerospace"). Without typeahead, Idea 1 is a silent
feature only discoverable by reading the changelog.

**Acceptance criteria**
- [ ] Dropdown appears after ≥ 2 characters, listing case-insensitive substring
      matches from both sectors and industries.
- [ ] Matched substring highlighted in each suggestion (e.g. bold or colour).
- [ ] Results capped at 6, sorted: exact prefix matches first, then substring
      matches. Sectors and industries visually labelled (e.g. a type badge or
      grouped).
- [ ] Keyboard nav: ↑/↓ to move focus, Enter to select, Esc to dismiss, Tab to
      dismiss and move to submit.
- [ ] Tap or click on a suggestion → runs Idea 1 lookup for that group.
- [ ] Dropdown styling matches existing input (`bg-slate-800`, `border-slate-700`,
      `focus:border-sky-500`); touch targets ≥ 40 px (mobile).
- [ ] No dropdown on empty input; no layout shift on open/close.
- [ ] Zero network requests fire during typing (DevTools Network).

**Validation**
- Manual: type "semi" → dropdown includes "Semiconductors". Type "tech" → both
  "Technology" (sector) and relevant tech industries appear. Arrow-down + Enter
  selects the focused item and runs the lookup.
- Mobile: tap "se" on iOS/Android → dropdown appears, tapping a suggestion works.

---

### Idea 3 — Aggregated group view (full context in Lookup)

**What:** When a group is resolved — either from a group-name search (Ideas 1/2)
or from a ticker lookup that returns an industry + sector — expand the group
card(s) to show the **complete group analytics inline**, without navigating away
from the Lookup tab.

This is the headline deliverable: a user looking up a stock should get the full
group context — rank trajectory, rotation signal, momentum depth, delta table —
right on the card, not by hunting for the group in the Today or Momentum tabs.

**Replaces** the old "deep-link to other tabs" proposal from PR #128 and from
`lookup-tab-improvements.md`'s deferred backlog. Deep-linking breaks session
context and forces the user to find their one group in a list of 150. Aggregating
in-place is strictly better and equally cheap (all data is already in `state.data`).

**Data to surface** (all sourced from `state.data[groupKey].delta` + `.snap` for
the resolved group — zero new network calls):

| Section | Fields |
|---|---|
| Rank table | `rank_day`, `rank_week`, `rank_month`, `rank_quarter`, `rank_half`, `rank_year`, `rank_ytd` |
| Performance % | `perf_day`, `perf_week`, `perf_month`, `perf_quarter`, `perf_half`, `perf_year`, `perf_ytd` |
| Rank delta table | `rank_ytd_delta_5d`, `rank_ytd_delta_10d`, `rank_ytd_delta_20d`, `rank_ytd_delta_50d` |
| Momentum deep dive | `momentum_score`, `momentum_confirmed`, `momentum_accel`, `regime_short_long`, `rank_trend_slope` |
| Already on card (keep) | Sparkline, conviction chip, rank floor (from `lookup-tab-improvements.md` Phase 1) |

**Sparse data convention (decided):** Show `—` for any field where the value is
null or NaN — the same treatment as the Today tab. Do not hide sparse rows. This
is intentional: users should know data is expected but not yet accumulated, not
wonder why a field is absent.

**Layout note:** The ticker path returns **both** an industry and a sector from
the Worker, so two group blocks render. Each gets its own expanded card, stacked.
The group-name search path (Ideas 1/2) resolves one group → one card. Both cases
use the same card component.

**Acceptance criteria**
- [ ] For a **ticker lookup**: both the industry and sector cards expand to show
      the full metric table.
- [ ] For a **group-name lookup** (via Ideas 1/2): a single expanded card shows
      the full metrics.
- [ ] Sparse fields render as `—`, not hidden and not blank.
- [ ] On mobile, the rank/delta table is readable (2-column grid or similar;
      avoid horizontal scroll within the card).
- [ ] **Zero new network requests** — all data from `state.data` (already loaded
      by `loadAndRender()`).
- [ ] `findGroupData(name, groupKey)` (L1469) is reused for the data fetch step —
      do not write a parallel resolver.

**Validation**
- Manual: look up `AAPL` → industry card expanded → `rank_week` and
  `momentum_score` match the corresponding row in
  `data/industries/deltas.csv` for the latest date.
- Look up "Semiconductors" (via Idea 1) → same cross-check against
  `data/industries/deltas.csv`.
- Set DevTools throttling to slow 3G → data still renders (from in-memory state).
- Force a field to NaN in a test fixture (or find a group with <50 sessions of
  history) → `rank_ytd_delta_50d` shows `—`.

---

### Idea 4 — Unified smart search bar (intent detection)

**What:** The single input auto-detects whether the user means a group or a
ticker and routes accordingly — no mode toggle, no explicit switching. This is the
capstone that unifies the group search path (Ideas 1/2) with the existing ticker
path.

**Intent detection rule (keep it binary):**
1. Check input against the in-memory group name list (case-insensitive substring
   match) **before** uppercasing for the ticker path.
2. If it matches a known group → local resolution (Ideas 1/2).
3. If no group match → uppercase → Worker ticker path (existing flow).

Ambiguous input (substring matches a group AND looks like a ticker) should
**surface the typeahead dropdown** (Idea 2) so the user disambiguates by
selection — never a silent auto-guess.

**Acceptance criteria**
- [ ] Known group name resolves locally regardless of case (`energy`, `ENERGY`,
      `Energy` all work).
- [ ] A plausible ticker that is not a group name routes to the Worker (`AAPL`,
      `XLE`, `MSFT`).
- [ ] Ambiguous input (matches a group substring) shows typeahead suggestions
      before firing the Worker — the user selects.
- [ ] Placeholder copy updated to reflect dual capability (e.g.
      "Search ticker or group…").
- [ ] All existing ticker lookup tests still pass (regression).

**Validation**
- Manual matrix to document in the PR:

  | Input | Expected path | Expected result |
  |---|---|---|
  | `AAPL` | Worker | Apple Inc card |
  | `Semiconductors` | Local | Group card, no Worker call |
  | `energy` | Local | Energy sector card |
  | `XLE` | Worker | ETF card |
  | `semi` | Typeahead | Dropdown with "Semiconductors" |

---

### Idea 5 — Recent searches + pinned favorites

**What:** Persist the last N lookups and let users pin groups or tickers, stored
in `localStorage`. Surfaces as chips below the search bar when the input is empty.

**Why it matters:** Turns the Lookup tab into a lightweight watchlist with zero
backend. The user's three most-watched groups are one tap away.

**`localStorage` key convention** (document in-code per CLAUDE.md "configurable
items" rule):
- Recents: `fvg_lookup_recent` — JSON array of `{ type, name/symbol }`, newest first, max 8
- Pinned: `fvg_lookup_pinned` — JSON array, no cap

**Acceptance criteria**
- [ ] Last 8 successful lookups persist across reloads (`fvg_lookup_recent`).
- [ ] User can pin/unpin from a result card; pinned items render first and survive
      the recents cap (FIFO eviction, pinned items exempt).
- [ ] Tapping a chip re-runs that lookup.
- [ ] Chips only visible when the input is empty; disappear when the user starts
      typing or after a lookup runs.
- [ ] `localStorage` errors (private browsing, storage full) are caught silently —
      the feature degrades gracefully, not fatally.

**Validation**
- Manual: look up 3 tickers + 1 group → reload → 4 chips appear. Pin one. Look
  up 7 more items → the 9th evicts an unpinned recent, pinned one stays.
- Open in private/incognito → no chips, no error thrown.

---

### Idea 6 — Fuzzy / "did you mean" matching

**What:** Tolerate typos and colloquial names (`semis` → `Semiconductors`,
`pharma` → relevant industry) via lightweight local fuzzy matching. No external
library needed for 161 strings — Levenshtein distance with a small synonym map
covers the cases.

**Synonym map location:** An exported `const GROUP_SYNONYMS` object at the top of
the `<script>` block in `docs/index.html`, documented there per CLAUDE.md
"configurable items" rule (in-code comment + README § Configurable parameters +
CLAUDE.md). Example:
```js
// Colloquial aliases for Finviz group names. Add entries here when a common
// user alias is found not to resolve. Pairs: alias (lowercase) → exact Finviz name.
const GROUP_SYNONYMS = {
  'semis': 'Semiconductors',
  'pharma': 'Drug Manufacturers—General',
  'banks': 'Banks—Diversified',
  // ...
};
```

**Acceptance criteria**
- [ ] Near-miss with a clear best match shows a "Did you mean **X**?" affordance
      (one tap / Enter to accept). Not an auto-redirect — user confirms.
- [ ] Entries in `GROUP_SYNONYMS` resolve directly (no fuzzy needed for those).
- [ ] Fuzzy matching applies only when no exact/synonym match is found first.
- [ ] No false-positive fuzzy suggestions for clear tickers (`AAPL` should not
      suggest a group).

**Validation**
- Manual: type `semis` → "Did you mean Semiconductors?". Type `semiconductrs`
  (typo) → same suggestion. Type `pharma` → correct industry suggested.
- Document the full test input list + expected suggestions in the PR.

---

### Idea 7 — Empty-state suggestion chips

> Previously seeded in `lookup-tab-improvements.md` "Deferred — backlog"; full
> criteria added here.

**What:** When the Lookup tab opens with no prior input, show 4–6 tappable chips
derived from today's data: top momentum groups or biggest rank movers. The tab
is useful on open, not a blank box.

**Acceptance criteria**
- [ ] On an empty Lookup tab (input cleared or first open), show 4–6 chips
      derived from the latest `state.data.*.delta` rows (e.g. top
      `momentum_score` or largest `rank_ytd_delta_5d`).
- [ ] Chips computed locally — no network call.
- [ ] Chips disappear once the user starts typing (input non-empty) and after any
      lookup runs.
- [ ] Tapping a chip runs the lookup for that group (routes through Idea 1/2/3).

**Validation**
- Manual: open Lookup cold → chips render. Cross-check chip names against
  `data/*/deltas.csv` latest date rows — they should reflect the actual top
  momentum groups for that day.

---

## Recommended sequencing

| Sprint | Ideas | What ships | Why this order |
|---|---|---|---|
| 1 | 1 + 2 together | Local group search + typeahead | Idea 1 is a silent feature without Idea 2's discoverability. Same `doLookup()` refactor required for both. Ship together. |
| 2 | 3 | Aggregated group view | Highest per-effort value after search exists. Makes the result card the answer, not a navigation prompt. No new data fetch. |
| 3 | 4 | Unified smart bar | Capstone of the search arc. Only possible after Ideas 1/2 exist to route to. |
| 4 | 5 | Recents + pinned | Fast-follow polish. Builds on Ideas 1–4 being stable. |
| 5 | 6 | Fuzzy / "did you mean" | Worth doing once the synonym set is informed by real usage. |
| 6 | 7 | Empty-state chips | Lowest urgency; nice finishing touch. |

**PR size expectation:** Sprint 1 (Ideas 1+2) is the largest single PR — roughly
150–200 lines of `index.html` change covering `doLookup()` refactor, group
resolver, and dropdown component. Sprint 2 (Idea 3) is the richest card expansion
but mostly additive (~100–150 lines). Sprints 3–6 are smaller and independent.

---

## Critical files (for whoever implements)

- `docs/index.html` — all Lookup markup and logic:
  - Input: `#ticker-input` (~L216)
  - Submit handler: `doLookup()` (~L1831) — **must be refactored for Gotcha 1**
  - Ticker fetch: `lookupTicker()` (~L1444)
  - Group data resolver: **`findGroupData(name, groupKey)` (~L1469)** — reuse this;
    do not write a parallel resolver
  - Render: `renderLookup()` (~L1774)
  - Worker URL constant: `WORKER_URL` (~L255)
  - Group data loader: `loadGroup()` (~L671)
  - In-memory state shape: `state.data.*` (~L267) — `.snap`, `.delta`, `.deltaAll`
- `docs/sw.js` — bump `CACHE` on every shell change; CSVs are intentionally NOT
  cached here (see Gotcha 4 — do not change this).
- `data/sectors/deltas.csv`, `data/industries/deltas.csv` — ground truth to
  cross-check rendered ranks and momentum values in manual validation.
- Any user-facing change = "What's New" trifecta: `docs/releases.json` entry +
  `current` bump + `docs/sw.js` `CACHE` bump (see CLAUDE.md § Automation).

---

## Validation checklist (applies to any idea shipped from this doc)

- [ ] HTML/PWA-only change → no pytest required; state so in the commit message
      per `.claude/rules/branch-commit-discipline.md`. If a Playwright PWA
      functional test fits the change (see CLAUDE.md "PWA functional testing"),
      add one.
- [ ] Manual validation steps from the idea's "Validation" section are recorded
      in the PR description (inputs tested, expected vs. actual).
- [ ] Zero new network requests fire for group-path changes (DevTools Network).
- [ ] "What's New" trifecta updated for any user-visible change.
- [ ] `.session/SPRINT.md` updated; `.session/session-notes.md` updated on
      milestones.

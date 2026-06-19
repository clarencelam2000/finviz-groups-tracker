# Lookup Tab — Search Experience Enhancements (Brainstorm for VP)

> **Status: brainstorm / RFC. Nothing here is implemented yet.** This is a
> standalone idea slate from a VP callout. Any teammate can pick up an
> individual idea below without prior chat context — each one carries its own
> rationale, acceptance criteria, and validation steps.
>
> Develop on a fresh branch off `claude/elegant-babbage-hlxnfy`; PR back into it.
> See `.claude/rules/branch-commit-discipline.md`.

## Scope note — how this differs from `lookup-tab-improvements.md`

`planning/lookup-tab-improvements.md` is about the **result card** — surfacing
moaty derived metrics (rank floor, conviction, breadth) *after* a match. **This
doc is about the search input itself** — what you type, how it resolves, and how
fast/offline it feels. The two are complementary and don't overlap in code paths
except where noted (ideas 6 and 7 here are already seeded in that doc's
"Deferred — backlog" list; this doc gives them acceptance criteria).

## Background — current state (verified in `docs/index.html`)

- The Lookup tab is **ticker-only**. A single input (`#ticker-input`, `index.html`
  L216) feeds `doLookup()` (L1831), which calls `lookupTicker()` (L1444) →
  `fetch(`${WORKER_URL}/lookup?t=...`)` (L1450). **Every search is a Cloudflare
  Worker round-trip** (`WORKER_URL`, L255).
- There is **no group (sector/industry) search at all** today.
- Meanwhile the PWA *already* downloads and caches the full sector + industry
  data client-side for the other tabs: `state.data.sectors` /
  `state.data.industries`, each holding `.snap` (latest snapshot rows, every row
  has a `name`), `.delta` (latest deltas), and `.deltaAll` (full history) —
  populated by `loadGroup()` (L671). That's ~11 sector names and ~150 industry
  names, each already carrying live rank/momentum, **sitting in memory unused by
  Lookup.**

That asymmetry is the opportunity: a group search needs **no network call**, and
a typeahead needs **no debounced API** — the candidate set is already local.

> **Implementation gotcha for whoever picks this up:** the Lookup tab does not
> currently guarantee both group CSVs are loaded. Any local-search idea below
> must first ensure `loadGroup('sectors')` and `loadGroup('industries')` have
> run (await both, show the existing skeleton while pending). Don't assume
> `state.data.*.snap` is non-null just because another tab populated it.

---

## Idea 1 — Local-first group search (no CF call)

**What:** Let the user type a sector or industry name and resolve it **entirely
client-side** from `state.data.*.snap`, rendering the same rank/momentum group
card the result view already builds. The Cloudflare Worker call stays **only**
for ticker → group mapping (which genuinely needs FMP); group-name lookups never
touch the network.

**Why it matters:** Removes a latency + rate-limit + offline liability for the
most common "is this group hot?" question. Instant results. Works offline once
the CSVs are cached by the service worker.

**Acceptance criteria**
- [ ] Typing an exact group name (e.g. `Semiconductors`, `Technology`) and
      submitting renders that group's card with no network request to
      `WORKER_URL` (verify in DevTools Network tab — zero Worker calls).
- [ ] Match is case-insensitive and tolerant of surrounding whitespace.
- [ ] Works for both sectors and industries from one input.
- [ ] If the typed text matches no group AND looks like a ticker, it still falls
      through to the existing Worker ticker path (no regression).
- [ ] Works with the device offline after first load (CSVs served from SW cache).

**End goal / validation**
- Manual: serve `docs/`, go offline (DevTools → Network → Offline), look up
  `Semiconductors` → card renders from cache, Network shows no Worker request.
- Cross-check the rendered rank/momentum against the matching row in
  `data/industries/deltas.csv` for the latest date.

---

## Idea 2 — Autosuggest / typeahead dropdown

**What:** As the user types, show a clean dropdown of substring matches from the
in-memory group list (and optionally recent tickers), styled to the existing
slate/sky theme. Pure local filtering — no API calls.

**Why it matters:** Discovery (users don't know exact Finviz group names) and
speed. Matches the "classic streamlined clean search bar" the VP described.

**Acceptance criteria**
- [ ] Dropdown appears after ≥2 chars, listing substring matches (case-insensitive).
- [ ] Matched substring is visually highlighted in each suggestion.
- [ ] Results capped (~6) and sorted sensibly (exact prefix matches first).
- [ ] Keyboard nav: ↑/↓ to move, Enter to select, Esc to dismiss.
- [ ] Tap/click a suggestion → runs the lookup for that group.
- [ ] Dropdown styling matches existing inputs (`bg-slate-800`, `border-slate-700`,
      `focus:border-sky-500`) and is fully usable on mobile (touch targets ≥40px).
- [ ] No layout shift / no dropdown flash on empty input.

**End goal / validation**
- Manual: type `semi` → suggestions include `Semiconductors`; arrow-down +
  Enter selects it. Type `tech` → both `Technology` (sector) and tech industries
  appear, grouped or labeled by type.
- Confirm zero network requests fire during typing (DevTools Network).

---

## Idea 3 — Unified smart search bar (intent detection)

**What:** One input that auto-detects intent: input that looks like a ticker
(short, all-caps, matches no known group) → Worker lookup; otherwise → local
group filter (ideas 1 + 2). Removes the "what do I type here?" ambiguity.

**Why it matters:** Single mental model. The user just types; the app figures out
whether they meant a stock or a group.

**Acceptance criteria**
- [ ] A known group name resolves locally even if uppercased (e.g. `ENERGY`).
- [ ] A plausible ticker that is not a group name routes to the Worker.
- [ ] Ambiguous input (matches both a ticker pattern and a group substring)
      prefers showing typeahead suggestions over firing the Worker, so the user
      disambiguates by selection — never a silent wrong guess.
- [ ] Placeholder/help copy updated to reflect dual capability.

**End goal / validation**
- Manual matrix: `AAPL` → ticker card; `Semiconductors` → group card; `XLE`
  (ETF/ticker) → ticker path; `energy` → group suggestions. Document expected vs.
  actual for each in the PR.

---

## Idea 4 — Recent searches + pinned favorites

**What:** Persist the last N lookups and let users pin groups/tickers, stored in
`localStorage`. Surfaces as chips below the search bar.

**Why it matters:** Turns the tab into a lightweight watchlist with zero backend.

**Acceptance criteria**
- [ ] Last ~8 successful lookups persist across reloads (`localStorage`).
- [ ] User can pin/unpin an item; pinned items render separately and survive
      eviction from the recents list.
- [ ] Tapping a chip re-runs that lookup.
- [ ] Clearing/over-cap behavior is defined (FIFO eviction, pinned exempt).

**End goal / validation**
- Manual: look up 3 tickers + 1 group, reload → chips persist; pin one, exceed
  the recents cap → pinned one stays. Inspect `localStorage` key.

---

## Idea 5 — Fuzzy / "did you mean" matching

**What:** Tolerate typos and partial/colloquial names (e.g. `semis` →
`Semiconductors`, `pharma` → relevant industry) via a lightweight local fuzzy
match.

**Why it matters:** Finviz group names are not what users naturally type. Fuzzy
matching keeps everything resolvable locally instead of dead-ending.

**Acceptance criteria**
- [ ] A near-miss with a clear best match shows a "Did you mean **X**?"
      affordance (one tap to accept).
- [ ] Common abbreviations resolve (maintain a small synonym map, documented
      in-code per CLAUDE.md "configurable items" rule).
- [ ] No false-confident auto-redirect — fuzzy matches are *suggested*, the user
      confirms.

**End goal / validation**
- Manual: `semis`, `semiconductrs` (typo), `pharma` each surface the right
  suggestion. List the test inputs + expected matches in the PR.

---

## Idea 6 — Empty-state suggestion chips

> Already in `lookup-tab-improvements.md` "Deferred — backlog"; criteria added here.

**What:** Before any input, show tappable chips for today's top-momentum or
biggest-mover groups (and/or example tickers), so the tab is useful on open.

**Why it matters:** No more blank box. Immediate value + teaches users what the
tab does.

**Acceptance criteria**
- [ ] On an empty Lookup tab, show 4–6 chips derived from the latest local data
      (e.g. top `momentum_score` groups or biggest `rank_*_delta` movers).
- [ ] Chips disappear once the user starts typing / after a lookup runs.
- [ ] Tapping a chip runs that lookup.
- [ ] Chips are computed locally — no extra network call.

**End goal / validation**
- Manual: open Lookup cold → chips reflect the actual top-momentum rows in
  `data/*/deltas.csv` for the latest date. Cross-check the names.

---

## Idea 7 — Deep-link from a result into the group's tab

> Already in `lookup-tab-improvements.md` "Deferred — backlog"; criteria added here.

**What:** Make the resolved sector/industry in a result tappable, jumping to that
group inside the Today/Momentum tab (internal deeplink). Chains naturally with
ideas 1–3.

**Why it matters:** Connects "this stock's group" to the full group analytics the
app already has, instead of the Lookup card being a dead end.

**Acceptance criteria**
- [ ] The group name in a Lookup result is an affordance (visibly tappable).
- [ ] Tapping switches to the relevant tab, selects sectors/industries
      correctly, and scrolls/filters to that group.
- [ ] Back navigation returns to the Lookup result (or behaves predictably —
      define and document the chosen behavior).

**End goal / validation**
- Manual: look up `AAPL` → tap its industry → lands on that industry in
  Today/Momentum. Verify the right group toggle (sectors vs industries) is set.

---

## Recommended sequencing (for the VP to react to)

Ideas **1 → 2 → 3** form one coherent arc and are the headline: a local group
index (1) is the foundation that removes the CF dependency the VP flagged;
typeahead (2) and unified intent detection (3) build on it. Ideas **4–7** are
fast-follow polish. The strongest pitch: **most of this is nearly free** because
the data is already client-side — low-risk, offline-friendly, and it removes a
latency/rate-limit liability rather than adding one.

## Open questions for the VP

1. Should group search and ticker search share **one** bar (idea 3) or be two
   explicit modes (toggle/segmented control)? One bar is sleeker; two modes are
   more predictable.
2. For typeahead, include **recent tickers** alongside group suggestions, or keep
   the dropdown groups-only to stay simple?
3. Is offline group lookup a stated goal worth testing for, or a nice-to-have?

## Critical files (for whoever implements)

- `docs/index.html` — all Lookup markup + logic: input `#ticker-input` (~L216),
  `doLookup()` (~L1831), `lookupTicker()` (~L1444), `renderLookup()` (~L1774),
  `WORKER_URL` (~L255), `loadGroup()` (~L671), `state.data.*` shape (~L267).
- `docs/sw.js` — bump `CACHE` when shipping shell changes; confirm CSVs are in
  the cached set for offline lookup (idea 1).
- `data/sectors/deltas.csv`, `data/industries/deltas.csv` — ground truth to
  cross-check rendered ranks/momentum.
- Any user-facing change = a "What's New" release entry (`docs/releases.json` +
  `current` + SW cache bump) per CLAUDE.md § Automation.

## Validation checklist (applies to any idea shipped from this doc)

- [ ] HTML/PWA-only change → no pytest required; state so in the commit message
      (per `.claude/rules/branch-commit-discipline.md`). If a Playwright PWA
      functional test fits (see CLAUDE.md "PWA functional testing"), add one.
- [ ] Manual verification steps from the idea's "End goal / validation" recorded
      in the PR description.
- [ ] "What's New" trifecta updated (releases.json entry + `current` + `sw.js`
      `CACHE` bump).
- [ ] `.session/SPRINT.md` updated; `session-notes.md` on milestones.

# Plan: Card Tap → Lookup Deep-Link — Full Rollout

**Status:** Ready to implement  
**Scope:** `docs/index.html`, `docs/releases.json`, `docs/sw.js`, `tests/test_functional_playwright.py`  
**Estimated diff:** ~65 lines JS/HTML in `index.html` + 8 Playwright test functions  
**Prereq:** None — all referenced functions and IDs are live on default branch

---

## Context

PR156 ("feat: movers — tap card to open Lookup for that group", commit `7a3c63b`) introduced
a tap-to-Lookup deep-link on Movers tab cards. The pattern proved out cleanly:

- Each card stores its group name in a `data-mover-name` attribute
- A single delegated `click` listener on the container calls `switchTab('lookup')` then
  `doGroupLookup(name, state.group)`
- CSS affordances (`cursor-pointer active:opacity-75 select-none` + a muted `›` chevron)
  signal tappability without being visually heavy

Currently **6 additional card types** across Momentum, Strength, and vs Market tabs display
group names but dead-end — no drill-down path. The Lookup tab is the richest data surface in
the app (RS spreads, rank sparkline, breadth strip, full tables, conviction chip). This plan
rolls the same pattern out everywhere it applies.

---

## Reference Implementation (PR156 — copy this pattern)

**HTML card root** (in `renderMovers`, line ~1322):
```html
<div class="rounded-xl p-3 bg-slate-800 border border-slate-700 border-l-4 ${border}
            flex items-center gap-3 cursor-pointer active:opacity-75 select-none"
     data-mover-name="${escapeHtml(row.name)}">
  <!-- card content -->
  <div class="text-xs text-slate-500">vs ${win} ago <span class="text-slate-600">›</span></div>
</div>
```

**Delegated click listener** (line ~3348):
```javascript
document.getElementById('movers-content').addEventListener('click', e => {
  const card = e.target.closest('[data-mover-name]');
  if (!card) return;
  const name = card.dataset.moverName;
  if (!name) return;
  switchTab('lookup');
  document.documentElement.scrollTop = 0;
  document.body.scrollTop = 0; // iOS Safari
  doGroupLookup(name, state.group);
});
```

Key points:
- `switchTab('lookup')` must come BEFORE `doGroupLookup` — switchTab triggers `render()`
  which would wipe lookup state if called after
- `state.group` is `'sectors'` or `'industries'` (set by the group toggle, initialized at
  line ~340) — pass it unchanged
- `doGroupLookup(name, groupKey)` is defined at line 2263; it bypasses the ticker search
  path and goes directly to the group name lookup, so "&" in names like "Oil & Gas" passes
  through correctly — no escaping needed at call time

---

## Card Inventory

### Tabs to implement (7 card types, 4 containers)

| Tab | Card type / View | Rendering function | Container ID | Tappable today? |
|-----|-----------------|-------------------|-------------|-----------------|
| Momentum | Momentum Cards | `renderMomentumCards()` line 1363 | `#momentum-list` line 165 | NO |
| Momentum | Rotation Cards | `renderRotation()` line 1409 | `#momentum-list` | NO |
| Strength | Sustained/Weak Cards | `renderStrength()` — `renderList` closure ~line 1547 | `#strength-list` line 189 | NO |
| Strength | All Green Cards | `renderStrength()` — `.map()` branch ~line 1599 | `#strength-list` | NO |
| vs Market | RS Score Cards | `renderRsScore()` line 1657 | `#vsmarket-list` line 205 | NO |
| vs Market | RS Regime Cards | `renderRsRegime()` — inner `renderCard` fn ~line 1730 | `#vsmarket-list` | NO |
| **Today** | Today Group Cards | `renderToday()` line 1142 | `#today-cards` line 116 | YES (expand/collapse) — special case |

### Tabs to skip

| Tab | Reason |
|-----|--------|
| Movers | Done in PR156 |
| AI | No per-group cards; all briefing text |
| Lookup | Cards are already inside Lookup; chips/suggestions already trigger lookup |

---

## Implementation

All changes are in `docs/index.html`. Add listeners near the existing Movers listener at
line ~3348.

### Part A — Momentum, Strength, vs Market (full-card tap)

For each of the 6 non-Today card types:

1. **Add to card root `<div>`** in the rendering function:
   ```
   data-group-name="${escapeHtml(row.name)}"
   cursor-pointer active:opacity-75 select-none
   ```
2. **Add chevron** somewhere in the card body (e.g. inside the stats row or at the
   bottom):
   ```html
   <span class="text-slate-600 text-xs">›</span>
   ```
3. **Add one delegated listener per container** (below):

```javascript
// Momentum card tap → Lookup (covers both Momentum Cards and Rotation views)
document.getElementById('momentum-list').addEventListener('click', e => {
  const card = e.target.closest('[data-group-name]');
  if (!card) return;
  const name = card.dataset.groupName;
  if (!name) return;
  switchTab('lookup');
  document.documentElement.scrollTop = 0;
  document.body.scrollTop = 0; // iOS Safari
  doGroupLookup(name, state.group);
});

// Strength card tap → Lookup (covers Sustained, Weak, and All Green views)
document.getElementById('strength-list').addEventListener('click', e => {
  const card = e.target.closest('[data-group-name]');
  if (!card) return;
  const name = card.dataset.groupName;
  if (!name) return;
  switchTab('lookup');
  document.documentElement.scrollTop = 0;
  document.body.scrollTop = 0; // iOS Safari
  doGroupLookup(name, state.group);
});

// vs Market card tap → Lookup (covers RS Score and RS Regime views)
document.getElementById('vsmarket-list').addEventListener('click', e => {
  const card = e.target.closest('[data-group-name]');
  if (!card) return;
  const name = card.dataset.groupName;
  if (!name) return;
  switchTab('lookup');
  document.documentElement.scrollTop = 0;
  document.body.scrollTop = 0; // iOS Safari
  doGroupLookup(name, state.group);
});
```

Each listener covers both view modes within its tab automatically — `renderMomentum`
dispatches to either `renderMomentumCards` or `renderRotation`, both writing to
`#momentum-list`; same pattern for the other two.

#### renderStrength gotcha — two code branches

`renderStrength` has two branches that both write to `#strength-list`:

- **Sustained/Weak view** (`view === 'sustained'`): cards built inside `renderList`
  closure (~line 1547). The card root `<div>` at ~line 1560 currently has no data
  attribute. Add `data-group-name="${escapeHtml(row.name)}"` there.

- **All Green view** (else branch): cards built in `.map()` at ~line 1608. The card
  root `<div>` currently has no data attribute. Add `data-group-name="${escapeHtml(row.name)}"`.

Both branches share the single `#strength-list` listener — no extra listener needed.

#### renderRsRegime gotcha — inner renderCard function

`renderRsRegime` builds cards inside an inner `renderCard(row)` function at ~line 1730.
The card root `<div>` is at ~line 1746. Add `data-group-name="${escapeHtml(row.name)}"` there.

---

### Part B — Today tab (special case)

Today cards tap to expand/collapse (listener at line 3367 checks `[data-name]`). Making
the whole card navigate to Lookup would break that primary action.

**Solution:** add a small dedicated `<button>` to each card header as a separate tap target.

In `renderToday()`, within each card's header row (`<div class="flex items-center ...">` at
~line 1232), add a small button **after** the group name text:

```html
<button data-today-lookup="${escapeHtml(row.name)}"
        class="text-slate-500 hover:text-slate-300 text-sm px-1 select-none flex-shrink-0"
        title="Open in Lookup">›</button>
```

**Listener** — register this BEFORE the existing expand listener at line 3367 (or place
the new listener before it in source order). The expand handler fires for clicks on
`[data-name]` (the card root div). The lookup button is a child of that div, so without
`stopPropagation()` both would fire. We stop propagation in the new listener:

```javascript
// Today card › button → Lookup. Register before the expand handler (line 3367).
// stopPropagation prevents the card expand from also firing when tapping the button.
document.getElementById('today-cards').addEventListener('click', e => {
  const btn = e.target.closest('[data-today-lookup]');
  if (!btn) return; // not our button — expand handler fires normally
  e.stopPropagation();
  const name = btn.dataset.todayLookup;
  if (!name) return;
  switchTab('lookup');
  document.documentElement.scrollTop = 0;
  document.body.scrollTop = 0; // iOS Safari
  doGroupLookup(name, state.group);
});
// existing expand handler stays at line 3367, unchanged
```

No capture phase needed — bubble phase with `stopPropagation()` is sufficient and less
surprising to future readers.

---

## Tests

Add to `tests/test_functional_playwright.py`. The existing Playwright test pattern in that
file (see the "movers lookback buttons" tests) uses a local HTTP server serving `docs/` +
route interception for the raw CSV fetches. Use the same fixture files in `tests/fixtures/`.

**Required fixture coverage:** fixture CSVs must contain at least one row with a group name
containing `&` (e.g., include a row for "Oil & Gas" in `industries_deltas.csv` fixture) to
cover the special-character round-trip.

**8 new test functions:**

```python
def test_momentum_card_tap_opens_lookup(page, local_pwa):
    """Click a Momentum card; assert Lookup tab becomes active and shows that group."""

def test_rotation_card_tap_opens_lookup(page, local_pwa):
    """Switch to Rotation view on Momentum tab; click a card; assert Lookup opens."""

def test_strength_card_tap_opens_lookup(page, local_pwa):
    """Click a Sustained Strength card; assert Lookup tab opens."""

def test_allgreen_card_tap_opens_lookup(page, local_pwa):
    """Switch to All Green view on Strength tab; click a card; assert Lookup opens."""

def test_rscore_card_tap_opens_lookup(page, local_pwa):
    """Click an RS Score card on vs Market tab; assert Lookup tab opens."""

def test_rsregime_card_tap_opens_lookup(page, local_pwa):
    """Switch to RS Regime view; click a card; assert Lookup tab opens."""

def test_today_card_lookup_button(page, local_pwa):
    """Tap the › lookup button on a Today card; assert Lookup opens WITHOUT expanding the card."""
    # Assert the card did NOT toggle its expand state (detail section should NOT appear)

def test_ampersand_group_name_round_trips(page, local_pwa):
    """Tap a card whose name contains '&'; assert Lookup renders the name as 'Oil & Gas'
    (not 'Oil &amp; Gas' or corrupted). Tests escapeHtml encode/decode round-trip."""
```

Run tests with:
```bash
python3 -m playwright install chromium
python3 -m pytest tests/test_functional_playwright.py -v
```

The existing tests in this file are excluded from default CI (they require Playwright); the
new tests follow the same pattern and the same exclusion applies. Run them manually in cloud
or locally before the PR is merged.

---

## Release entry (in same PR as implementation)

Per `CLAUDE.md` "Cutting a release" — all three together:

1. **Prepend** to `docs/releases.json` `releases[]` (current latest is `2026.06.22.1`,
   `CACHE` is `finviz-v24`):
   ```json
   {
     "version": "YYYY.MM.DD",
     "date": "YYYY-MM-DD",
     "title": "Tap any card to drill into Lookup",
     "tag": "feature",
     "notes": [
       "Every group card across Momentum, Strength, vs Market, and Today tabs now taps through to the Lookup tab with that group pre-filled.",
       "Subtle › affordance on each card signals tappability. No back-navigation from Lookup — by design for now."
     ]
   }
   ```
   Use today's date as the version (`YYYY.MM.DD`). If there's already an entry for today,
   append `.1` (e.g. `2026.06.23.1`).

2. **Update** top-level `current` to match the new version.

3. **Bump** `CACHE` in `docs/sw.js` from `finviz-v24` to `finviz-v25`.

---

## Files to modify

| File | What changes |
|------|-------------|
| `docs/index.html` | `data-group-name` + CSS + `›` on 6 card root divs (2 branches in `renderStrength`, inner fn in `renderRsRegime`); `data-today-lookup` button in `renderToday()`; 4 delegated click listeners near line 3348 |
| `docs/releases.json` | Prepend release entry, update `current` |
| `docs/sw.js` | Bump `CACHE` from `finviz-v24` to `finviz-v25` |
| `tests/test_functional_playwright.py` | 8 new test functions |

---

## Verification checklist

- [ ] `python3 -m pytest tests/ -q` passes (all existing tests + new ones)
- [ ] Serve `docs/` locally, navigate to each tab, tap a card → Lookup tab activates and
      shows that group's data
- [ ] "Oil & Gas" card → Lookup renders "Oil & Gas" (not `&amp;`)
- [ ] Today tab: tap card body → card expands; tap `›` button → Lookup opens, card does
      NOT expand (two independent actions)
- [ ] Group toggle: switch to Industries, tap any card → correct group type looked up
- [ ] `tests/test_guide_releases.py` passes (guards `current === releases[0].version`)

---

## Known gaps / follow-up notes

- **No back-navigation from Lookup** — acceptable for now. Noted in release notes.
- **`data-mover-name` inconsistency** — PR156 used `data-mover-name`; new cards standardize
  on `data-group-name`. Could unify in a future cleanup PR but not worth the risk here.
- **AI tab** — no per-group cards; briefing text may name groups but they're unstructured
  prose. Out of scope.
- **Today expand affordance** — the `›` lookup button sits in the header row. If UX testing
  shows the button is too subtle or conflicts with the expand tap zone, revisit with a
  dedicated icon (magnifier, `⊕`) in a follow-up.

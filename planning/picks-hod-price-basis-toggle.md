# Plan: HoD ↔ Last price-basis toggle for Picks risk metrics

> **Status:** 📋 **Design approved, not yet implemented.** Greenlit to build **Phase A first,
> Phase B as the committed end goal** (not a spike). This doc is written so any contributor can
> pick it up cold. No code has been written yet.

---

## 1. Context — the problem this solves

The Picks tab (`docs/index.html`) shows a daily Stage-2 stock list. Each row's risk metrics —
**risk-to-20MA**, **risk-to-50MA**, **ATR extension (×50MA)**, dollar-per-share risk, and
stop-distance-in-ATR — are all computed from the stock's **last/close price** (`Price`). They
are pre-computed by the Python pipeline (`scripts/picks_metrics.py`) and stored as columns in
`data/picks/picks_latest.csv` (`atr_ext_50`, `risk_20ma_pct`, `risk_50ma_pct`).

**The trader's actual entry is often not the close.** A common setup is to enter on a **break
above the prior session's high of day (HoD)**. When that's the plan, the *real* risk should be
measured from the HoD entry, not from the last print. On a **wide-range bar** that closed well
off its high, the two diverge sharply: a stock that looks like a tight, low-risk entry at the
close can be a materially wider-risk, more-extended entry if you chase the high.

**Goal:** let the user view (Phase A) and ultimately rank by (Phase B) the risk metrics computed
from either price basis — **`Last`** (close, today's behavior) or **`HoD`** (prior session high).

### Worked example (the wide-bar case this is built for)

```
Price (last) $100.00   High/HoD $103.00   Low $99.00   ATR $3.00
20MA +2.0% above → MA price $98.04     50MA +5.0% above → MA price $95.24
```

| Metric              | Last basis        | HoD basis         | Why it moves                          |
|---------------------|-------------------|-------------------|---------------------------------------|
| Risk to 20MA        | +1.96% / $1.96/sh | +4.82% / $4.96/sh | entry $3 higher, MA fixed → ~2.5× risk |
| Risk to 50MA        | +4.76%            | +7.53%            | same                                  |
| Ext (×50MA)         | 1.6×              | 2.6×              | crosses `ATR_EXT_PENALTY_START` (2.5) |
| Stop dist (ATR)     | 0.65×             | 1.65×             | sub-1-ATR stop becomes 1.65-ATR       |
| Range/ATR           | 1.33              | 1.33              | **bar property — fixed (see §3)**     |
| Volatility (ATR%)   | 3.0%              | 3.0%              | **instrument property — fixed (§3)**  |

---

## 2. The two phases, in plain terms

- **Phase A — per-card what-if toggle.** Inside an *expanded* pick card, a small
  `[ Last │ HoD ]` segmented control. Flipping it recomputes the risk numbers **in that one
  card only**. Rankings, sort order, Focus scores, and collapsed-row badges are untouched. It is
  a what-if calculator for the single stock you're contemplating. Per-card, ephemeral state.

- **Phase B — tab-level price-basis toggle (the end goal).** One global `[ Last │ HoD ]` switch
  at the top of the Picks tab. Flipping it to HoD **re-derives the risk metrics for every row**
  and feeds them into the Focus hard gate, the Focus score, the extension penalty, and the
  sort — so **the whole list re-ranks** off HoD. This is the feature that turns the wide-bar
  insight into a ranking signal.

Phase B is accepted to run **systematically stricter** than Last mode: because `High ≥ Price`
by definition, every stock is at least as extended under HoD, so more names hit the extension
penalty ramp and the hard-DQ. This is **intended and acceptable** (CEO decision) — HoD mode
answers "if I buy the breakout, what's actually actionable?", and a stricter sheet is the
correct answer to that question. No separate HoD threshold set in v1; revisit only if real use
shows the strictness is unhelpful.

---

## 3. The metric-split rule (applies to BOTH phases — get this right)

Only the **"where am I relative to my stop" family** re-bases on the chosen price. Everything
that describes the **bar or the instrument** stays on close, *always*, in both modes:

| Re-bases with `basis` (Last/HoD)        | Always stays on close price            |
|-----------------------------------------|----------------------------------------|
| `atr_ext_50` = (P − sma50_price)/ATR    | `range_atr` = (High − Low)/ATR         |
| `risk_20ma_pct` = (P − sma20_price)/P   | volatility = ATR/Price                 |
| `risk_50ma_pct` = (P − sma50_price)/P   | the MA *prices* themselves (sma20/50)  |
| $/sh risk = P × risk_fraction           | `grp_*` group metrics                  |
| stop-distance-ATR = risk_frac × P / ATR | `stage2`, RSI, perf columns            |

Where `P = (basis === 'hod' ? High : Price)`.

**Why the MAs stay fixed:** the moving averages are close-based historical values. Choosing to
enter higher does not move them — it only moves *you* relative to them. The reconstruction
`sma_price = Price / (1 + SMA_pct/100)` already gives the MA dollar level independent of which
`P` you display, so this falls out for free.

**Why volatility and Range/ATR stay on close:** ATR% is "how much does this instrument move per
day," and Range/ATR is "how wide was today's bar" — both are properties of the stock/bar, not of
your entry. Buying higher doesn't make the stock less volatile or its bar narrower.

---

## 4. Compatibility — why Phase A is not wasted work toward Phase B

**This was verified against the code before approval. Both phases share one engine.**

Today, all five ranking/scoring/gating consumers read the risk metrics **straight off the CSV
row** (`r.atr_ext_50`, `r.risk_20ma_pct`, `r.risk_50ma_pct`), which the pipeline computed at
close:

| Consumer                     | Location (current line refs) | Field read            |
|------------------------------|------------------------------|-----------------------|
| Focus hard gate              | `index.html` ~`:3522`        | `r.atr_ext_50`        |
| Focus score (tightness)      | `index.html` ~`:3414`        | `risk_20ma_pct`, `risk_50ma_pct` |
| Focus extension penalty      | `index.html` ~`:3452`        | `r.atr_ext_50`        |
| All-view sort                | `index.html` ~`:3590`        | `r.atr_ext_50`        |
| All-view pre-scored Focus map| `index.html` ~`:3561`–`3566` | `r.atr_ext_50` (via `computeFocusScores`) |
| Card display (risk panel)    | `index.html` ~`:3260`–`3340` | all of the above      |

> **Note:** the All-view pre-scored Focus map (`:3561`–`:3566`) computes Focus scores for All-view
> score badges (shown on collapsed rows next to the ticker in All view). This is a 6th call site
> that must use derived metrics in Phase B, not just the four gate/score/sort/card consumers listed
> above. It goes through `computeFocusScores` which also reads `r.atr_ext_50` directly.

Both phases need the **identical** primitive: those three numbers re-derived from a chosen
basis. So the mandated foundation (built in Phase A, reused verbatim in Phase B) is one pure
function:

```js
// basis ∈ {'last','hod'}; returns the re-based risk family. MAs/range/vol per §3 stay fixed.
function deriveRiskMetrics(row, basis) {
  const price = _pF(row['Price']);
  const high  = _pF(row['High']);
  const atr   = _pF(row['ATR']);
  const P     = (basis === 'hod' && !isNaN(high)) ? high : price;
  // sma20_price, sma50_price reconstructed from row SMA20/SMA50 pct (close-based, fixed)
  // sma20_price = price / (1 + _pPct(row['SMA20']) / 100)  ← denominator is always close price
  // sma50_price = price / (1 + _pPct(row['SMA50']) / 100)
  //
  // Explicit return shape — all fields required:
  //   atr_ext_50:      (P − sma50_price) / atr
  //   risk_20ma_pct:   (P − sma20_price) / P          ← denominator is P, not close
  //   risk_50ma_pct:   (P − sma50_price) / P
  //   sma20_price, sma50_price                         (dollar levels, for card display)
  //   risk20DolPerSh:  P − sma20_price                 (=P × risk_20ma_pct; separate key for clarity)
  //   risk50DolPerSh:  P − sma50_price
  //   stopDistAtr:     (nearest positive risk_fraction × P) / atr
  // NaN-safe throughout — any blank/missing input → NaN for that field, never throws.
}
```

> **Note on the existing inline block:** `renderPickRow` already computes `sma20Price`, `sma50Price`,
> `risk20f`, `risk50f`, `stopDistAtr` etc. inline at ~`:3262`–`3289`. Phase A **replaces** that
> block with a call to `deriveRiskMetrics(r, cardBasis)` — do not add `deriveRiskMetrics` alongside
> the existing code. The inline block is superseded.

- **Phase A** routes *one expanded card's display* through `deriveRiskMetrics(r, cardBasis)`.
- **Phase B** routes *the gate + score + sort + every card* through the **same function** with a
  global `state.picksBasis`.

The hard, error-prone part — the formulas and the §3 split — is written once in Phase A and
reused unchanged in Phase B. **Phase-A-only** code is a per-card toggle UI + local state.
**Phase-B-only** code threads `basis` into the four consumers above. Nothing built for A is
rewritten for B.

> **MANDATE:** Phase A **must** be implemented as the pure `deriveRiskMetrics(row, basis)`
> function with the card reading through it — **not** as an inline `Last/HoD` swap buried in the
> card renderer. The inline shortcut would have to be torn out and rewritten for B; the function
> form makes A a strict down-payment on B. Reviewers: reject a Phase A PR that inlines the swap.

**No pipeline / CSV change needed for either phase.** `High`, `Price`, `ATR`, `SMA20/50/200`
are already columns in `picks_latest.csv` (the card already renders `r['High']`). This is
entirely client-side in `docs/index.html`.

---

## 5. Phase A — detailed design

### 5.1 The `deriveRiskMetrics(row, basis)` helper
Pure function, near the existing risk-panel logic in `renderPickRow`. Implements §3 exactly.
Returns `atr_ext_50`, `risk_20ma_pct`, `risk_50ma_pct`, the reconstructed MA dollar prices,
$/sh risk for each MA, and stop-distance-ATR. NaN-safe (any blank input → NaN for that field,
never throws), mirroring `scripts/picks_metrics.py`.

> **Anti-drift:** the JS formulas must stay numerically identical to `picks_metrics.py` for the
> `Last` basis. A `Last`-basis call to `deriveRiskMetrics` must reproduce the stored CSV values.
> This is the v1 regression anchor (see §7).

### 5.2 Per-card toggle UI
Segmented control at the top of the expanded risk panel:
```
Risk basis:  [ Last ]  ·  HoD
```
- Default: `Last`. State is **per-card and ephemeral** — resets to `Last` when the card is
  collapsed. No `localStorage` in v1 (persistence is an explicit later evaluation — §8).
- Flipping recomputes only that card's risk panel. No list re-render, no sort change, no badge
  change on the collapsed row.
- When `HoD` is active, show a one-line context note: *"risk measured from $103.00 entry (last
  session high)."*
- **Cosmetic note:** the expanded card already has a cell labelled *"HoD (next buy trigger): $103.00"*
  (~`:3319`). In HoD mode the context note and that cell will both reference the same price — this is
  redundant but not wrong (one names the price, one explains how it's used). This is acceptable for v1.
  If it feels noisy in use, remove the context note and rely on the existing HoD cell label alone
  (do not rename the cell).

### 5.3 Trim / extension color under HoD (resolved decision)
- **Color ramp** (emerald → amber → red on `atr_ext_50`): **apply in HoD mode.** Coloring the
  number honestly reflects that a HoD entry is more extended. Uses the same `ATR_EXT_*`
  thresholds.
- **`trim` badge:** in HoD mode the `atr_ext ≥ ATR_EXT_TRIM` flag **still fires with the same
  color**, but the **word changes `trim` → `extended`**. Rationale: `trim` means "reduce a held
  position" (a current-price, position-management instruction); in a HoD what-if you hold
  nothing at that price, so the honest label for the same red state is "extended," not "trim."
  `Last` mode keeps the word `trim`.

### 5.4 What Phase A does NOT touch
Collapsed-row badges, the Focus score, the sort, the hard gate, the All-view grouping. All
remain on `Last`. Phase A is display-only.

---

## 6. Phase B — detailed design (the end goal)

### 6.1 Global basis state
Add `state.picksBasis` (`'last'` | `'hod'`, default `'last'`). A `[ Last │ HoD ]` segmented
control in the Picks tab header (next to the existing All/Focus toggle). Flipping it calls
`renderPicks()`.

### 6.2 Thread `basis` through every consumer
`renderPicks()` derives each row's effective risk metrics via `deriveRiskMetrics(r,
state.picksBasis)` **before** gating/scoring/sorting. Concretely:

1. **Focus hard gate** (`:3522`) — gate on the *derived* `atr_ext_50`, not `r.atr_ext_50`.
2. **`computeFocusScores`** (`:3403`) — its `rawTight` (risk_20/50) and the per-row `atrExt` used
   in the penalty must come from the derived metrics. **`rawQuiet` (`range_atr`) and `rawGroup`
   stay as-is** (§3 — bar/group properties).
3. **All-view sort** (`:3590`) — sort on derived `atr_ext_50`.
4. **Every card render** — `renderPickRow` shows derived numbers consistent with the global
   basis.

**Threading mechanism (use this exact pattern):** compute derived metrics once per row at the
top of `renderPicks()` using a spread overlay — `const dr = {...r, ...deriveRiskMetrics(r, state.picksBasis)}` —
and pass `dr` (not `r`) into every downstream call. This is zero-mutation (the original CSV row
is untouched, so toggling back to Last mode just re-calls `renderPicks()` with fresh spreads),
and it requires no signature change to `renderPickRow` or `computeFocusScores` — both already
read fields off their row argument, so passing `dr` instead of `r` is the only change at each
call site. Do NOT mutate `r` directly (original values are lost, toggling back fails) and do NOT
add a new parameter to `renderPickRow` (it would require updating `renderIndustryCard` on the
Today tab, which this feature should not touch).

> **Note on collapsed-row badges in Phase B:** the All and Focus views both show the ATR badge
> and `trim` chip on the collapsed row. Under Phase B, these **also** reflect the global basis
> (not just the expanded panel). Concretely: `atrExt`, `isTrim`, and `atrCls` at the top of
> `renderPickRow` (~`:3226`–`3229`) are computed from the row argument — passing the spread `dr`
> (derived) row means the collapsed badge automatically reflects HoD when that's the global basis.
> No extra work needed if the threading pattern above is followed; just confirm the collapsed badge
> updates correctly in the Phase B test.

### 6.3 Interaction between the global toggle (B) and per-card toggle (A)
**Decision for v1:** the global basis sets the default each card opens in. The per-card toggle
(A) remains available as a **local override** for a single open card (e.g. global = Last, but I
want to peek at one name's HoD risk). Collapsing the card discards the override and it reverts to
the global basis. This keeps A useful after B ships rather than making it redundant.

> **Implementation note:** Phase A initialises per-card state to `'last'`. Phase B changes that
> initialisation to `state.picksBasis` (the global default). The reset-on-collapse behaviour
> (currently resets to `'last'`) must become "resets to `state.picksBasis`" — not hardcoded to
> `'last'` — otherwise a Phase B card always opens in Last even when global = HoD.
> If this dual-control proves confusing in use, the fallback is to drop the per-card toggle once
> B exists and rely on the global switch alone. Flagged as a post-use evaluation (§8).

### 6.4 Strictness is expected (not a bug)
Per §2, HoD mode legitimately gates out more names and re-ranks toward less-extended entries.
The Focus empty-state copy should still read correctly when HoD strictness empties the list
(*"No Focus candidates — all actionable names are over-extended…"* already covers it). No
threshold retuning in v1.

### 6.5 Guide / copy
- Add a `GUIDE` glossary entry explaining the price-basis toggle (verbatim-synced to
  `knowledge/moaty-metrics.md` per the project's anti-drift rule — add the User one-liner there
  first, then copy into `GUIDE`).
- The Focus note and any tooltips that say "risk to the 20MA" should make clear, when HoD is
  active, that risk is measured from the prior session high.

---

## 7. Testing

Playwright PWA functional tests run in cloud (see CLAUDE.md § "What Playwright in cloud
unlocks"); intercept the `picks_latest.csv` fetch with a fixture. Test file: **`tests/test_pwa_picks_hod.py`**.

**Phase A:**
- **Regression anchor:** `deriveRiskMetrics(row, 'last')` reproduces the stored CSV
  `atr_ext_50` / `risk_20ma_pct` / `risk_50ma_pct` for a fixture row (numerically identical to
  `picks_metrics.py`). This is the guard that the JS port didn't drift.
- HoD basis on the §1 worked-example fixture produces the expected HoD column values.
- `range_atr` and volatility are **identical** across Last/HoD (the §3 fixed-set guard).
- Toggle resets to `Last` on collapse; per-card state doesn't leak to sibling cards.
- `trim` → `extended` word swap fires in HoD mode at `atr_ext ≥ ATR_EXT_TRIM`.

**Phase B:**
- A fixture with a deliberate wide-bar name verifies the Focus order **changes** between Last
  and HoD, and that the wide-bar name sinks / drops out of the gate under HoD.
- `range_atr`/group inputs to the score are unchanged across basis (only tightness + penalty
  move).
- Global toggle defaults to `last`; a per-card override reverts on collapse.

A Python-side unit test is **not** required (no pipeline change), but the regression-anchor test
above effectively cross-checks the JS against `picks_metrics.py`.

---

## 8. Explicitly deferred (post-use evaluations, not v1)

- **Persistence of basis choice** (localStorage) — for A (per-card) and/or B (global). Decide
  after the CEO has used it. v1 = ephemeral.
- **Whether the per-card toggle survives once B ships** (§6.3) or is dropped for the global one.
- **A separate HoD threshold set** (`ATR_EXT_*` tuned for HoD) if the inherited strictness
  proves unhelpful. v1 reuses the Last thresholds.

---

## 9. Release checklist (when shipping each phase to the PWA)

User-facing PWA change ⇒ do all three together (CLAUDE.md § Automation):
1. Prepend a `releases.json` entry (`tab: 'picks'`), set top-level `current`.
2. Bump `CACHE` in `docs/sw.js`.
3. Add/sync the `GUIDE` entry + `knowledge/moaty-metrics.md` User one-liner.

---

## 10. Configurable constants touched

No **new** constants in v1. The existing `ATR_EXT_ACTIONABLE`, `ATR_EXT_TRIM`,
`ATR_EXT_PENALTY_START`, `PENALTY_MAX`, `FOCUS_W_*` (documented in `index.html`, README, and
CLAUDE.md) are **reused** for both bases. If §8's separate-HoD-threshold path is ever taken, any
new constant must be triple-documented per the project's configurable-constants rule.

# Picks Methodology Tracking — Plan

**Goal:** Make any day's Picks (All) and Focus tab output replayable from historical data, and enable A/B testing of selectors and scoring logic by versioning the methodology that was active on each date.

**Status:** Plan only. No implementation yet.

---

## Background

The picks pipeline produces two artifacts every day:

- `data/picks/picks.csv` — append-only log of every stock scraped, one row per
  `(date, ticker)`. Contains all raw data needed to reconstruct the display.
- `data/picks/picks_latest.csv` — the max-date slice of `picks.csv`; this is what
  the PWA fetches.

The PWA (`docs/index.html`) reads `picks_latest.csv` and applies two layers of logic
client-side to produce what the user sees:

| Layer | What it does | Currently versioned? |
|-------|-------------|---------------------|
| **Group selector** (Python, server-side) | Which industry groups get scraped each day | ✓ `data/picks/selector_versions.json` |
| **Display methodology** (JS, client-side) | Which stocks are shown, how Focus scores are computed | ✗ Not versioned |

`picks.csv` already has all the columns needed for replay. The only missing piece is a
record of which display methodology constants were active on any given date.

---

## Design

### New file: `data/picks/display_methodology.json`

Same versioning pattern as `selector_versions.json`: a `current` pointer and a
`versions[]` array sorted newest-first. Each entry captures every constant that
affects what the PWA shows and in what order.

**Why separate from `selector_versions.json`?** The two layers change independently.
The selector is a Python pipeline concern (which groups to scrape). The display
methodology is a PWA concern (how to filter and rank the scraped stocks). Keeping them
separate means a Focus weight tweak doesn't pollute selector history and vice versa.
For A/B testing that touches both simultaneously, join by `effective_date`.

**Version lookup:** to find the methodology in effect on date D, take the entry with
the largest `effective_date ≤ D`. This mirrors how `selector_versions.json` works.

**No column added to `picks.csv`.** The dated version entries are sufficient; there is
no need to stamp each row.

---

### v1 initial entry (current state as of 2026-06-25)

The v1 entry captures the methodology that was in effect from the first day of the picks
pipeline (2026-06-25) through the present. All values below are read from the current
`docs/index.html` constants and rendering logic.

```json
{
  "current": "v1",
  "versions": [
    {
      "version": "v1",
      "effective_date": "2026-06-25",
      "description": "Initial display methodology (Phase 3b). Base display filter gates both All and Focus views. All view groups by selector category then industry, sorts least-extended first. Focus view adds hard ATR-extension DQ, cross-sectional 3-component scoring (group strength + stop tightness + quiet bar), and extension penalty ramp. VP-locked alongside selector v1.",
      "params": {
        "base_filter": {
          "min_market_cap_b": 5,
          "note": "Market Cap column in picks.csv is in billions (float). Row is excluded if market_cap <= 5.",
          "ma_positioning": {
            "logic": "any",
            "conditions": [
              "SMA50 > 0",
              "SMA200 > 0",
              "SMA50 > SMA20"
            ],
            "columns": ["SMA50", "SMA200", "SMA20"],
            "note": "SMA* columns are % distance from MA (e.g. 5.2 = price is 5.2% above that MA). A row passes if ANY condition holds. All three NaN = fails."
          }
        },
        "all_view_sort": {
          "primary": "list_category",
          "category_order": ["leaders", "emerging", "accel", "rs_new_high"],
          "secondary": "grp_name",
          "tertiary": {
            "col": "atr_ext_50",
            "direction": "asc",
            "note": "Least-extended first within each group."
          }
        },
        "focus_dq": {
          "col": "atr_ext_50",
          "min_exclusive": 0,
          "max_inclusive": 4.0,
          "note": "atr_ext_50 <= 0 means price is at or below the 50MA (not actionable). > ATR_EXT_ACTIONABLE means over-extended. Both are hard disqualifications."
        },
        "focus_score": {
          "formula": "score = base * (1 - penaltyFrac)",
          "base_formula": "FOCUS_W_GROUP * normGroup + FOCUS_W_TIGHT * normTight + FOCUS_W_QUIET * normQuiet",
          "weights": {
            "group": 0.4,
            "tight": 0.4,
            "quiet": 0.2
          },
          "components": {
            "group": {
              "col": "grp_sum_mid_rank",
              "direction": "lower_is_better",
              "note": "Sum of rank_month + rank_quarter + rank_half for the selecting group. Lower = stronger group."
            },
            "tight": {
              "cols": ["risk_20ma_pct", "risk_50ma_pct"],
              "selection": "min of positive values only",
              "direction": "lower_is_better",
              "note": "Nearest MA stop below the price. risk_50ma_pct is always positive for Focus members (price > 50MA is the DQ gate). risk_20ma_pct only qualifies if > 0 (20MA is below price). Takes the smaller of the two qualifying values."
            },
            "quiet": {
              "col": "range_atr",
              "direction": "lower_is_better",
              "note": "Today's high-low range divided by ATR. Narrower = more orderly day."
            }
          },
          "normalization": {
            "method": "inverted_minmax",
            "fallback_method": "rank_percentile",
            "fallback_threshold_col": "FOCUS_MIN_POOL",
            "fallback_threshold": 5,
            "all_equal_default": 0.5,
            "nan_default": 0.5,
            "note": "Inverted: lower raw value → higher normalized score (1.0 = best). When pool < 5, rank-based percentile replaces min–max to avoid jumpy scores. All-equal in a component → everyone gets 0.5. NaN → 0.5 (neutral contribution)."
          },
          "extension_penalty": {
            "col": "atr_ext_50",
            "ramp_start": 2.5,
            "ramp_end": 4.0,
            "max_fraction": 0.5,
            "formula": "penaltyT = clamp((atr_ext - 2.5) / (4.0 - 2.5), 0, 1); penaltyFrac = 0.5 * penaltyT",
            "note": "0 penalty below 2.5×. Ramps linearly to 50% haircut at 4.0× (ATR_EXT_ACTIONABLE). score is always in [0, 1]."
          }
        },
        "focus_sort": {
          "col": "score",
          "direction": "desc"
        },
        "atr_bands": {
          "emerald_max": 4.0,
          "amber_max": 8.0,
          "note": "Display-only color bands on atr_ext_50. Emerald = actionable zone; amber = caution; red = trim candidate."
        }
      }
    }
  ]
}
```

---

## When to add a new version entry

Whenever any value in `params` changes in `docs/index.html`, the implementer must:

1. Append a new entry to `display_methodology.json` `versions[]` (prepend, keeping
   newest-first).
2. Update `current` to the new version label.
3. Set `effective_date` to the first date the new constants are live.
4. Increment the version label (`v1` → `v2`, etc.).

The same discipline already applies to `selector_versions.json`. Both files should be
updated in the same PR as the `index.html` or `picks_config.py` change that triggers it.

---

## Replay plan (for future implementation)

This section is a complete specification for whoever writes `scripts/replay_picks.py`.

### Inputs

| Input | Source |
|-------|--------|
| `date` | CLI arg `--date YYYY-MM-DD` (default: max date in picks.csv) |
| Raw stock data | `data/picks/picks.csv` filtered to `date = <target>` |
| Display methodology | `data/picks/display_methodology.json`, latest version with `effective_date ≤ date` |
| Group selector | `data/picks/selector_versions.json`, latest version with `effective_date ≤ date` (informational only for replay; data already reflects which groups were selected) |

### Step-by-step replay algorithm

**Step 1 — Load and filter to date**
```python
df = pd.read_csv('data/picks/picks.csv')
df = df[df['date'] == target_date]
```

**Step 2 — Apply base display filter**

```python
# Market cap gate (market_cap is in billions as a float)
df = df[df['market_cap'] > methodology['params']['base_filter']['min_market_cap_b']]

# MA positioning gate: any of (SMA50>0) OR (SMA200>0) OR (SMA50>SMA20)
# SMA* columns are % distance floats; NaN if MA was unavailable that day.
sma50  = pd.to_numeric(df['SMA50'],  errors='coerce')
sma200 = pd.to_numeric(df['SMA200'], errors='coerce')
sma20  = pd.to_numeric(df['SMA20'],  errors='coerce')

ma_pass = (sma50 > 0) | (sma200 > 0) | (sma50 > sma20)
df = df[ma_pass]
```

**Step 3A — All view output**

Group by `list_category`, then within each category group by `grp_name`, then sort by
`atr_ext_50` ascending (least-extended first within each group). Category display order:
`['leaders', 'emerging', 'accel', 'rs_new_high']`.

**Step 3B — Focus view output**

```python
p = methodology['params']

# Hard DQ gate
atr = pd.to_numeric(df['atr_ext_50'], errors='coerce')
focus_candidates = df[(atr > p['focus_dq']['min_exclusive']) &
                      (atr <= p['focus_dq']['max_inclusive'])].copy()

# Component raw values
raw_group = pd.to_numeric(focus_candidates['grp_sum_mid_rank'], errors='coerce')

r20 = pd.to_numeric(focus_candidates['risk_20ma_pct'], errors='coerce')
r50 = pd.to_numeric(focus_candidates['risk_50ma_pct'], errors='coerce')
# Nearest positive MA stop: smallest of the qualifying (positive) values
raw_tight = pd.DataFrame({'r20': r20, 'r50': r50}).apply(
    lambda row: min(v for v in [row.r20, row.r50] if pd.notna(v) and v > 0),
    axis=1
)

raw_quiet = pd.to_numeric(focus_candidates['range_atr'], errors='coerce')

# Inverted min–max normalization (or rank-based for small pools)
def normalize_inv(series, min_pool):
    valid = series.dropna()
    if len(valid) == 0:
        return pd.Series(0.5, index=series.index)
    if len(series) < min_pool:
        ranked = series.rank(ascending=True, na_option='keep')  # lower raw = better (rank 1)
        m = valid.count()
        return (1 - (ranked - 1) / (m - 1)).fillna(0.5) if m > 1 else pd.Series(1.0, index=series.index)
    mn, mx = valid.min(), valid.max()
    if mx == mn:
        return pd.Series(0.5, index=series.index)
    return ((mx - series) / (mx - mn)).fillna(0.5)

min_pool = p['focus_score']['normalization']['fallback_threshold']
w = p['focus_score']['weights']

norm_group = normalize_inv(raw_group, min_pool)
norm_tight = normalize_inv(raw_tight, min_pool)
norm_quiet = normalize_inv(raw_quiet, min_pool)

base = w['group'] * norm_group + w['tight'] * norm_tight + w['quiet'] * norm_quiet

# Extension penalty
ep = p['focus_score']['extension_penalty']
atr_focus = pd.to_numeric(focus_candidates['atr_ext_50'], errors='coerce')
penalty_t = ((atr_focus - ep['ramp_start']) / (ep['ramp_end'] - ep['ramp_start'])).clip(0, 1).fillna(0)
penalty_frac = ep['max_fraction'] * penalty_t

focus_candidates = focus_candidates.copy()
focus_candidates['focus_score'] = base * (1 - penalty_frac)
focus_candidates = focus_candidates.sort_values('focus_score', ascending=False)
```

### A/B testing pattern

To compare two methodology versions on the same date:

```python
output_a = replay(date='2026-06-25', methodology_version='v1')
output_b = replay(date='2026-06-25', methodology_version='v2')
# Compare top-N overlap, rank correlation, score distribution
```

The same `picks.csv` data is used for both; only the constants differ. This makes it
straightforward to test: "if we had used heavier group-strength weighting (0.6/0.3/0.1),
how would the Focus ranking have changed on a given day?"

### CLI design (sketch)

```
python scripts/replay_picks.py [--date YYYY-MM-DD] [--view all|focus] [--methodology-version vN]
```

- `--date`: defaults to max date in picks.csv
- `--view`: `all` (default) or `focus`
- `--methodology-version`: defaults to the version that was effective on `--date`; can be
  overridden for A/B testing

Output: TSV or styled terminal table of stocks in display order, with key columns
(`ticker`, `grp_name`, `list_category`, `atr_ext_50`, `focus_score` for Focus view).

---

## Implementation checklist

- [ ] Create `data/picks/display_methodology.json` with v1 entry (values above)
- [ ] Update `CLAUDE.md` — add `display_methodology.json` to the data directory structure
  table and add a note in the "Picks pipeline" section about when to bump the version
- [ ] Update `README.md` § Configurable parameters — add a row for `display_methodology.json`
- [ ] Write `scripts/replay_picks.py` per the algorithm above
- [ ] Write `tests/test_replay_picks.py` — unit tests for the normalize_inv function and
  the full replay pipeline against a small fixture CSV
- [ ] Add anti-drift guard: a test (`tests/test_picks_methodology.py`) that reads the
  current v1 `params` from `display_methodology.json` and asserts each constant matches
  the corresponding constant in `docs/index.html` (same pattern as
  `tests/test_picks_button_config.py`). This prevents silent drift when someone edits
  `index.html` and forgets to bump the version.

---

## What is NOT needed

- **Snapshotting the actual list of displayed stocks** — `picks.csv` (raw data) +
  `display_methodology.json` (filter/ranking logic) are necessary and sufficient. The
  output is deterministic from these two inputs.
- **`display_methodology_version` column in `picks.csv`** — `effective_date` lookups on
  the version file handle this; no per-row stamp needed.
- **Merging with `selector_versions.json`** — they change independently. Join by
  `effective_date` when you need to reason about both simultaneously.

---

## File locations

| File | Purpose |
|------|---------|
| `data/picks/display_methodology.json` | NEW — versioned display constants |
| `data/picks/selector_versions.json` | EXISTS — versioned group selector constants |
| `data/picks/picks.csv` | EXISTS — raw data; all columns needed for replay already present |
| `scripts/replay_picks.py` | TO WRITE — replay + A/B test CLI |
| `tests/test_replay_picks.py` | TO WRITE — unit tests for replay logic |
| `tests/test_picks_methodology.py` | TO WRITE — anti-drift guard (JSON ↔ index.html) |

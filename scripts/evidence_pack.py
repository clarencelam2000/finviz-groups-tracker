"""Evidence pack builder, field registry, and model-output validator (AI-NEXT-P0a).

Tier A (Python) source of truth for the evidence-pack contract defined in
`planning/ai-evidence-pack-schema.md`. Tier B (`worker-positions/src/evidencePack.js`,
AI-NEXT-P4) must mirror this module field-for-field; the shared registry is emitted to
`data/ai/pack_schema.json` by `--emit-schema` and imported by both the JS builder and the
PWA renderer.

Design constraints this module is built to (schema §5):

* **Pure functions only.** No file I/O outside `--emit-schema`, no network, no API client.
  Every rule is unit-testable from `io.StringIO` fixtures per `branch-commit-discipline.md`.
* **The model never does arithmetic that reaches the screen.** Anything the reader will see
  as a number is a registered field with a unit; the model returns a template plus field
  references and the renderer formats by unit (§2.1).
* **Registry drift is a hard error** (owner decision, schema §6.1). Emitting a field id that
  is not registered for the surface raises `UnregisteredFieldError` — it does not warn.

No ground-truth CSV is read or written here. Per `.claude/rules/data-pipeline.md`, nothing
in this module becomes a column on `picks.csv` or the session stores.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import statistics
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

# ---------------------------------------------------------------------------
# Versioning (schema §4)
# ---------------------------------------------------------------------------

# PACK_VERSION is semver over the *field registry*. MINOR = fields added (a renderer built
# on 1.0 keeps working). MAJOR = a field removed, or its `u`/meaning changed — which can
# silently corrupt a cached statement's rendering, so a major bump invalidates cached Tier B
# statements (schema §4). Bump this in the same PR that changes FIELD_REGISTRY.
PACK_VERSION = "1.0.0"

# CONTRACT_VERSION is semver over the *model output shape* (§3): the statement object's keys
# and the per-surface kind sets. A renderer refuses output whose major version it does not
# understand. Independent of PACK_VERSION on purpose — the registry can grow fields without
# changing what a statement looks like.
CONTRACT_VERSION = "1.0.0"

# Rounding applied to every float in the canonical serialization (§2.5). 4 dp is well below
# any unit's display precision (usd shows 2, atr/x show 1) so it can never change what the
# reader sees; it exists to make `pack_hash` stable across platforms' float repr.
CANONICAL_FLOAT_DP = 4


# ---------------------------------------------------------------------------
# Units (schema §2.1)
# ---------------------------------------------------------------------------

# id -> {"desc": what it means, "plural": whether the renderer pluralises the noun}.
# The *formatters* live one per runtime — `formatUnit()` in `docs/index.html` (AI-NEXT-P0b)
# and the drawer's label renderer. Python declares the vocabulary and ships it in
# pack_schema.json; it deliberately does not format, because the whole point of slot filling
# is that the PWA's existing formatters own on-screen presentation (§2.1).
UNITS: dict[str, dict[str, Any]] = {
    "usd":      {"desc": "US dollars, 2 dp, $ prefix",          "plural": False},
    "pct":      {"desc": "percent, signed, 1 dp, % suffix",     "plural": False},
    "pp":       {"desc": "percentage points (a spread/delta)",  "plural": False},
    "atr":      {"desc": "multiples of ATR, 1 dp, 'ATR' suffix", "plural": False},
    "x":        {"desc": "bare multiple, 1 dp, '×' suffix",     "plural": False},
    "rank":     {"desc": "ordinal position, 1 = best",          "plural": False},
    "sessions": {"desc": "count of trading sessions",           "plural": True},
    "days":     {"desc": "count of calendar days",              "plural": True},
    "int":      {"desc": "signed whole number",                 "plural": False},
    "ratio":    {"desc": "unitless ratio, 2 dp",                "plural": False},
    "enum":     {"desc": "categorical; renderer shows `d`",     "plural": False},
    "text":     {"desc": "free string, rendered verbatim",      "plural": False},
}


# ---------------------------------------------------------------------------
# Display maps — kept verbatim-synced with the PWA (§2.1: "the AI never invents a status name")
# ---------------------------------------------------------------------------

# Mirrors MORNING_STATUS_META in `docs/index.html` (~line 5655). An enum field's `d` string
# must equal the label on the chip beside it, or the prose and the chip disagree on screen.
# If a status label changes there, change it here in the same PR — tests/test_evidence_pack.py
# asserts this map covers every status in scripts/pick_status.py.
STATUS_LABELS: dict[str, str] = {
    "triggered":           "Triggered",
    "gapped_through":      "Gapped through",
    "failed_breakout":     "Failed breakout",
    "setting_up":          "Setting up",
    "invalidated":         "Invalidated",
    "no_quote":            "No quote",
    "awaiting_first_read": "Awaiting first read",
    "reclaim":             "Reclaimed",
}

# Mirrors CATEGORY_LABEL in `docs/index.html` (~line 860), plus 'watchlist' which the PWA
# renders through a separate branch rather than that map.
CATEGORY_LABELS: dict[str, str] = {
    "leaders":     "Leaders",
    "emerging":    "Emerging",
    "accel":       "Accel",
    "rs_new_high": "RS New High",
    "all_green":   "All Green",
    "watchlist":   "Watchlist",
}

# Mirrors the reclaim_ref values written by scripts/pick_status.py (STATUS_RECLAIM).
RECLAIM_REF_LABELS: dict[str, str] = {
    "prior_low": "prior swing low",
    "sma50":     "50-day MA",
}

# Statuses the owner acts on. Drives US-P2a's row scope (actionable OR status-changed) and
# the triage pack's `derived.n_actionable`. Mirrors pick_status.ACTIONABLE_STATUSES and
# MORNING_STATUS_META[*].actionable in the PWA — three places, one meaning.
ACTIONABLE_STATUSES: frozenset[str] = frozenset({"triggered", "gapped_through", "reclaim"})


# ---------------------------------------------------------------------------
# Field registry (schema §2.1, §6.1 — unknown id is a hard error)
# ---------------------------------------------------------------------------

def _f(u: str, label: str) -> dict[str, str]:
    return {"u": u, "l": label}


# surface -> field_id -> {"u": unit, "l": human label}.
#
# Registered ids are an API the model is prompted against (§4): renaming one is a breaking
# change, so prefer adding and deprecating. A builder may omit a registered field (the source
# column was blank and the field is genuinely absent, not null) but may never emit an
# unregistered one.
FIELD_REGISTRY: dict[str, dict[str, dict[str, str]]] = {
    "morning_card": {
        # --- the row itself, as stored by collect_morning.py -------------------
        "row.ticker":            _f("text", "Ticker"),
        "row.group":             _f("text", "Industry group"),
        "row.list_category":     _f("enum", "Pick bucket"),
        "row.status":            _f("enum", "Status"),
        "row.trigger":           _f("usd",  "Trigger"),
        "row.stop":              _f("usd",  "Planned stop"),
        "row.price":             _f("usd",  "Price"),
        "row.open":              _f("usd",  "Open"),
        "row.high":              _f("usd",  "Session high"),
        "row.low":               _f("usd",  "Session low"),
        "row.change":            _f("pct",  "Change on day"),
        "row.atr":               _f("usd",  "ATR (14)"),
        "row.atr_from_lod":      _f("atr",  "ATR from low of day"),
        "row.reclaim_ref":       _f("enum", "Reclaim reference"),
        "row.reclaim_ref_value": _f("usd",  "Reclaim reference level"),
        # --- Finviz screener block (SETUP_COLUMNS; only present from 2026-09-01/03) ---
        "row.rsi":               _f("ratio", "RSI (14)"),
        "row.volatility_w":      _f("pct",  "Volatility, 1 week"),
        "row.volatility_m":      _f("pct",  "Volatility, 1 month"),
        "row.rel_volume":        _f("x",    "Relative volume"),
        "row.pct_of_52w_high":   _f("pct",  "From 52-week high"),
        "row.sma20_dist":        _f("pct",  "Distance to 20MA"),
        "row.sma50_dist":        _f("pct",  "Distance to 50MA"),
        # --- prior session (morning -> yesterday's pre_close; pre_close -> today's morning) ---
        "prior.status":          _f("enum", "Status at prior read"),
        "prior.price":           _f("usd",  "Price at prior read"),
        "prior.session":         _f("enum", "Prior read"),
        # --- builder-computed (the deterministic-computation boundary, §2.1) ---
        "derived.sma20_ext_atr":  _f("atr",  "ATR-extension from 20MA"),
        "derived.sma50_ext_atr":  _f("atr",  "ATR-extension from 50MA"),
        "derived.stop_gap_pct":   _f("pct",  "Price to planned stop"),
        "derived.stop_gap_atr":   _f("atr",  "Price to planned stop (ATR)"),
        "derived.trigger_gap_pct": _f("pct", "Price to trigger"),
        "derived.r_at_price":     _f("ratio", "R already used vs plan"),
        "derived.range_atr":      _f("x",    "Session range as ATR multiple"),
        "derived.status_changed": _f("enum", "Status changed since prior read"),
        "derived.price_change_since_prior": _f("pct", "Price change since prior read"),
        # --- the row's industry group, from data/industries/deltas.csv ---------
        "group.rank_month":          _f("rank", "Group 1-month rank"),
        "group.rank_month_delta_5d": _f("int",  "Group rank change, 5 sessions"),
        "group.rs_month":            _f("pp",   "Group RS vs S&P, 1 month"),
        "group.rs_score":            _f("ratio", "Group RS breadth score"),
        "group.rs_new_high":         _f("enum", "Group RS at 20-session high"),
        "group.momentum_score":      _f("ratio", "Group momentum score"),
    },
    "morning_triage": {
        "session.date":            _f("text", "Trading date"),
        "session.name":            _f("enum", "Session"),
        "derived.n_rows":          _f("int",  "Rows in this read"),
        "derived.n_actionable":    _f("int",  "Actionable rows"),
        "derived.n_changed":       _f("int",  "Rows whose status changed"),
        "derived.n_triggered":     _f("int",  "Triggered"),
        "derived.n_gapped_through": _f("int", "Gapped through"),
        "derived.n_reclaim":       _f("int",  "Reclaimed"),
        "derived.n_failed_breakout": _f("int", "Failed breakout"),
        "derived.n_setting_up":    _f("int",  "Setting up"),
        "derived.n_invalidated":   _f("int",  "Invalidated"),
        "derived.n_no_quote":      _f("int",  "No quote"),
        "derived.invalidated_ext_atr_median": _f("atr", "Median 50MA extension of invalidated rows"),
        "derived.actionable_ext_atr_median":  _f("atr", "Median 50MA extension of actionable rows"),
        "derived.n_groups_actionable": _f("int", "Distinct groups with an actionable row"),
        "derived.top_group":       _f("text", "Group with the most actionable rows"),
        "derived.top_group_n":     _f("int",  "Actionable rows in that group"),
    },
}

# Kinds, caps, and the mandatory-catch rule per surface (§2.0, §3).
#
# `cap` is per-kind, first-wins on overflow. `total` caps the whole statement list.
# `requires_catch` implements validation rule 4: a surface whose kind set includes `catch`
# must produce one, or the card is dropped entirely — a thesis with no counter-evidence is
# exactly the one-sided output the proposal §3.0 forbids.
SURFACE_KINDS: dict[str, dict[str, Any]] = {
    "morning_card":   {"kinds": {"read": 1, "catch": 1},                  "total": 2,
                       "requires_catch": True,  "allows_subjects": False},
    "morning_triage": {"kinds": {"triage": 3, "pattern": 1, "catch": 1},  "total": 5,
                       "requires_catch": True,  "allows_subjects": True},
    "picks_card":     {"kinds": {"thesis": 1, "catch": 1},                "total": 2,
                       "requires_catch": True,  "allows_subjects": False},
    "brief_public":   {"kinds": {"regime": 1, "action": 1,
                                 "non_action": 1, "uncertainty": 1},      "total": 4,
                       "requires_catch": False, "allows_subjects": False},
    "position":       {"kinds": {"hold_read": 1, "catch": 1},             "total": 2,
                       "requires_catch": True,  "allows_subjects": False},
}

# Digit-bearing vocabulary the app already uses on screen, stripped from `text` before
# validation rule 3 looks for bare digits (§3.1 rule 3). Without this, "reclaimed the 20MA"
# fails the rule and the most useful sentences get suppressed. Adding an entry is a registry
# change like any field — it ships in pack_schema.json and both runtimes read it from there.
# Ordered longest-first so "S&P 500" is consumed before "500" could be seen as a bare number.
DIGIT_LEXICON: list[str] = [
    "S&P 500", "200MA", "52W High", "52-week high", "52W", "20MA", "50MA",
    "RSI(14)", "RSI 14", "ATR(14)", "10:05", "15:30", "15:50", "R:R",
]


class UnregisteredFieldError(KeyError):
    """A builder tried to emit a field id absent from FIELD_REGISTRY for its surface.

    Hard error by owner decision (schema §6.1): a field that is not in the registry cannot be
    cited legibly in the provenance drawer, and the JS builder would not know about it, so
    silently allowing it would let Tier A and Tier B drift apart unnoticed.
    """


# ---------------------------------------------------------------------------
# Parsing helpers — the Morning store's real dtypes
# ---------------------------------------------------------------------------

_PCT_RE = re.compile(r"^\s*([-+]?[\d.,]+)\s*%\s*$")


def _num(value: Any) -> float | None:
    """Coerce a store value to float, mapping blank/NaN/'-' to None.

    The session stores write missing values as the empty string (data-pipeline.md § Value
    conventions), and pandas reads those back as NaN — both must land as `None` so the field
    renders as `—` rather than the string "nan".
    """
    if value is None:
        return None
    if isinstance(value, str):
        s = value.strip().replace(",", "")
        if s in ("", "-", "nan", "NaN", "None"):
            return None
        try:
            return float(s)
        except ValueError:
            return None
    if isinstance(value, bool):
        return float(value)
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) else f


def _pct(value: Any) -> float | None:
    """Parse a Finviz percent-string ("3.05%", "-7.99%") to a float in percent units.

    Finviz's SMA20/SMA50/52W High screener columns are stored verbatim as scraped strings
    (collect_morning.py SETUP_COLUMNS comment), NOT as prices — SMA20 is the percent distance
    from the *live* price to the 20-day MA. Callers that want the MA's dollar level must
    reconstruct it via `_ma_price()`.
    """
    if isinstance(value, str):
        m = _PCT_RE.match(value)
        if m:
            return _num(m.group(1))
    return _num(value)


def _text(value: Any) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    return None if s in ("", "nan", "NaN", "None") else s


def _ma_price(price: float | None, dist_pct: float | None) -> float | None:
    """Reconstruct a moving average's dollar level from Finviz's percent-above-price column.

    PARITY-CRITICAL: this is the same reconstruction the PWA does in `deriveRiskMetrics()`
    (`docs/index.html` ~line 4603): `ma$ = price / (1 + pct/100)`. If this diverges, the AI
    will say "4.0 ATR" next to a chip that says "3.9" (schema §2.4). Covered by the parity
    test in tests/test_evidence_pack.py.
    """
    if price is None or dist_pct is None:
        return None
    denom = 1.0 + dist_pct / 100.0
    if denom == 0:
        return None
    return price / denom


def _ext_atr(price: float | None, ma_price: float | None, atr: float | None) -> float | None:
    """(price − MA$) / ATR — how many ATRs price sits above the moving average.

    Mirrors `atr_ext_50` / `atr_ext_20` in the PWA's `deriveRiskMetrics()`. Guards `atr > 0`
    exactly as the PWA does, so a zero-ATR row yields None on both sides rather than an
    infinity on one.
    """
    if price is None or ma_price is None or atr is None or atr <= 0:
        return None
    return (price - ma_price) / atr


def _div(numer: float | None, denom: float | None) -> float | None:
    if numer is None or denom is None or denom == 0:
        return None
    return numer / denom


# ---------------------------------------------------------------------------
# Pack assembly
# ---------------------------------------------------------------------------

class _Fields:
    """Accumulates `fields`, enforcing the registry as each id is added.

    Skips ids whose value is absent *and* which the caller marked optional, so a builder can
    offer a field unconditionally and have it simply not appear when the source column was
    never scraped for that date (the SETUP_COLUMNS coverage cliff before 2026-09-03). A field
    present with `v: null` means "we looked and there is no value"; an absent field means "not
    available on this surface for this date" — a distinction the model is prompted on, and the
    reason `notes` exists (§2.3).
    """

    def __init__(self, surface: str) -> None:
        if surface not in FIELD_REGISTRY:
            raise UnregisteredFieldError(f"no field registry for surface {surface!r}")
        self._surface = surface
        self._reg = FIELD_REGISTRY[surface]
        self.out: dict[str, dict[str, Any]] = {}

    def add(self, field_id: str, value: Any, display: Any = None,
            omit_if_none: bool = False) -> None:
        spec = self._reg.get(field_id)
        if spec is None:
            raise UnregisteredFieldError(
                f"field id {field_id!r} is not registered for surface {self._surface!r}. "
                f"Add it to FIELD_REGISTRY and re-run --emit-schema in the same PR "
                f"(schema §6.1: registry drift is a hard error)."
            )
        if value is None and omit_if_none:
            return
        entry: dict[str, Any] = {"v": value, "u": spec["u"], "l": spec["l"]}
        if spec["u"] == "enum":
            # An enum always carries `d`: the renderer shows `d`, the model reasons over `v`
            # (§2.1). `d` is None when `v` is None so the renderer falls through to "—".
            entry["d"] = display
        self.out[field_id] = entry


def _block(label: str, key: str, columns: Sequence[str],
           rows: Iterable[Sequence[Any]]) -> dict[str, Any]:
    """One `context` block (§2.2).

    Rows are positional arrays against a single `columns` list rather than per-row objects —
    roughly a 2x token saving across 115 session rows + 144 industries, which is what makes
    US-P2a's 10-minute budget reachable. `key` names the column a `context:block#row` citation
    is validated against.
    """
    return {"label": label, "key": key, "columns": list(columns),
            "rows": [list(r) for r in rows]}


def _assemble(surface: str, subject: str, as_of: str, session: str | None,
              fields: dict[str, Any], context: dict[str, Any],
              notes: Sequence[str], generated_at: str | None) -> dict[str, Any]:
    pack = {
        "meta": {
            "pack_version": PACK_VERSION,
            "surface": surface,
            "subject": subject,
            "as_of": as_of,
            "session": session,
            "generated_at": generated_at,
            "pack_hash": None,
        },
        "fields": fields,
        "context": context,
        "notes": list(notes),
    }
    pack["meta"]["pack_hash"] = pack_hash(pack)
    return pack


# ---------------------------------------------------------------------------
# Canonical serialization + hashing (schema §2.5)
# ---------------------------------------------------------------------------

def _round_floats(obj: Any) -> Any:
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
        r = round(obj, CANONICAL_FLOAT_DP)
        # Normalise -0.0 to 0.0 so two inputs that differ only in the sign of a rounded-away
        # value hash identically.
        return 0.0 if r == 0 else r
    if isinstance(obj, dict):
        return {k: _round_floats(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_round_floats(v) for v in obj]
    return obj


def canonical(pack: Mapping[str, Any]) -> bytes:
    """Canonical byte serialization of a pack's *content* (§2.5).

    Sorted keys, UTF-8, no whitespace, floats rounded to CANONICAL_FLOAT_DP, `null` for
    missing. `meta` is excluded: `generated_at` changes every run and `pack_hash` is the
    output, so including either would make the hash useless as a "did the input change"
    check and as a Tier B cache key.
    """
    content = {k: pack.get(k) for k in ("fields", "context", "notes")}
    return json.dumps(_round_floats(content), sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def pack_hash(pack: Mapping[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(canonical(pack)).hexdigest()


def prompt_parts(pack: Mapping[str, Any]) -> tuple[str, str]:
    """Split a pack into (stable_prefix, volatile_tail) for prompt assembly (§2.5).

    `context` goes first because it is byte-identical across every card pack in a run — that
    shared prefix is what makes Vertex prompt caching bite across ~40 per-card calls, and
    US-P2a AC4 asserts on it. `fields` + `notes` are the per-subject tail.
    """
    prefix = json.dumps(_round_floats({"context": pack.get("context", {})}),
                        sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    tail = json.dumps(_round_floats({"fields": pack.get("fields", {}),
                                     "notes": pack.get("notes", [])}),
                      sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return prefix, tail


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------

def build_morning_card(row: Mapping[str, Any],
                       prior_row: Mapping[str, Any] | None = None,
                       group_row: Mapping[str, Any] | None = None,
                       context: Mapping[str, Any] | None = None,
                       generated_at: str | None = None) -> dict[str, Any]:
    """Build a `morning_card` pack for one (session, ticker) row (schema §2.4).

    `row` is one record from `data/picks/sessions/{morning,pre_close}.csv`. `prior_row` is the
    same ticker's previous read — for a `morning` row that is the *previous day's* `pre_close`;
    for a `pre_close` row it is the *same day's* `morning` (US-P2a AC2). `group_row` is the
    ticker's industry group from `data/industries/deltas.csv`; it is None for watchlist rows,
    which carry no group at all. `context` is the shared bulk assembled once per run.
    """
    f = _Fields("morning_card")
    notes: list[str] = []

    ticker = _text(row.get("ticker")) or ""
    status = _text(row.get("status"))
    category = _text(row.get("list_category"))

    f.add("row.ticker", ticker)
    f.add("row.group", _text(row.get("group")))
    f.add("row.list_category", category, CATEGORY_LABELS.get(category or ""))
    f.add("row.status", status, STATUS_LABELS.get(status or ""))

    # Lowercase price/atr come from the status engine's quote-block scrape; the capitalised
    # Price/ATR come from the Finviz screener block. `price` and `Price` agree exactly across
    # the store, but `atr` and `ATR` DIVERGE on 224 of 234 rows (they are two different
    # as-of reads). Each derivation below therefore uses the ATR belonging to its own source:
    # stop/trigger geometry uses `atr` (the ATR the engine planned the stop with), and MA
    # extension uses `ATR` (what the PWA's chip uses) — see the parity note on _ext_atr.
    price = _num(row.get("price"))
    atr_engine = _num(row.get("atr"))
    atr_finviz = _num(row.get("ATR"))
    trigger = _num(row.get("trigger"))
    stop = _num(row.get("stop"))

    f.add("row.price", price)
    f.add("row.trigger", trigger)
    f.add("row.stop", stop)
    f.add("row.open", _num(row.get("open")))
    high = _num(row.get("high"))
    low = _num(row.get("low"))
    f.add("row.high", high)
    f.add("row.low", low)
    f.add("row.change", _num(row.get("change")))
    f.add("row.atr", atr_engine)
    f.add("row.atr_from_lod", _num(row.get("atr_from_lod")))

    reclaim_ref = _text(row.get("reclaim_ref"))
    f.add("row.reclaim_ref", reclaim_ref, RECLAIM_REF_LABELS.get(reclaim_ref or ""))
    f.add("row.reclaim_ref_value", _num(row.get("reclaim_ref_value")))

    # --- Finviz screener block. Two independent sub-groups with DIFFERENT coverage-cliff
    # start dates (RSI/Volatility/RelVol/52W from 2026-09-01; SMA20/SMA50/ATR from 2026-09-03
    # — see scripts/CLAUDE.md). During that 2-day gap the RSI group is present while the SMA
    # group is still absent, so each group must gate its own fields independently — a single
    # combined flag would wrongly emit the still-absent SMA fields as null instead of omitting
    # them (and skip the caveat note) merely because the RSI group had already landed.
    rsi_block_present = any(_text(row.get(c)) is not None
                            for c in ("RSI", "Volatility W", "Volatility M", "Rel Volume",
                                      "52W High"))
    sma_block_present = any(_text(row.get(c)) is not None for c in ("SMA20", "SMA50"))

    f.add("row.rsi", _num(row.get("RSI")), omit_if_none=not rsi_block_present)
    f.add("row.volatility_w", _pct(row.get("Volatility W")), omit_if_none=not rsi_block_present)
    f.add("row.volatility_m", _pct(row.get("Volatility M")), omit_if_none=not rsi_block_present)
    f.add("row.rel_volume", _num(row.get("Rel Volume")), omit_if_none=not rsi_block_present)
    f.add("row.pct_of_52w_high", _pct(row.get("52W High")), omit_if_none=not rsi_block_present)

    sma20_dist = _pct(row.get("SMA20"))
    sma50_dist = _pct(row.get("SMA50"))
    f.add("row.sma20_dist", sma20_dist, omit_if_none=not sma_block_present)
    f.add("row.sma50_dist", sma50_dist, omit_if_none=not sma_block_present)

    if not rsi_block_present:
        notes.append(
            "The Finviz setup block (RSI, volatility, relative volume, 52-week high) was "
            "not collected for this date, so those fields are absent from this pack. Do "
            "not infer them."
        )
    if not sma_block_present:
        notes.append(
            "The Finviz setup block (20MA/50MA distance) was not collected for this date, "
            "so those fields and the MA-extension derivations are absent from this pack. "
            "Do not infer them."
        )

    # --- derived (the deterministic-computation boundary, §2.1) ---
    sma20_ext = _ext_atr(price, _ma_price(price, sma20_dist), atr_finviz)
    sma50_ext = _ext_atr(price, _ma_price(price, sma50_dist), atr_finviz)
    f.add("derived.sma20_ext_atr", sma20_ext, omit_if_none=not sma_block_present)
    f.add("derived.sma50_ext_atr", sma50_ext, omit_if_none=not sma_block_present)

    stop_gap = (price - stop) if (price is not None and stop is not None) else None
    f.add("derived.stop_gap_pct", (stop_gap / price * 100.0)
          if (stop_gap is not None and price) else None)
    f.add("derived.stop_gap_atr", _div(stop_gap, atr_engine))
    f.add("derived.trigger_gap_pct",
          ((price - trigger) / trigger * 100.0)
          if (price is not None and trigger) else None)

    # R already used vs plan: how much of the planned trigger→stop risk unit the move has
    # already consumed. 1R = trigger − stop. Negative when price is below the trigger.
    plan_r = (trigger - stop) if (trigger is not None and stop is not None) else None
    f.add("derived.r_at_price",
          _div((price - trigger) if (price is not None and trigger is not None) else None,
               plan_r if (plan_r is not None and plan_r > 0) else None))
    f.add("derived.range_atr",
          _div((high - low) if (high is not None and low is not None) else None, atr_engine))

    # --- prior read ---
    prior_status = _text(prior_row.get("status")) if prior_row else None
    prior_price = _num(prior_row.get("price")) if prior_row else None
    prior_session = _text(prior_row.get("session")) if prior_row else None
    f.add("prior.status", prior_status, STATUS_LABELS.get(prior_status or ""))
    f.add("prior.price", prior_price)
    f.add("prior.session", prior_session,
          {"morning": "10:05 read", "pre_close": "15:30 read"}.get(prior_session or ""))

    if prior_row is None:
        changed: bool | None = None
        notes.append(
            "No prior read exists for this ticker (first appearance, or the prior session's "
            "scrape is missing), so nothing can be said about what changed."
        )
    else:
        changed = (prior_status != status)
    f.add("derived.status_changed", changed,
          {True: "Yes", False: "No"}.get(changed) if changed is not None else None)
    f.add("derived.price_change_since_prior",
          ((price - prior_price) / prior_price * 100.0)
          if (price is not None and prior_price) else None)

    # --- industry group ---
    if group_row is None:
        for fid in ("group.rank_month", "group.rank_month_delta_5d", "group.rs_month",
                    "group.rs_score", "group.rs_new_high", "group.momentum_score"):
            f.add(fid, None)
        if category == "watchlist":
            notes.append(
                "This is a watchlist ticker, not a screened pick: it has no industry group "
                "in the store, so every group.* field is null. Do not attribute group strength."
            )
        else:
            notes.append("No industry-group deltas were found for this ticker's group; "
                         "group.* fields are null.")
    else:
        f.add("group.rank_month", _num(group_row.get("rank_month")))
        f.add("group.rank_month_delta_5d", _num(group_row.get("rank_month_delta_5d")))
        f.add("group.rs_month", _num(group_row.get("rs_month")))
        f.add("group.rs_score", _num(group_row.get("rs_score")))
        rsnh = _num(group_row.get("rs_new_high"))
        f.add("group.rs_new_high", rsnh,
              {1.0: "Yes", 0.0: "No"}.get(rsnh) if rsnh is not None else None)
        f.add("group.momentum_score", _num(group_row.get("momentum_score")))

    # Earnings is genuinely unavailable here: the 27-column Morning store has no earnings
    # column (schema §2.4). It exists on picks_latest.csv and in D1 ticker_quotes, so the
    # picks_card and position surfaces can carry it — this one cannot. The note exists so the
    # model does not silently omit an earnings catch as if it had checked.
    notes.append(
        "Days-to-earnings is not collected in the Morning read, so this pack cannot support "
        "any statement about earnings timing."
    )

    return _assemble("morning_card", ticker, _text(row.get("date")) or "",
                     _text(row.get("session")), f.out, dict(context or {}), notes,
                     generated_at)


def build_morning_triage(session_rows: Sequence[Mapping[str, Any]],
                         prior_rows: Mapping[str, Mapping[str, Any]] | None = None,
                         context: Mapping[str, Any] | None = None,
                         generated_at: str | None = None) -> dict[str, Any]:
    """Build the one `morning_triage` pack for a session (schema §2.0).

    Every cross-row number the triage card will show is computed here, not by the model:
    counts per status, how many changed since the prior read, and the median 50MA extension
    of the invalidated and actionable cohorts (US-P0a AC3). `prior_rows` maps ticker -> that
    ticker's prior read.
    """
    f = _Fields("morning_triage")
    notes: list[str] = []
    prior_rows = prior_rows or {}
    rows = list(session_rows)

    date = _text(rows[0].get("date")) if rows else ""
    session = _text(rows[0].get("session")) if rows else None
    f.add("session.date", date or "")
    f.add("session.name", session,
          {"morning": "10:05 read", "pre_close": "15:30 read"}.get(session or ""))

    counts: dict[str, int] = {s: 0 for s in STATUS_LABELS}
    for r in rows:
        s = _text(r.get("status"))
        if s in counts:
            counts[s] += 1

    f.add("derived.n_rows", len(rows))
    f.add("derived.n_actionable",
          sum(counts[s] for s in ACTIONABLE_STATUSES if s in counts))
    for status, fid in (("triggered", "derived.n_triggered"),
                        ("gapped_through", "derived.n_gapped_through"),
                        ("reclaim", "derived.n_reclaim"),
                        ("failed_breakout", "derived.n_failed_breakout"),
                        ("setting_up", "derived.n_setting_up"),
                        ("invalidated", "derived.n_invalidated"),
                        ("no_quote", "derived.n_no_quote")):
        f.add(fid, counts.get(status, 0))

    n_changed = 0
    n_comparable = 0
    for r in rows:
        prior = prior_rows.get(_text(r.get("ticker")) or "")
        if prior is None:
            continue
        n_comparable += 1
        if _text(prior.get("status")) != _text(r.get("status")):
            n_changed += 1
    f.add("derived.n_changed", n_changed)
    if n_comparable < len(rows):
        notes.append(
            f"{len(rows) - n_comparable} of {len(rows)} rows have no prior read to compare "
            f"against; the changed count covers only the {n_comparable} that do."
        )

    def _median_ext(predicate) -> float | None:
        vals = []
        for r in rows:
            if not predicate(_text(r.get("status"))):
                continue
            price = _num(r.get("price"))
            ext = _ext_atr(price, _ma_price(price, _pct(r.get("SMA50"))), _num(r.get("ATR")))
            if ext is not None:
                vals.append(ext)
        return statistics.median(vals) if vals else None

    inval_med = _median_ext(lambda s: s == "invalidated")
    action_med = _median_ext(lambda s: s in ACTIONABLE_STATUSES)
    f.add("derived.invalidated_ext_atr_median", inval_med)
    f.add("derived.actionable_ext_atr_median", action_med)
    if inval_med is None and counts.get("invalidated", 0) > 0:
        notes.append("50MA extension could not be computed for any invalidated row "
                     "(the Finviz setup block is missing for this date).")

    group_counts: dict[str, int] = {}
    for r in rows:
        if _text(r.get("status")) in ACTIONABLE_STATUSES:
            g = _text(r.get("group"))
            if g:
                group_counts[g] = group_counts.get(g, 0) + 1
    f.add("derived.n_groups_actionable", len(group_counts))
    if group_counts:
        # Ties broken by group name so the pack is deterministic across runs — a tie that
        # resolved by dict order would change pack_hash without any input changing.
        top = sorted(group_counts.items(), key=lambda kv: (-kv[1], kv[0]))[0]
        f.add("derived.top_group", top[0])
        f.add("derived.top_group_n", top[1])
    else:
        f.add("derived.top_group", None)
        f.add("derived.top_group_n", 0)

    return _assemble("morning_triage", "*", date or "", session, f.out,
                     dict(context or {}), notes, generated_at)


# ---------------------------------------------------------------------------
# Validator (schema §3.1)
# ---------------------------------------------------------------------------

# Matches a bare short name ({chg}) AND a dotted field id used directly as a placeholder
# ({row.change}). The AI-NEXT-P0c spike (2026-09-06) found gemini-3.5-flash sometimes writes
# the field id straight into `text` instead of a short name mapped via `slots` — with the old
# letters-only pattern, `{row.status}` didn't match at all (the dot isn't in the character
# class), so it was invisible to both Rule 1 (no placeholder found -> nothing to check against
# `slots`) and Rule 3 (never stripped, but only caught if the field id itself contains a digit)
# — a `{row.status}`-style statement with `slots: {}` sailed through validate() unrejected and
# would have rendered the literal, unsubstituted "{row.status}" text to a real user. Requiring
# a `slots` entry regardless of which spelling was used closes that hole.
_SLOT_RE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_.]*)\}")
_DIGIT_RE = re.compile(r"\d")


class Rejection(dict):
    """One dropped statement or card, shaped for the Tier-2 capture record (§3.2)."""

    def __init__(self, rule: str, detail: str, raw: Any) -> None:
        super().__init__(status="rejected", rule=rule, detail=detail, raw=raw)


def strip_lexicon(text: str) -> str:
    """Remove known digit-bearing app vocabulary before the bare-digit check (§3.1 rule 3)."""
    out = text
    for term in sorted(DIGIT_LEXICON, key=len, reverse=True):
        out = out.replace(term, " ")
    return out


def _resolve_cite(cite: str, pack: Mapping[str, Any]) -> str | None:
    """Return None if the citation resolves, else a human reason why it does not."""
    if not isinstance(cite, str) or not cite:
        return "citation is not a non-empty string"
    if cite.startswith("context:"):
        ref = cite[len("context:"):]
        block_id, _, row_key = ref.partition("#")
        block = (pack.get("context") or {}).get(block_id)
        if block is None:
            return f"context block {block_id!r} is not in the pack"
        if row_key:
            key_col = block.get("key")
            cols = block.get("columns") or []
            if key_col not in cols:
                return f"context block {block_id!r} declares no usable key column"
            idx = cols.index(key_col)
            keys = {str(r[idx]) for r in (block.get("rows") or [])
                    if isinstance(r, (list, tuple)) and len(r) > idx}
            if row_key not in keys:
                return f"{row_key!r} is not a {key_col} in context block {block_id!r}"
        return None
    if cite in (pack.get("fields") or {}):
        return None
    return f"{cite!r} is not a field in this pack"


def validate(response: Mapping[str, Any], pack: Mapping[str, Any]) -> dict[str, Any]:
    """Validate model output against the pack that produced it (schema §3.1).

    Returns `{"statements": [...kept...], "rejections": [Rejection...], "card_dropped": bool,
    "errors": [str...]}`. `errors` is the feedback list appended to the retry prompt (§3.2);
    `card_dropped` is True when the mandatory `catch` did not survive, in which case the
    surface renders exactly as it does today (silence convention) rather than showing a
    half-card.

    All four rules are mechanical — no numeric-comparison heuristics, no fuzzy matching. A
    failure is a bug in our prompt, not a judgement about the model's arithmetic, which is
    what makes failing closed safe here (§3.1).
    """
    surface = (pack.get("meta") or {}).get("surface")
    spec = SURFACE_KINDS.get(surface or "")
    if spec is None:
        raise UnregisteredFieldError(f"unknown surface {surface!r}")

    fields = pack.get("fields") or {}
    notes_blob = " ".join(pack.get("notes") or [])
    kept: list[dict[str, Any]] = []
    rejections: list[Rejection] = []
    errors: list[str] = []
    per_kind: dict[str, int] = {}

    def reject(rule: str, detail: str, raw: Any) -> None:
        rejections.append(Rejection(rule, detail, raw))
        errors.append(detail)

    got_version = str(response.get("contract_version") or "")
    if got_version and got_version.split(".")[0] != CONTRACT_VERSION.split(".")[0]:
        reject("contract_version",
               f"response declares contract_version {got_version!r}; this renderer "
               f"understands {CONTRACT_VERSION!r}", response)
        return {"statements": [], "rejections": rejections, "card_dropped": True,
                "errors": errors}

    for st in response.get("statements") or []:
        raw = st
        if not isinstance(st, Mapping):
            reject("shape", "statement is not an object", raw)
            continue
        kind = st.get("kind")
        text = st.get("text")
        slots = st.get("slots") or {}
        cites = st.get("cites") or []

        # Unknown kinds are dropped rather than rendered somewhere arbitrary (§3).
        if kind not in spec["kinds"]:
            reject("kind", f"kind {kind!r} is not valid for surface {surface!r}; "
                           f"valid kinds are {sorted(spec['kinds'])}", raw)
            continue
        if not isinstance(text, str) or not text.strip():
            reject("shape", f"{kind} statement has empty text", raw)
            continue
        if not isinstance(slots, Mapping):
            reject("shape", f"{kind} statement's slots is not an object", raw)
            continue

        # Rule 1 — slots and text agree, both directions.
        in_text = set(_SLOT_RE.findall(text))
        declared = set(slots)
        if in_text - declared:
            reject("rule1_slot_undeclared",
                   f"{kind}: text uses {sorted(in_text - declared)} with no entry in slots",
                   raw)
            continue
        if declared - in_text:
            reject("rule1_slot_unused",
                   f"{kind}: slots declares {sorted(declared - in_text)} which text never "
                   f"uses", raw)
            continue

        # Rule 2 — every slot resolves in `fields`; a slot may never point into `context`
        # (§2.2: numbers on screen come from fields, and that is the forcing function that
        # gets a useful context value promoted to a real field in a follow-up PR).
        bad_slot = None
        for name, fid in slots.items():
            if isinstance(fid, str) and fid.startswith("context:"):
                bad_slot = (f"{kind}: slot {name!r} points at {fid!r}; slots must reference a "
                            f"field, never context (schema §2.2)")
                break
            if fid not in fields:
                bad_slot = (f"{kind}: slot {name!r} references {fid!r} which is not in the "
                            f"pack. Available fields: {sorted(fields)}")
                break
        if bad_slot:
            reject("rule2_slot_unresolved", bad_slot, raw)
            continue

        # Rule 2 (cont.) — every cite resolves in `fields` or is a valid context reference.
        bad_cite = None
        if not isinstance(cites, (list, tuple)) or not cites:
            bad_cite = f"{kind}: cites is empty; every statement must say what it reasoned from"
        else:
            for c in cites:
                why = _resolve_cite(c, pack)
                if why:
                    bad_cite = f"{kind}: cite {c!r} does not resolve — {why}"
                    break
        if bad_cite:
            reject("rule2_cite_unresolved", bad_cite, raw)
            continue

        # Rule 3 — no bare digits outside slots, after stripping the app's own digit-bearing
        # vocabulary and the slot placeholders themselves.
        probe = strip_lexicon(_SLOT_RE.sub(" ", text))
        if _DIGIT_RE.search(probe):
            reject("rule3_bare_digit",
                   f"{kind}: text contains a literal number outside a slot. Every number must "
                   f"be a {{slot}} bound to a field so the app formats it "
                   f"(offending text: {text!r})", raw)
            continue

        if spec["allows_subjects"]:
            subjects = st.get("subjects") or []
        elif st.get("subjects"):
            reject("subjects", f"{kind}: surface {surface!r} does not accept subjects", raw)
            continue
        else:
            subjects = []

        # Per-kind and total caps, first-wins (§3). Enforced here rather than in the prompt so
        # a chatty model costs us a dropped extra, not a broken layout.
        if per_kind.get(kind, 0) >= spec["kinds"][kind]:
            reject("cap_kind", f"{kind}: more than {spec['kinds'][kind]} statement(s) of this "
                               f"kind; extras are dropped first-wins", raw)
            continue
        if len(kept) >= spec["total"]:
            reject("cap_total", f"surface {surface!r} accepts at most {spec['total']} "
                                f"statements", raw)
            continue

        # Confidence (§3.3). The validator forces `low` when the rubric is provably violated,
        # whatever the model claimed: a statement resting on a null field, on a field a note
        # flags, or on fewer than 2 distinct fields is thin by construction.
        confidence = st.get("confidence")
        if confidence not in ("high", "medium", "low"):
            confidence = "low"
        field_cites = [c for c in cites if not str(c).startswith("context:")]
        thin_reasons: list[str] = []
        for c in field_cites:
            if (fields.get(c) or {}).get("v") is None:
                thin_reasons.append(c)
        if len(set(field_cites)) < 2:
            thin_reasons.append("fewer than two distinct fields")
        if notes_blob and any(
            re.search(r"\b" + re.escape(c.rsplit(".", 1)[-1]) + r"\b", notes_blob)
            for c in field_cites
        ):
            # A field named in a caveat is thin even when it has a value. Word-boundary match,
            # not a raw substring test: a naive `in` check lets unrelated words collide (e.g.
            # the field id "change" is a substring of the routine no-prior-read note's
            # "...what changed.", which forced every row.change citation to `low` confidence).
            thin_reasons.append("cites a field flagged in notes")
        if thin_reasons:
            confidence = "low"

        out = {"kind": kind, "text": text, "slots": dict(slots), "cites": list(cites),
               "confidence": confidence}
        if thin_reasons:
            out["thin"] = sorted(set(thin_reasons))
        if subjects:
            out["subjects"] = list(subjects)
        kept.append(out)
        per_kind[kind] = per_kind.get(kind, 0) + 1

    # Rule 4 — the mandatory catch. Its absence drops the whole card, not just the statement:
    # a read or thesis with no counter-evidence is precisely the one-sided output the design
    # forbids (§3.2).
    card_dropped = False
    if spec["requires_catch"] and per_kind.get("catch", 0) == 0:
        card_dropped = True
        errors.append(f"surface {surface!r} requires exactly one non-empty `catch` statement "
                      f"(the strongest reason not to act); none survived validation")

    return {"statements": [] if card_dropped else kept,
            "rejections": rejections, "card_dropped": card_dropped, "errors": errors}


def validate_with_retry(response: Mapping[str, Any], pack: Mapping[str, Any],
                        retry) -> dict[str, Any]:
    """Validate, and on any failure call `retry(errors)` once for a second response (§3.2).

    `retry` is a callable taking the validator's error list and returning a fresh response
    mapping — in production the same model call with the errors appended to the prompt; in
    tests a fake. There is no second retry: two failures against a mechanical contract means
    the prompt is wrong, and burning more quota will not fix it.
    """
    first = validate(response, pack)
    if not first["rejections"] and not first["card_dropped"]:
        return {**first, "attempts": 1}
    second_response = retry(first["errors"])
    if second_response is None:
        return {**first, "attempts": 1}
    second = validate(second_response, pack)
    # Keep whichever attempt actually produced a renderable card; on a tie prefer the retry,
    # since it saw the error list. A retry that also fails still returns its own rejections so
    # the capture records what the model did the second time, not the first.
    if first["card_dropped"] and not second["card_dropped"]:
        return {**second, "attempts": 2}
    if second["card_dropped"] and not first["card_dropped"]:
        return {**first, "rejections": first["rejections"] + second["rejections"],
                "attempts": 2}
    return {**second, "rejections": first["rejections"] + second["rejections"],
            "attempts": 2}


# ---------------------------------------------------------------------------
# Registry emission (schema §5 — committed == generated, asserted by a test)
# ---------------------------------------------------------------------------

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "data" / "ai" / "pack_schema.json"


def schema_document() -> dict[str, Any]:
    """The shared registry, as committed to data/ai/pack_schema.json.

    Read by the Tier B builder (`worker-positions/src/evidencePack.js`) and the PWA renderer
    so there is exactly one definition of field ids, units, kinds, and the digit lexicon
    across three runtimes.
    """
    return {
        "pack_version": PACK_VERSION,
        "contract_version": CONTRACT_VERSION,
        "canonical_float_dp": CANONICAL_FLOAT_DP,
        "units": UNITS,
        "digit_lexicon": DIGIT_LEXICON,
        "surfaces": {
            surface: {
                "kinds": spec["kinds"],
                "total": spec["total"],
                "requires_catch": spec["requires_catch"],
                "allows_subjects": spec["allows_subjects"],
                "fields": FIELD_REGISTRY.get(surface, {}),
            }
            for surface, spec in SURFACE_KINDS.items()
        },
        "labels": {
            "status": STATUS_LABELS,
            "list_category": CATEGORY_LABELS,
            "reclaim_ref": RECLAIM_REF_LABELS,
        },
        "actionable_statuses": sorted(ACTIONABLE_STATUSES),
    }


def render_schema() -> str:
    return json.dumps(schema_document(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--emit-schema", action="store_true",
                    help="write data/ai/pack_schema.json from the in-code registry")
    ap.add_argument("--check-schema", action="store_true",
                    help="exit non-zero if the committed schema differs from the generated one")
    args = ap.parse_args(argv)

    if args.emit_schema:
        SCHEMA_PATH.parent.mkdir(parents=True, exist_ok=True)
        SCHEMA_PATH.write_text(render_schema(), encoding="utf-8")
        print(f"wrote {SCHEMA_PATH}")
        return 0
    if args.check_schema:
        if not SCHEMA_PATH.exists():
            print(f"{SCHEMA_PATH} is missing; run --emit-schema")
            return 1
        if SCHEMA_PATH.read_text(encoding="utf-8") != render_schema():
            print(f"{SCHEMA_PATH} is stale; run --emit-schema and commit the result")
            return 1
        print("schema is current")
        return 0
    ap.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

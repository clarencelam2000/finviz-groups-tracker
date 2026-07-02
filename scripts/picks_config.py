"""
picks_config.py — single source of truth for the stock-picks pipeline schema
and selector constants.

Imported by `collect_picks.py`, the picks tests, and (later) `eval_picks.py`.
Mirrors the `delta_config.py` pattern: schema + tunable constants live here so a
change is made in exactly one place and every consumer derives from it.

ALL constants below are configurable parameters and are triple-documented per
house rules (in-code here, README § Configurable parameters, CLAUDE.md § Picks
pipeline). If you add or change one, update all three AND bump SELECTOR_VERSION
+ prepend a `data/picks/selector_versions.json` entry if it affects selection
(see ADR-007 § selector_version scheme).
"""

import json
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
PICKS_DIR = BASE_DIR / "data" / "picks"
CONFIG_PATH = PICKS_DIR / "screener_config.json"
PICKS_CSV = PICKS_DIR / "picks.csv"
PICKS_LATEST_CSV = PICKS_DIR / "picks_latest.csv"
SLUGS_PATH = PICKS_DIR / "finviz_industry_slugs.csv"
SELECTOR_VERSIONS_PATH = PICKS_DIR / "selector_versions.json"
GOLDEN_HEADER_PATH = BASE_DIR / "tests" / "fixtures" / "probe_header_84col.txt"

# ---------------------------------------------------------------------------
# Selector version (ADR-007)
# ---------------------------------------------------------------------------

# SELECTOR_VERSION — monotonic, immutable-once-published string stamped onto
# every picks.csv row. AWS-task-definition-revision style: integers behind a "v"
# prefix, never reused. Bump (v1 -> v2 -> ...) on ANY change to selection logic
# OR to any constant below that feeds selection, AND prepend a matching entry to
# data/picks/selector_versions.json (enforced by tests).
# CAVEAT (ADR-007): the registry captures *constants*, not arbitrary code. If the
# ranking math in select_groups() changes without a version bump, the stamp lies.
# Mitigation is this bump rule + code review, not a technical lock.
#
# v1 -> v2 (2026-07-02, ADR-007 amendment): a group already selected by a
# higher-priority bucket no longer consumes one of a lower-priority bucket's N
# slots just by ranking in that bucket's natural top-N — it is still tagged
# there (attribution preserved), but the bucket backfills past rank N with the
# next NEW candidate so its N slots still yield N distinct groups when the
# qualifying pool is deep enough. See select_groups()'s add_bucket_with_backfill.
SELECTOR_VERSION = "v2"

# ---------------------------------------------------------------------------
# Daily cap + per-bucket slot split (ADR-007, VP-locked 2026-06-24/25)
# ---------------------------------------------------------------------------

# DAILY_GROUP_CAP — max UNIQUE groups scraped per day (conviction over breadth;
# also bounds ToS exposure). A group qualifying in multiple buckets counts once
# toward this cap but still gets one tagged row per bucket in picks.csv.
DAILY_GROUP_CAP = 20

# Leaders bucket is split into a stable core + a responsive freshness fill.
# LEADER_SS_SLOTS — core slots ranked by sustained_strength (sum of
#   rank_month+rank_quarter+rank_half, lower = stronger mid-timeframe leader).
# LEADER_MC_SLOTS — freshness slots ranked by momentum_confirmed desc among
#   groups NOT already in the core (catches fresh movers the stable core misses).
LEADER_SS_SLOTS = 8
LEADER_MC_SLOTS = 2

# Smaller, earlier/riskier buckets get small allocations (ADR-007 table).
EMERGING_SLOTS = 4
ACCEL_SLOTS = 3
RS_NH_SLOTS = 3

# ---------------------------------------------------------------------------
# Selector gate thresholds (ADR-007)
# ---------------------------------------------------------------------------

# ANTIFLASH_PCTILE — the anti-flash floor for accel/rs_new_high, expressed as a
# cross-sectional percentile by momentum_score (NOT an absolute cutoff — invariant
# to PERF_RANK_METRICS rescaling). 0.40 = a group must be in today's top 40% by
# momentum_score to qualify. Conservative start; may loosen toward 0.50 after 30+
# days if buckets chronically yield too few groups.
ANTIFLASH_PCTILE = 0.40

# EMERGING_REGIME_FLOOR — emerging primary gate on regime_short_long (mirrors the
# PWA REGIME_THRESHOLD = 0.15; kept as the selector's own named constant so the
# selector is config-free and self-describing per ADR-007).
EMERGING_REGIME_FLOOR = 0.15

# ACCEL_THRESHOLD — accel primary gate on momentum_accel (mirrors the PWA
# ACCEL_STRONG = 0.08).
ACCEL_THRESHOLD = 0.08

# rs_score floors per bucket (anti-flash absolute-strength gate vs SPY). NaN when
# benchmark/snapshots.csv lacks the date → bucket yields 0 groups (correct).
EMERGING_RS_FLOOR = 0.5   # emerging: must already be net-positive vs SPY
ACCEL_RS_FLOOR = 0.5      # accel: reject bottom-of-pack dead-cat flashes
RS_NH_RS_FLOOR = 0.6      # rs_new_high: IBD "true leadership", not a low-base pop

# ---------------------------------------------------------------------------
# Scrape guardrails (ADR-008 / D11)
# ---------------------------------------------------------------------------

# PAGE_SIZE — rows Finviz returns per screener page (v=151). Used to walk &r=.
PAGE_SIZE = 20

# PAGE_CAP — per-group hard page cap. At 20 rows/page, 2 pages = 40 names.
# Lowered from 15 -> 2 (2026-07-02): historical picks.csv data showed only
# Biotechnology (a structurally oversized Finviz industry, ~100 names/day)
# ever exceeded 40 names — every other group observed stays under 35. The
# wide screener sorts -marketcap desc (screener_config.json), so capping at
# 2 pages keeps the biggest/most-liquid names in an oversized group and drops
# the long tail, trading a few small/mid-cap names for scrape-budget headroom.
PAGE_CAP = 2

# GLOBAL_FETCH_CAP — hard global daily page cap (VP-set 2026-06-25). The job
# scrapes in priority order (leaders first) and STOPS at this many pages, so the
# worst case is bounded regardless of how many names each group has. Revisit once
# live data shows real daily page demand.
GLOBAL_FETCH_CAP = 50

# PAGE_DELAY_S — polite inter-fetch delay (seconds). Set PICKS_PAGE_DELAY=0 in env
# to skip during debugging.
import os as _os
PAGE_DELAY_S = float(_os.environ.get("PICKS_PAGE_DELAY", "3"))

# ---------------------------------------------------------------------------
# picks.csv schema
# ---------------------------------------------------------------------------

# Leading identity columns (lowercase `ticker` is the dedup-key copy of the
# Finviz "Ticker" column; both are kept intentionally — the leading column is the
# stable join key, the 84-col block is the verbatim scrape).
PICKS_LEAD_COLS = ["date", "list_category", "selector_version", "group", "ticker"]

# grp_* group-metric snapshot columns (19) — frozen at selection time so Phase-4
# attribution never re-derives from deltas.csv (ADR-007/008 § grp_* spec).
# Renaming/removing any of these is effectively one-way once data flows; ADDING
# one later is a two-way-door superset migration. Order is sticky.
PICKS_GRP_COLS = [
    "grp_rank_basis",            # sustained_strength | freshness_fill | <category>
    "grp_category_rank",         # within-bucket rank among qualifying candidates
    "grp_sum_mid_rank",          # rank_month + rank_quarter + rank_half
    "grp_rank_month",
    "grp_rank_quarter",
    "grp_rank_half",
    "grp_momentum_confirmed",
    "grp_momentum_score",
    "grp_momentum_score_pctile",  # computed cross-sectionally; the anti-flash floor value
    "grp_momentum_accel",
    "grp_momentum_weighted_mid",  # rejected-alt, stored for Phase-4 head-to-head
    "grp_rank_agreement",         # rejected-alt, stored for Phase-4 head-to-head
    "grp_regime_short_long",
    "grp_rs_score",
    "grp_rs_agreement",
    "grp_rs_confirmed",           # rejected leaders metric, stored for Phase-4
    "grp_rs_accel",
    "grp_rs_new_high",
    "grp_rs_slope",
]

# METRICS_COLS — 5 backend-derived columns appended AFTER grp_* (Phase 3a, ADR-008).
# Deterministic transforms of already-stored Finviz columns; computed at write time in
# collect_picks.py. No selector_version bump needed. Adding one later is a two-way-door
# superset migration (ensure_picks_csv pattern). Renaming/removing is one-way once data flows.
# Triple-documented: here, README § Configurable parameters, CLAUDE.md § Picks pipeline.
METRICS_COLS = [
    "atr_ext_50",      # (price − sma50_price) / ATR; ATR multiples from 50MA (CEO "rubber-band")
    "risk_20ma_pct",   # (price − sma20_price) / price; fraction at risk to 20MA stop
    "risk_50ma_pct",   # (price − sma50_price) / price; fraction at risk to 50MA stop
    "range_atr",       # (High − Low) / ATR; day-tightness proxy (C1)
    "stage2",          # 1 if price>50MA AND 50MA>200MA; 0 otherwise; NaN if SMAs absent
]


def load_config() -> dict:
    return json.loads(CONFIG_PATH.read_text())


def finviz_cols(config: dict = None) -> list:
    """Ordered 84 Finviz column labels (from screener_config.json `wide.columns`)."""
    config = config or load_config()
    return [c["label"] for c in config["wide"]["columns"]]


def picks_columns(config: dict = None) -> list:
    """Full ordered picks.csv header: lead (5) + Finviz (84) + grp_* (19) + metrics (5) = 113."""
    return PICKS_LEAD_COLS + finviz_cols(config) + PICKS_GRP_COLS + METRICS_COLS

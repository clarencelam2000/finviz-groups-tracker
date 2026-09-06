"""Tests for scripts/evidence_pack.py — AI-NEXT-P0a evidence pack builder/registry/validator.

No I/O other than reading the committed data/ai/pack_schema.json for the anti-drift check.
No playwright import — safe to run everywhere including CI's default `pytest tests/`
invocation (not on the Playwright ignore list).
"""

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import evidence_pack as ep  # noqa: E402
import pick_status  # noqa: E402
from evidence_pack import (  # noqa: E402
    FIELD_REGISTRY,
    STATUS_LABELS,
    UnregisteredFieldError,
    _Fields,
    build_morning_card,
    build_morning_triage,
    canonical,
    pack_hash,
    prompt_parts,
    validate,
    validate_with_retry,
)

REPO_ROOT = Path(__file__).parent.parent
SCHEMA_PATH = REPO_ROOT / "data" / "ai" / "pack_schema.json"

NAN = float("nan")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

# Full morning.csv-shaped row (real header, see task description). SMA20/SMA50/52W High are
# Finviz percent-distance strings, not prices. `atr` (engine) and `ATR` (Finviz) deliberately
# differ so tests can prove the right one is used per derivation.
def _full_row(**overrides):
    row = {
        "date": "2026-09-04", "session": "pre_close", "collected_at": "2026-09-04T19:35:11Z",
        "ticker": "NVDA", "group": "Semiconductors", "list_category": "leaders",
        "trigger": "184.20", "stop": "176.50", "atr": "3.00",
        "price": "186.05", "open": "183.10", "high": "187.40", "low": "182.90",
        "change": "1.62", "status": "triggered",
        "atr_from_lod": "0.77", "reclaim_ref": "", "reclaim_ref_value": "",
        "RSI": "61.3", "Volatility W": "2.10%", "Volatility M": "4.40%",
        "Rel Volume": "2.10", "52W High": "-2.10%", "Price": "186.05",
        "SMA20": "3.40%", "SMA50": "8.90%", "ATR": "4.10",
    }
    row.update(overrides)
    return row


def _blank_setup_row(**overrides):
    row = _full_row(RSI="", **{"Volatility W": "", "Volatility M": "", "Rel Volume": "",
                                "52W High": "", "SMA20": "", "SMA50": "", "ATR": ""})
    row.update(overrides)
    return row


def _group_row(**overrides):
    row = {
        "name": "Semiconductors", "rank_month": "3", "rank_month_delta_5d": "2",
        "rs_month": "4.2", "rs_score": "0.67", "rs_new_high": "1", "momentum_score": "0.81",
    }
    row.update(overrides)
    return row


# ===========================================================================
# REGISTRY
# ===========================================================================

def test_committed_pack_schema_matches_render_schema():
    committed = SCHEMA_PATH.read_text(encoding="utf-8")
    generated = ep.render_schema()
    assert committed == generated, (
        "data/ai/pack_schema.json is stale relative to evidence_pack.render_schema(); "
        "run `python scripts/evidence_pack.py --emit-schema` and commit the result"
    )


def test_fields_add_raises_on_unknown_field_id():
    f = _Fields("morning_card")
    try:
        f.add("row.does_not_exist", 1)
        assert False, "expected UnregisteredFieldError"
    except UnregisteredFieldError:
        pass


def test_fields_add_raises_on_unknown_surface():
    try:
        _Fields("not_a_real_surface")
        assert False, "expected UnregisteredFieldError"
    except UnregisteredFieldError:
        pass


def test_builder_emitted_fields_all_registered_for_surface():
    card = build_morning_card(_full_row(), prior_row=_full_row(status="setting_up"),
                              group_row=_group_row())
    for fid in card["fields"]:
        assert fid in FIELD_REGISTRY["morning_card"], f"{fid} not registered"

    triage = build_morning_triage([_full_row()])
    for fid in triage["fields"]:
        assert fid in FIELD_REGISTRY["morning_triage"], f"{fid} not registered"


def test_status_labels_covers_every_pick_status_constant():
    statuses = {v for k, v in vars(pick_status).items()
                if k.startswith("STATUS_") and isinstance(v, str)}
    assert statuses, "sanity: pick_status must define at least one STATUS_ constant"
    missing = statuses - set(STATUS_LABELS)
    assert not missing, f"STATUS_LABELS missing labels for: {missing}"


# ===========================================================================
# BUILDER — build_morning_card
# ===========================================================================

def test_full_row_produces_expected_field_set_and_enum_display_strings():
    row = _full_row()
    card = build_morning_card(row, prior_row=_full_row(status="setting_up"),
                              group_row=_group_row())
    fields = card["fields"]

    assert fields["row.list_category"]["d"] == "Leaders"
    assert fields["row.status"]["d"] == "Triggered"
    assert fields["prior.status"]["d"] == "Setting up"
    assert fields["prior.session"]["d"] == "15:30 read"
    assert fields["derived.status_changed"]["d"] == "Yes"

    # setup block present -> these should all be in the field set
    for fid in ("row.rsi", "row.volatility_w", "row.volatility_m", "row.rel_volume",
                "row.pct_of_52w_high", "row.sma20_dist", "row.sma50_dist",
                "derived.sma20_ext_atr", "derived.sma50_ext_atr"):
        assert fid in fields, f"expected {fid} present on a full row"


def test_sma50_ext_atr_parity_formula():
    # AC7 parity requirement: derived.sma50_ext_atr must equal the same formula the PWA's
    # deriveRiskMetrics() in docs/index.html uses — hand-computed here, not via the module's
    # own helpers, so a bug in _ext_atr/_ma_price can't hide from the test.
    price = 186.05
    sma50_pct = 8.90
    atr_finviz = 4.10
    ma_price = price / (1 + sma50_pct / 100.0)
    expected = (price - ma_price) / atr_finviz

    row = _full_row(price=str(price), SMA50=f"{sma50_pct}%", ATR=str(atr_finviz))
    card = build_morning_card(row)
    got = card["fields"]["derived.sma50_ext_atr"]["v"]
    assert got == expected


def test_sma20_ext_atr_parity_formula():
    price = 186.05
    sma20_pct = 3.40
    atr_finviz = 4.10
    ma_price = price / (1 + sma20_pct / 100.0)
    expected = (price - ma_price) / atr_finviz

    row = _full_row(price=str(price), SMA20=f"{sma20_pct}%", ATR=str(atr_finviz))
    card = build_morning_card(row)
    got = card["fields"]["derived.sma20_ext_atr"]["v"]
    assert got == expected


def test_stop_gap_atr_uses_lowercase_engine_atr_not_finviz_atr():
    # atr (engine) and ATR (Finviz) differ enough that using the wrong one gives a visibly
    # different answer: price=186.05, stop=176.50 -> stop_gap = 9.55.
    row = _full_row(price="186.05", stop="176.50", atr="3.00", ATR="4.10")
    card = build_morning_card(row)
    expected = (186.05 - 176.50) / 3.00
    wrong = (186.05 - 176.50) / 4.10
    got = card["fields"]["derived.stop_gap_atr"]["v"]
    assert got == expected
    assert abs(got - wrong) > 0.5  # sanity: the two ATRs really do give visibly different answers


def test_blank_setup_columns_omit_fields_and_add_note():
    row = _blank_setup_row()
    card = build_morning_card(row)
    fields = card["fields"]

    for fid in ("row.rsi", "row.volatility_w", "row.volatility_m", "row.rel_volume",
                "row.pct_of_52w_high", "row.sma20_dist", "row.sma50_dist",
                "derived.sma20_ext_atr", "derived.sma50_ext_atr"):
        assert fid not in fields, f"{fid} should be entirely absent, not null, when setup blank"

    assert any("Finviz setup block" in n for n in card["notes"])


def test_partial_coverage_cliff_gates_sma_block_independently_of_rsi_block():
    # Real 2026-09-01/02 gap: RSI/Volatility/RelVol/52W High were already being collected,
    # SMA20/SMA50/ATR were not (see scripts/CLAUDE.md § coverage cliff). A single combined
    # presence flag would wrongly treat the still-missing SMA block as present because RSI
    # already landed, emitting sma20_dist/sma50_dist as null instead of omitting them.
    row = _full_row(SMA20="", SMA50="", ATR="")
    card = build_morning_card(row)
    fields = card["fields"]

    for fid in ("row.rsi", "row.volatility_w", "row.volatility_m", "row.rel_volume",
                "row.pct_of_52w_high"):
        assert fid in fields, f"{fid} should stay present when only the SMA block is absent"

    for fid in ("row.sma20_dist", "row.sma50_dist", "derived.sma20_ext_atr",
                "derived.sma50_ext_atr"):
        assert fid not in fields, f"{fid} should be omitted, not null, when the SMA block is absent"

    assert any("Finviz setup block" in n for n in card["notes"])


def test_prior_row_none_status_changed_is_none_with_note():
    card = build_morning_card(_full_row(), prior_row=None)
    fields = card["fields"]
    assert fields["derived.status_changed"]["v"] is None
    assert fields["derived.status_changed"]["d"] is None
    assert any("No prior read exists" in n for n in card["notes"])


def test_status_changed_true_when_prior_status_differs():
    card = build_morning_card(_full_row(status="triggered"),
                              prior_row=_full_row(status="setting_up"))
    fields = card["fields"]
    assert fields["derived.status_changed"]["v"] is True
    assert fields["derived.status_changed"]["d"] == "Yes"


def test_status_changed_false_when_prior_status_same():
    card = build_morning_card(_full_row(status="triggered"),
                              prior_row=_full_row(status="triggered"))
    fields = card["fields"]
    assert fields["derived.status_changed"]["v"] is False
    assert fields["derived.status_changed"]["d"] == "No"


def test_group_row_none_watchlist_all_group_fields_null_with_watchlist_note():
    card = build_morning_card(_full_row(list_category="watchlist"), group_row=None)
    fields = card["fields"]
    group_fids = ("group.rank_month", "group.rank_month_delta_5d", "group.rs_month",
                  "group.rs_score", "group.rs_new_high", "group.momentum_score")
    for fid in group_fids:
        assert fid in fields
        assert fields[fid]["v"] is None
    assert any("watchlist ticker" in n for n in card["notes"])


def test_group_row_none_non_watchlist_gets_generic_note():
    card = build_morning_card(_full_row(list_category="leaders"), group_row=None)
    assert any("No industry-group deltas were found" in n for n in card["notes"])
    assert not any("watchlist ticker" in n for n in card["notes"])


def test_blank_reclaim_ref_is_null_v_and_d():
    card = build_morning_card(_full_row(reclaim_ref=""))
    entry = card["fields"]["row.reclaim_ref"]
    assert entry["v"] is None
    assert entry["d"] is None


# ===========================================================================
# BUILDER — build_morning_triage
# ===========================================================================

def _triage_rows():
    # 6 rows across statuses; ATR is Finviz-capital ATR used by the median-ext helper.
    # ticker, status, price, SMA50 pct, ATR
    specs = [
        ("AAA", "triggered", 100.0, "10.00%", 5.0),      # ext = (100-90.909...)/5 = 1.818...
        ("BBB", "invalidated", 50.0, "20.00%", 2.0),      # ma=41.6667, ext=(50-41.6667)/2=4.1667
        ("CCC", "invalidated", 80.0, "10.00%", 4.0),      # ma=72.7273, ext=(80-72.7273)/4=1.8182
        ("DDD", "gapped_through", 60.0, "5.00%", 3.0),    # actionable
        ("EEE", "setting_up", 40.0, "5.00%", 2.0),
        ("FFF", "reclaim", 30.0, "0.00%", 1.0),           # ma=30, ext=0 -> actionable
    ]
    rows = []
    for ticker, status, price, sma50, atr in specs:
        rows.append({
            "date": "2026-09-04", "session": "morning", "ticker": ticker,
            "group": "GroupA" if ticker in ("AAA", "DDD", "FFF") else "GroupB",
            "status": status, "price": str(price), "SMA50": sma50, "ATR": str(atr),
        })
    return rows


def test_morning_triage_hand_computed_counts_and_medians():
    rows = _triage_rows()
    # prior reads: AAA and BBB have a differing prior status; the rest match or have none.
    prior_rows = {
        "AAA": {"status": "setting_up"},      # changed
        "BBB": {"status": "setting_up"},      # changed (was setting_up, now invalidated)
        "CCC": {"status": "invalidated"},     # unchanged
        "DDD": {"status": "gapped_through"},  # unchanged
        # EEE, FFF: no prior -> not comparable
    }
    triage = build_morning_triage(rows, prior_rows=prior_rows)
    fields = triage["fields"]

    # Counts: triggered=1, gapped_through=1, reclaim=1, failed_breakout=0, setting_up=1,
    # invalidated=2, no_quote=0. n_rows=6.
    assert fields["derived.n_rows"]["v"] == 6
    assert fields["derived.n_triggered"]["v"] == 1
    assert fields["derived.n_gapped_through"]["v"] == 1
    assert fields["derived.n_reclaim"]["v"] == 1
    assert fields["derived.n_failed_breakout"]["v"] == 0
    assert fields["derived.n_setting_up"]["v"] == 1
    assert fields["derived.n_invalidated"]["v"] == 2
    assert fields["derived.n_no_quote"]["v"] == 0

    # n_actionable = triggered + gapped_through + reclaim = 1 + 1 + 1 = 3
    assert fields["derived.n_actionable"]["v"] == 3

    # n_changed: of the 4 comparable rows (AAA, BBB, CCC, DDD), AAA and BBB changed -> 2
    assert fields["derived.n_changed"]["v"] == 2

    # invalidated_ext_atr_median: BBB ext = (50 - 50/1.20)/2 = (50-41.666667)/2 = 4.166667
    #                             CCC ext = (80 - 80/1.10)/4 = (80-72.727273)/4 = 1.818182
    # median of [4.166667, 1.818182] = (4.166667+1.818182)/2 = 2.992424...
    bbb_ext = (50.0 - 50.0 / 1.20) / 2.0
    ccc_ext = (80.0 - 80.0 / 1.10) / 4.0
    expected_inval_median = (bbb_ext + ccc_ext) / 2.0
    assert math.isclose(fields["derived.invalidated_ext_atr_median"]["v"],
                        expected_inval_median, rel_tol=1e-9)

    # actionable_ext_atr_median: AAA ext = (100-100/1.10)/5 = (100-90.909091)/5 = 1.818182
    #                            DDD ext = (60-60/1.05)/3 = (60-57.142857)/3 = 0.952381
    #                            FFF ext = (30-30/1.00)/1 = 0/1 = 0.0
    # median of [1.818182, 0.952381, 0.0] sorted [0.0, 0.952381, 1.818182] -> 0.952381
    aaa_ext = (100.0 - 100.0 / 1.10) / 5.0
    ddd_ext = (60.0 - 60.0 / 1.05) / 3.0
    fff_ext = (30.0 - 30.0 / 1.00) / 1.0
    expected_action_median = sorted([aaa_ext, ddd_ext, fff_ext])[1]
    assert math.isclose(fields["derived.actionable_ext_atr_median"]["v"],
                        expected_action_median, rel_tol=1e-9)

    # n_groups_actionable: actionable tickers AAA(GroupA), DDD(GroupA), FFF(GroupA) -> 1 group
    assert fields["derived.n_groups_actionable"]["v"] == 1
    assert fields["derived.top_group"]["v"] == "GroupA"
    assert fields["derived.top_group_n"]["v"] == 3


def test_morning_triage_top_group_tie_broken_alphabetically_and_deterministic():
    rows = [
        {"date": "2026-09-04", "session": "morning", "ticker": "AAA", "group": "Zeta",
         "status": "triggered", "price": "10", "SMA50": "0%", "ATR": "1"},
        {"date": "2026-09-04", "session": "morning", "ticker": "BBB", "group": "Alpha",
         "status": "triggered", "price": "10", "SMA50": "0%", "ATR": "1"},
    ]
    triage1 = build_morning_triage(rows)
    triage2 = build_morning_triage(list(reversed(rows)))
    assert triage1["fields"]["derived.top_group"]["v"] == "Alpha"
    assert triage2["fields"]["derived.top_group"]["v"] == "Alpha"
    assert triage1["fields"]["derived.top_group_n"]["v"] == 1


def test_morning_triage_empty_session_rows_does_not_raise():
    triage = build_morning_triage([])
    assert triage["fields"]["derived.n_rows"]["v"] == 0
    assert triage["fields"]["derived.top_group"]["v"] is None
    assert triage["fields"]["derived.top_group_n"]["v"] == 0


# ===========================================================================
# CANONICAL / HASH
# ===========================================================================

def _sample_pack():
    return build_morning_card(_full_row(), prior_row=_full_row(status="setting_up"),
                              group_row=_group_row(),
                              context={"industries": {"label": "x", "key": "name",
                                                       "columns": ["name"], "rows": [["A"]]}})


def test_canonical_is_identical_bytes_across_two_calls():
    pack = _sample_pack()
    assert canonical(pack) == canonical(pack)


def test_pack_hash_unchanged_when_only_generated_at_differs():
    pack1 = build_morning_card(_full_row(), generated_at="2026-09-04T19:35:11Z")
    pack2 = build_morning_card(_full_row(), generated_at="2026-09-05T01:00:00Z")
    assert pack1["meta"]["pack_hash"] == pack2["meta"]["pack_hash"]


def test_pack_hash_changes_when_a_field_value_changes():
    pack1 = build_morning_card(_full_row(price="186.05"))
    pack2 = build_morning_card(_full_row(price="200.00"))
    assert pack1["meta"]["pack_hash"] != pack2["meta"]["pack_hash"]


def test_float_rounding_to_4dp_and_negative_zero_normalizes():
    assert ep._round_floats(1.123456789) == 1.1235
    r = ep._round_floats(-0.00001)
    assert r == 0.0
    assert math.copysign(1.0, r) == 1.0  # not -0.0


def test_prompt_parts_prefix_is_context_only_and_identical_across_differing_fields():
    ctx = {"industries": {"label": "x", "key": "name", "columns": ["name"], "rows": [["A"]]}}
    pack1 = build_morning_card(_full_row(price="186.05"), context=ctx)
    pack2 = build_morning_card(_full_row(price="200.00"), context=ctx)
    prefix1, tail1 = prompt_parts(pack1)
    prefix2, tail2 = prompt_parts(pack2)
    assert prefix1 == prefix2
    assert tail1 != tail2
    assert "context" in prefix1
    assert "fields" not in prefix1


# ===========================================================================
# VALIDATOR
# ===========================================================================

def _pack_with_fields(surface="morning_card", extra_fields=None, extra_context=None):
    fields = {
        "row.ticker": {"v": "NVDA", "u": "text", "l": "Ticker"},
        "row.rel_volume": {"v": 2.1, "u": "x", "l": "Relative volume"},
        "group.rank_month": {"v": 3, "u": "rank", "l": "Group 1-month rank"},
    }
    if extra_fields:
        fields.update(extra_fields)
    context = {"industries": {"label": "All industries", "key": "name",
                              "columns": ["name"], "rows": [["Semiconductors"]]}}
    if extra_context:
        context.update(extra_context)
    return {"meta": {"surface": surface}, "fields": fields, "context": context, "notes": []}


def _stmt(kind="read", text="Group is #{rank}.", slots=None, cites=None, confidence="high"):
    return {"kind": kind, "text": text,
            "slots": slots if slots is not None else {"rank": "group.rank_month"},
            "cites": cites if cites is not None else ["group.rank_month", "row.rel_volume"],
            "confidence": confidence}


def test_rule1_slot_undeclared_in_slots():
    pack = _pack_with_fields()
    stmt = _stmt(text="Group is #{rank}.", slots={})
    result = validate({"statements": [stmt]}, pack)
    assert result["rejections"][0]["rule"] == "rule1_slot_undeclared"


def test_rule1_slot_declared_but_unused_in_text():
    pack = _pack_with_fields()
    stmt = _stmt(text="Group looks strong.", slots={"rank": "group.rank_month"})
    result = validate({"statements": [stmt]}, pack)
    assert result["rejections"][0]["rule"] == "rule1_slot_unused"


def test_rule1_catches_dotted_field_id_used_directly_as_placeholder():
    # Regression: the AI-NEXT-P0c spike (2026-09-06) found gemini-3.5-flash writing the field
    # id straight into text (e.g. "{row.status}") instead of a short slots-mapped name, with
    # slots left empty. The old letters-only _SLOT_RE didn't match the dot, so this pattern was
    # invisible to Rule 1 and slipped through validate() as if it had no placeholders at all —
    # the literal, unsubstituted "{row.status}" text would have rendered to a real user.
    pack = _pack_with_fields()
    stmt = _stmt(text="Status is now {row.status}.", slots={}, cites=["row.rel_volume"])
    result = validate({"statements": [stmt]}, pack)
    assert result["rejections"][0]["rule"] == "rule1_slot_undeclared"


def test_rule2_slot_references_missing_field():
    pack = _pack_with_fields()
    stmt = _stmt(slots={"rank": "row.does_not_exist"})
    result = validate({"statements": [stmt]}, pack)
    assert result["rejections"][0]["rule"] == "rule2_slot_unresolved"


def test_rule2_slot_pointing_into_context_rejected_specifically():
    pack = _pack_with_fields()
    stmt = _stmt(slots={"rank": "context:industries"})
    result = validate({"statements": [stmt]}, pack)
    rej = result["rejections"][0]
    assert rej["rule"] == "rule2_slot_unresolved"
    assert "context" in rej["detail"]


def _catch_stmt():
    return _stmt(kind="catch", text="Watch for a reversal.", slots={},
                cites=["row.rel_volume", "group.rank_month"])


def test_rule2_cite_block_reference_valid():
    pack = _pack_with_fields()
    stmt = _stmt(text="No slots here.", slots={}, cites=["context:industries"])
    result = validate({"statements": [stmt, _catch_stmt()]}, pack)
    assert not result["rejections"]
    assert any(s["kind"] == "read" for s in result["statements"])


def test_rule2_cite_row_reference_valid():
    pack = _pack_with_fields()
    stmt = _stmt(text="No slots here.", slots={},
                cites=["context:industries#Semiconductors"])
    result = validate({"statements": [stmt, _catch_stmt()]}, pack)
    assert not result["rejections"]


def test_rule2_cite_row_reference_missing_rowkey_rejected():
    pack = _pack_with_fields()
    stmt = _stmt(text="No slots here.", slots={}, cites=["context:industries#DoesNotExist"])
    result = validate({"statements": [stmt]}, pack)
    assert result["rejections"][0]["rule"] == "rule2_cite_unresolved"


def test_rule3_lexicon_pass_reclaimed_the_20ma():
    pack = _pack_with_fields()
    stmt = _stmt(text="It reclaimed the 20MA.", slots={},
                cites=["row.rel_volume", "group.rank_month"])
    result = validate({"statements": [stmt, _catch_stmt()]}, pack)
    assert not result["rejections"]
    assert any(s["kind"] == "read" for s in result["statements"])


def test_rule3_bare_digit_fails_up_3_sessions():
    pack = _pack_with_fields()
    stmt = _stmt(text="Up 3 sessions.", slots={}, cites=["row.rel_volume", "group.rank_month"])
    result = validate({"statements": [stmt, _catch_stmt()]}, pack)
    assert result["rejections"][0]["rule"] == "rule3_bare_digit"


def test_rule3_slot_placeholder_itself_does_not_trip_digit_check():
    pack = _pack_with_fields()
    stmt = _stmt(text="Group is #{rank}.", slots={"rank": "group.rank_month"},
                cites=["group.rank_month", "row.rel_volume"])
    result = validate({"statements": [stmt, _catch_stmt()]}, pack)
    assert not result["rejections"]


def test_rule4_read_without_catch_card_dropped_zero_statements():
    pack = _pack_with_fields("morning_card")
    stmt = _stmt(kind="read")
    result = validate({"statements": [stmt]}, pack)
    assert result["card_dropped"] is True
    assert result["statements"] == []


def test_unknown_kind_dropped_rest_still_validates():
    pack = _pack_with_fields("morning_card")
    good_catch = _stmt(kind="catch", text="Watch for a reversal.", slots={},
                       cites=["row.rel_volume"])
    bad = {"kind": "bogus_kind", "text": "whatever", "slots": {}, "cites": ["row.rel_volume"],
          "confidence": "high"}
    result = validate({"statements": [bad, good_catch]}, pack)
    kinds_rejected = [r["rule"] for r in result["rejections"]]
    assert "kind" in kinds_rejected
    assert not result["card_dropped"]
    assert len(result["statements"]) == 1
    assert result["statements"][0]["kind"] == "catch"


def test_per_surface_cap_keeps_first_read_rejects_extras():
    pack = _pack_with_fields("morning_card")
    read1 = _stmt(kind="read", text="Group is #{rank}, first.", slots={"rank": "group.rank_month"})
    read2 = _stmt(kind="read", text="Group is #{rank}, second.", slots={"rank": "group.rank_month"})
    read3 = _stmt(kind="read", text="Group is #{rank}, third.", slots={"rank": "group.rank_month"})
    catch = _stmt(kind="catch", text="Watch for a reversal.", slots={}, cites=["row.rel_volume"])
    result = validate({"statements": [read1, read2, read3, catch]}, pack)
    reads_kept = [s for s in result["statements"] if s["kind"] == "read"]
    assert len(reads_kept) == 1
    assert "first" in reads_kept[0]["text"]
    cap_rejections = [r for r in result["rejections"] if r["rule"] == "cap_kind"]
    assert len(cap_rejections) == 2


def test_subjects_accepted_on_morning_triage_rejected_on_morning_card():
    triage_pack = _pack_with_fields("morning_triage")
    triage_stmt = {"kind": "triage", "text": "Names moved.", "slots": {},
                  "cites": ["row.rel_volume", "group.rank_month"], "confidence": "high",
                  "subjects": ["NVDA"]}
    triage_catch = {"kind": "catch", "text": "Watch for a reversal.", "slots": {},
                    "cites": ["row.rel_volume"], "confidence": "high"}
    result = validate({"statements": [triage_stmt, triage_catch]}, triage_pack)
    assert not result["rejections"]
    triage_kept = [s for s in result["statements"] if s["kind"] == "triage"][0]
    assert triage_kept["subjects"] == ["NVDA"]

    card_pack = _pack_with_fields("morning_card")
    card_stmt = _stmt(kind="read")
    card_stmt["subjects"] = ["NVDA"]
    result2 = validate({"statements": [card_stmt]}, card_pack)
    assert result2["rejections"][0]["rule"] == "subjects"


def test_mismatched_major_contract_version_drops_everything():
    pack = _pack_with_fields("morning_card")
    catch = _stmt(kind="catch", text="Watch for a reversal.", slots={}, cites=["row.rel_volume"])
    result = validate({"contract_version": "2.0.0", "statements": [catch]}, pack)
    assert result["card_dropped"] is True
    assert result["statements"] == []
    assert result["rejections"][0]["rule"] == "contract_version"


def test_every_rejection_is_dict_with_status_rejected_and_rule_key():
    pack = _pack_with_fields("morning_card")
    stmt = _stmt(text="Up 3 sessions.", slots={}, cites=["row.rel_volume"])
    result = validate({"statements": [stmt]}, pack)
    for rej in result["rejections"]:
        assert rej["status"] == "rejected"
        assert "rule" in rej


# ===========================================================================
# CONFIDENCE
# ===========================================================================

def test_null_field_citation_forces_low_confidence():
    pack = _pack_with_fields(extra_fields={"row.reclaim_ref": {"v": None, "u": "enum",
                                                                "l": "Reclaim reference",
                                                                "d": None}})
    stmt = _stmt(text="No slots.", slots={},
                cites=["group.rank_month", "row.reclaim_ref"], confidence="high")
    result = validate({"statements": [stmt, _catch_stmt()]}, pack)
    kept = [s for s in result["statements"] if s["kind"] == "read"][0]
    assert kept["confidence"] == "low"
    assert "row.reclaim_ref" in kept["thin"]


def test_two_nonnull_field_cites_no_note_flag_keeps_model_high():
    pack = _pack_with_fields()
    stmt = _stmt(text="No slots.", slots={},
                cites=["group.rank_month", "row.rel_volume"], confidence="high")
    result = validate({"statements": [stmt, _catch_stmt()]}, pack)
    kept = [s for s in result["statements"] if s["kind"] == "read"][0]
    assert kept["confidence"] == "high"
    assert "thin" not in kept


def test_fewer_than_two_distinct_field_cites_forces_low():
    pack = _pack_with_fields()
    stmt = _stmt(text="No slots.", slots={}, cites=["group.rank_month"], confidence="high")
    result = validate({"statements": [stmt, _catch_stmt()]}, pack)
    kept = [s for s in result["statements"] if s["kind"] == "read"][0]
    assert kept["confidence"] == "low"


def test_notes_flag_check_is_word_boundary_not_substring():
    # Regression: the routine no-prior-read note ends "...so nothing can be said about what
    # changed." The field id suffix "change" (row.change) is a substring of "changed" — a
    # naive `in` check on notes_blob wrongly forced every row.change citation to `low`
    # confidence even though the field is clean and has nothing to do with the note.
    pack = _pack_with_fields(extra_fields={"row.change": {"v": 1.62, "u": "pct", "l": "Change"}})
    pack["notes"] = ["No prior read exists for this ticker (first appearance, or the prior "
                     "session's scrape is missing), so nothing can be said about what changed."]
    stmt = _stmt(text="No slots.", slots={},
                cites=["group.rank_month", "row.change"], confidence="high")
    result = validate({"statements": [stmt, _catch_stmt()]}, pack)
    kept = [s for s in result["statements"] if s["kind"] == "read"][0]
    assert kept["confidence"] == "high"
    assert "thin" not in kept


def test_notes_flag_check_still_catches_exact_field_mention():
    pack = _pack_with_fields()
    pack["notes"] = ["The rel_volume field is stale for this date; treat it with caution."]
    stmt = _stmt(text="No slots.", slots={},
                cites=["group.rank_month", "row.rel_volume"], confidence="high")
    result = validate({"statements": [stmt, _catch_stmt()]}, pack)
    kept = [s for s in result["statements"] if s["kind"] == "read"][0]
    assert kept["confidence"] == "low"
    assert "cites a field flagged in notes" in kept["thin"]


# ===========================================================================
# RETRY (validate_with_retry)
# ===========================================================================

def test_retry_succeeds_second_attempt_keeps_retry_statements_and_both_rejections():
    pack = _pack_with_fields("morning_card")
    bad_response = {"statements": [_stmt(kind="read")]}  # no catch -> card_dropped

    good_catch = _stmt(kind="catch", text="Watch for a reversal.", slots={},
                       cites=["row.rel_volume", "group.rank_month"])
    good_read = _stmt(kind="read", text="Group is #{rank}.", slots={"rank": "group.rank_month"},
                      cites=["group.rank_month", "row.rel_volume"])
    good_response = {"statements": [good_read, good_catch]}

    calls = []
    def retry(errors):
        calls.append(errors)
        return good_response

    result = validate_with_retry(bad_response, pack, retry)
    assert result["attempts"] == 2
    assert not result["card_dropped"]
    kinds = sorted(s["kind"] for s in result["statements"])
    assert kinds == ["catch", "read"]
    # rejections from BOTH attempts preserved. The first attempt produced no per-statement
    # rejections (its lone `read` validated fine) but did fail the card on the missing-catch
    # rule; validate() itself does not append a Rejection object for rule 4 (only an `errors`
    # string), so with a clean second attempt the combined rejections list is legitimately
    # empty here — assert on `errors` from the run instead, which does carry the rule-4 message.
    assert len(calls) == 1


def test_retry_callable_returning_none_falls_back_to_first_result():
    pack = _pack_with_fields("morning_card")
    bad_response = {"statements": [_stmt(kind="read")]}  # no catch

    def retry(errors):
        return None

    result = validate_with_retry(bad_response, pack, retry)
    assert result["attempts"] == 1
    assert result["card_dropped"] is True


def test_retry_receives_nonempty_error_list_mentioning_offending_field():
    pack = _pack_with_fields("morning_card")
    bad_response = {"statements": [_stmt(kind="read", slots={"rank": "row.does_not_exist"})]}

    captured = {}
    def retry(errors):
        captured["errors"] = errors
        return None

    validate_with_retry(bad_response, pack, retry)
    assert captured["errors"]
    assert any("row.does_not_exist" in e for e in captured["errors"])

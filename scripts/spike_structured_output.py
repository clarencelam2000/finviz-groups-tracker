"""AI-NEXT-P0c — structured-output spike: does gemini-3.5-flash hold the pack contract?

Runs real `morning_card` evidence packs (built by `scripts/evidence_pack.py`) against
`gemini-3.5-flash` with `response_schema` set, pushes every response through the P0a validator
with retry-once, and reports the drop rate that selects the renderer design.

**This does not decide whether the AI workstream ships.** Per
`planning/ai-evidence-pack-schema.md` §3.2 the measured drop-rate-after-retry selects one of
three renderer designs, all of which ship a cited, AI-selected read:

    <= 5%   -> slot filling, batched calls (cheapest, fastest)
    5-15%   -> slot filling, one row per call (slower, same product)
    > 15%   -> renderer-owned templates: the model returns kind + cites only and the app
               owns the sentence wording (strictly the safer product, just less fluent)

**Cohort split (owner decision, 2026-09-06).** The Finviz setup block (RSI / Volatility /
Rel Volume / 52W High / Price / SMA20 / SMA50 / ATR) only exists in the session stores from
2026-09-01 and 2026-09-03 respectively. Packs built from earlier dates omit those fields, so a
single blended drop rate would mix two different pack shapes. This script therefore reports
**two rates**:

    full  — rows carrying the setup block. This is the production-shaped pack, and the cohort
            the thresholds above are read against.
    thin  — rows without it. Measures whether the model misbehaves around omitted fields
            (invents them, or cites ids that are not in the pack), which the full cohort
            cannot tell us.

**Cannot run from a Claude Code cloud session** — needs Vertex/AI-Studio credentials. Run it
locally or in GitHub Actions, same auth as `generate_ai.py`:

    GOOGLE_GENAI_USE_VERTEXAI=true GOOGLE_API_KEY=... \\
        python3 scripts/spike_structured_output.py --limit 60

Auth priority matches `generate_ai.py`: Vertex express key (`GOOGLE_API_KEY`) > Vertex ADC
(`GOOGLE_CLOUD_PROJECT`) > AI Studio (`GEMINI_API_KEY`).

Writes a JSON result blob plus a ready-to-paste markdown summary for the knowledge note at
`knowledge/investigations/ai-next-structured-output-spike.md` (US-P0c AC4).
"""

from __future__ import annotations

import argparse
import json
import os
import random
import statistics
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import evidence_pack as ep  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
SESSIONS = REPO / "data" / "picks" / "sessions"
INDUSTRY_DELTAS = REPO / "data" / "industries" / "deltas.csv"
DEFAULT_OUT = REPO / "knowledge" / "investigations" / "ai-next-structured-output-spike.json"

GEMINI_MODEL = "gemini-3.5-flash"

# Statuses that put a row in scope for the Morning pipeline (US-P2a AC2). The spike samples
# preferentially from these plus status-changed rows, because those are the rows production
# will actually call on — measuring the drop rate on `setting_up` rows nobody sends would
# flatter the result.
IN_SCOPE = ep.ACTIONABLE_STATUSES

# The response schema handed to the model. Deliberately mirrors schema §3 exactly; if this and
# `evidence_pack.validate()` ever disagree, the validator wins and the spike will show it as a
# drop — which is the signal we want, not something to paper over here.
RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["contract_version", "statements"],
    "properties": {
        "contract_version": {"type": "string"},
        "statements": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["kind", "text", "slots", "cites", "confidence"],
                "properties": {
                    "kind": {"type": "string", "enum": ["read", "catch"]},
                    "text": {"type": "string"},
                    "slots": {"type": "object"},
                    "cites": {"type": "array", "items": {"type": "string"}},
                    "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                },
            },
        },
    },
}

SYSTEM_PROMPT = """\
You write two sentences about one stock setup for an experienced swing trader who is already \
looking at the numbers. He does not want the numbers restated; he wants to know what they mean \
and what argues against acting.

You are given an evidence pack. Return JSON matching the response schema, with exactly two \
statements:

  kind "read"  — what changed and what it means. One sentence.
  kind "catch" — the strongest honest reason NOT to take this. One sentence. Mandatory: if you \
cannot find one, say what would have to be true for the setup to fail. Never omit it.

Hard rules — output violating any of these is discarded:

1. NEVER write a number in `text`. Every number is a {placeholder} declared in `slots`, mapped \
to a field id from the pack's `fields`. The app formats it; you do not. Writing "up 3.4%" fails; \
writing "up {chg}" with slots {"chg": "row.change"} passes.
2. Every {placeholder} in `text` appears in `slots`, and every `slots` key appears in `text`.
3. `slots` values must be field ids from `fields`. NEVER a "context:" reference.
4. `cites` lists everything you reasoned from — a superset of your slot fields. It may also \
include "context:<block>" or "context:<block>#<rowkey>" for a pattern you found in the broad \
context. Never cite a field id that is not in the pack.
5. Named levels the app already uses are fine as words: 20MA, 50MA, 52W High, RSI, 10:05, 15:30, \
S&P 500. Anything else with a digit must be a slot.
6. `confidence`: "low" if you lean on a field whose value is null or that `notes` flags; \
"medium" if you rest on 2-3 clean fields; "high" otherwise.
7. Respect `notes`. If a note says a fact was not collected, you may not reason about it.

Set "contract_version" to "1.0.0".
"""


# ---------------------------------------------------------------------------
# Corpus
# ---------------------------------------------------------------------------

def _shared_context(morning, preclose, groups: dict, picked: list[dict]) -> dict[str, Any]:
    """The broad `context` layer (schema §2.2), shared by every pack in the run.

    Production assembles this once per session; the spike must include it or it would measure
    a materially smaller prompt than production sends — both the token cost and the model's
    ability to cite a `context:` block would go unmeasured. Built from the single most-recent
    session in the sample so it is one coherent read, not a mix of dates.

    NOTE: because the sampled rows span many dates, this block is representative rather than
    each row's own session. That is fine for measuring contract adherence (the question is
    whether the model keeps its cites resolvable and its slots in `fields`), but it means the
    spike is not a test of reasoning quality. Said plainly in the knowledge note.
    """
    import pandas as pd

    latest_date = max(str(c["row"]["date"]) for c in picked) if picked else None
    frames = [f for f in (morning, preclose) if len(f)]
    if not frames or latest_date is None:
        return {}
    allrows = pd.concat(frames, ignore_index=True)
    sess = allrows[allrows["date"].astype(str) == latest_date]
    if not len(sess):
        return {}

    cols = ["ticker", "group", "list_category", "status", "atr_from_lod"]
    rows = [[ep._text(r.get("ticker")), ep._text(r.get("group")),
             ep._text(r.get("list_category")), ep._text(r.get("status")),
             ep._num(r.get("atr_from_lod"))] for r in sess.to_dict("records")]

    # Label names both sessions because `allrows` concatenates morning + pre_close for that
    # date — production's per-session run would carry one session here. Keeping the label
    # honest matters: it is what the provenance drawer shows for a `context:session_rows` cite.
    ctx = {"session_rows": {"label": f"All rows from both reads, {latest_date}",
                            "key": "ticker", "columns": cols, "rows": rows}}
    if groups:
        gcols = ["name", "rank_month", "rank_month_delta_5d", "rs_month", "rs_score",
                 "momentum_score"]
        ctx["industries"] = {
            "label": f"All {len(groups)} industries, latest deltas", "key": "name",
            "columns": gcols,
            "rows": [[n] + [ep._num(g.get(c)) for c in gcols[1:]] for n, g in groups.items()],
        }
    return ctx


def _load_corpus(limit: int, seed: int) -> list[dict[str, Any]]:
    """Build morning_card packs from real session history, cohort-tagged.

    Prior-row pairing follows US-P2a AC2: a `morning` row's prior is the *previous day's*
    `pre_close`; a `pre_close` row's prior is the *same day's* `morning`.
    """
    import pandas as pd

    morning = pd.read_csv(SESSIONS / "morning.csv")
    preclose = pd.read_csv(SESSIONS / "pre_close.csv")

    def _index(df):
        return {(r["date"], r["ticker"]): r for r in df.to_dict("records")}

    m_idx, p_idx = _index(morning), _index(preclose)
    m_dates = sorted(morning["date"].unique())
    prev_day = {d: m_dates[i - 1] for i, d in enumerate(m_dates) if i > 0}

    groups: dict[str, dict] = {}
    if INDUSTRY_DELTAS.exists():
        gd = pd.read_csv(INDUSTRY_DELTAS)
        if len(gd):
            latest = gd[gd["date"] == gd["date"].max()]
            groups = {r["name"]: r for r in latest.to_dict("records")}

    candidates: list[dict[str, Any]] = []
    for df, session in ((morning, "morning"), (preclose, "pre_close")):
        for row in df.to_dict("records"):
            date, ticker = row["date"], row["ticker"]
            if session == "morning":
                prior = p_idx.get((prev_day.get(date, ""), ticker))
            else:
                prior = m_idx.get((date, ticker))
            status = str(row.get("status") or "")
            changed = prior is not None and str(prior.get("status") or "") != status
            if status not in IN_SCOPE and not changed:
                continue  # production would not call on this row
            candidates.append({"row": row, "prior": prior,
                               "group": groups.get(str(row.get("group") or ""))})

    random.Random(seed).shuffle(candidates)

    # Stratify: fill half the budget from each cohort where possible, so a thin-cohort-heavy
    # history cannot swamp the full-field rows the thresholds are read against.
    #
    # Cohort test goes through ep._text, NOT `str(x) or ''` — pandas reads a blank CSV cell as
    # float NaN, and `str(nan)` is the truthy string "nan", which silently classified every
    # thin row as full-field. (Caught by --dry-run before any API spend.)
    def _cohort(c) -> str:
        return "full" if ep._text(c["row"].get("SMA50")) is not None else "thin"

    by_cohort: dict[str, list] = {"full": [], "thin": []}
    for c in candidates:
        by_cohort[_cohort(c)].append(c)

    # Take up to half from each, then backfill from whichever cohort still has rows so a short
    # cohort never costs us sample size.
    half = max(1, limit // 2)
    picked = by_cohort["full"][:half] + by_cohort["thin"][:half]
    if len(picked) < limit:
        taken = set(id(c) for c in picked)
        picked += [c for c in candidates if id(c) not in taken][: limit - len(picked)]
    picked = picked[:limit]

    context = _shared_context(morning, preclose, groups, picked)

    out = []
    for c in picked:
        pack = ep.build_morning_card(c["row"], c["prior"], c["group"], context)
        out.append({"pack": pack, "cohort": _cohort(c),
                    "status": str(c["row"].get("status") or ""),
                    "changed": c["prior"] is not None
                    and str(c["prior"].get("status") or "") != str(c["row"].get("status") or "")})
    return out


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------

def _make_client():
    """Same auth ladder as generate_ai.py: Vertex express > Vertex ADC > AI Studio."""
    try:
        import google.genai as genai
    except ImportError:
        sys.exit("google-genai not installed. Run: pip install google-genai")

    use_vertex = os.getenv("GOOGLE_GENAI_USE_VERTEXAI", "").lower() in ("1", "true", "yes")
    vertex_key = os.getenv("GOOGLE_API_KEY")
    project = os.getenv("GOOGLE_CLOUD_PROJECT")
    studio_key = os.getenv("GEMINI_API_KEY")

    if use_vertex and vertex_key:
        return genai.Client(vertexai=True, api_key=vertex_key), "vertex_express"
    if use_vertex and project:
        return genai.Client(vertexai=True, project=project,
                            location=os.getenv("GOOGLE_CLOUD_LOCATION", "global")), "vertex_ai"
    if studio_key:
        return genai.Client(api_key=studio_key), "google_ai_studio"
    sys.exit("No credentials. Set GOOGLE_API_KEY (+GOOGLE_GENAI_USE_VERTEXAI=true) or "
             "GEMINI_API_KEY. This script cannot run from a Claude Code cloud session.")


def _prompt_for(pack: dict, extra_errors: list[str] | None = None) -> str:
    prefix, tail = ep.prompt_parts(pack)
    parts = [SYSTEM_PROMPT, "\n## Shared context\n", prefix, "\n## This row\n", tail]
    if extra_errors:
        parts.append("\n## Your previous answer was rejected. Fix exactly these and retry:\n")
        parts.extend(f"- {e}\n" for e in extra_errors)
    return "".join(parts)


def _call(client, prompt: str) -> tuple[dict | None, float, str | None]:
    from google.genai import types
    started = time.monotonic()
    try:
        resp = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=RESPONSE_SCHEMA,
            ),
        )
        return json.loads(resp.text), time.monotonic() - started, None
    except Exception as e:  # noqa: BLE001 — the spike records failures, it does not handle them
        msg = str(e)
        if "GenerateRequestsPerDayPerProjectPerModel" in msg:
            raise
        return None, time.monotonic() - started, msg


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

def run(limit: int, seed: int, out_path: Path) -> dict[str, Any]:
    corpus = _load_corpus(limit, seed)
    if not corpus:
        sys.exit("no in-scope rows found in the session stores")
    client, backend = _make_client()
    print(f"[backend] {backend}  [model] {GEMINI_MODEL}  [packs] {len(corpus)}")

    results: list[dict[str, Any]] = []
    for i, item in enumerate(corpus, 1):
        pack = item["pack"]
        subject = pack["meta"]["subject"]
        first, lat1, err1 = _call(client, _prompt_for(pack))
        latency = lat1
        if first is None:
            results.append({**_meta(item), "outcome": "api_error", "latency": lat1,
                            "error": err1})
            print(f"  {i:>3}/{len(corpus)} {subject:<6} api_error")
            continue

        v = ep.validate(first, pack)
        if not v["rejections"] and not v["card_dropped"]:
            outcome, attempts, final = "first_try", 1, v
        else:
            second, lat2, err2 = _call(client, _prompt_for(pack, v["errors"]))
            latency += lat2
            if second is None:
                outcome, attempts, final = "dropped", 2, v
            else:
                v2 = ep.validate(second, pack)
                if not v2["card_dropped"] and v2["statements"]:
                    outcome, attempts, final = "after_retry", 2, v2
                else:
                    outcome, attempts, final = "dropped", 2, v2

        results.append({**_meta(item), "outcome": outcome, "attempts": attempts,
                        "latency": latency,
                        "rules": sorted({r["rule"] for r in final["rejections"]}),
                        "statements": final["statements"],
                        "raw_first": first})
        print(f"  {i:>3}/{len(corpus)} {subject:<6} {item['cohort']:<4} {outcome:<11} "
              f"{latency:5.1f}s")

    report = _summarise(results)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps({"model": GEMINI_MODEL, "backend": backend,
                                    "seed": seed, "summary": report, "results": results},
                                   indent=2), encoding="utf-8")
    print(f"\nwrote {out_path}")
    print(_markdown(report))
    return report


def _meta(item: dict) -> dict:
    return {"subject": item["pack"]["meta"]["subject"],
            "as_of": item["pack"]["meta"]["as_of"],
            "session": item["pack"]["meta"]["session"],
            "cohort": item["cohort"], "status": item["status"],
            "status_changed": item["changed"]}


def _summarise(results: list[dict]) -> dict[str, Any]:
    def _bucket(rows: list[dict]) -> dict[str, Any]:
        n = len(rows)
        if not n:
            return {"n": 0}
        c = {k: sum(1 for r in rows if r["outcome"] == k)
             for k in ("first_try", "after_retry", "dropped", "api_error")}
        lat = [r["latency"] for r in rows if r.get("latency")]
        return {
            "n": n, **c,
            "drop_rate_pct": round(100.0 * c["dropped"] / n, 1),
            "first_try_pct": round(100.0 * c["first_try"] / n, 1),
            "latency_median_s": round(statistics.median(lat), 2) if lat else None,
            "latency_p90_s": round(sorted(lat)[int(0.9 * (len(lat) - 1))], 2) if lat else None,
        }

    full = _bucket([r for r in results if r["cohort"] == "full"])
    rule_counts: dict[str, int] = {}
    for r in results:
        for rule in r.get("rules", []):
            rule_counts[rule] = rule_counts.get(rule, 0) + 1

    drop = full.get("drop_rate_pct")
    if drop is None:
        design = "undetermined (no full-field rows in the sample)"
    elif drop <= 5:
        design = "slot filling, batched calls"
    elif drop <= 15:
        design = "slot filling, per-row calls only"
    else:
        design = "renderer-owned templates (model returns kind + cites only)"

    return {"all": _bucket(results), "full": full,
            "thin": _bucket([r for r in results if r["cohort"] == "thin"]),
            "by_rule": dict(sorted(rule_counts.items(), key=lambda kv: -kv[1])),
            "selected_design": design,
            "threshold_cohort": "full",
            "statuses": sorted({r["status"] for r in results}),
            "n_status_changed": sum(1 for r in results if r["status_changed"])}


def _markdown(s: dict) -> str:
    def _row(name: str, b: dict) -> str:
        if not b.get("n"):
            return f"| {name} | 0 | — | — | — | — |"
        return (f"| {name} | {b['n']} | {b['first_try_pct']}% | {b['after_retry']} | "
                f"{b['drop_rate_pct']}% | {b['latency_median_s']}s |")

    return "\n".join([
        "",
        "| Cohort | n | validated 1st try | validated after retry | **dropped** | median latency |",
        "|---|---|---|---|---|---|",
        _row("full (2026-09-03+)", s["full"]),
        _row("thin (setup block absent)", s["thin"]),
        _row("**all**", s["all"]),
        "",
        f"**Selected renderer design (read against the `full` cohort): {s['selected_design']}**",
        "",
        f"Statuses covered: {', '.join(s['statuses'])} · status-changed rows: "
        f"{s['n_status_changed']}",
        f"Rejections by rule: {s['by_rule'] or 'none'}",
    ])


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--limit", type=int, default=60,
                    help="packs to run (US-P0c AC1 requires >= 50); default 60")
    ap.add_argument("--seed", type=int, default=20260906,
                    help="sampling seed, so a re-run measures the same corpus")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--dry-run", action="store_true",
                    help="build and print the corpus + one prompt, make no API call "
                         "(this is the part that DOES run from a cloud session)")
    args = ap.parse_args(argv)

    if args.dry_run:
        corpus = _load_corpus(args.limit, args.seed)
        cohorts: dict[str, int] = {}
        statuses: dict[str, int] = {}
        for c in corpus:
            cohorts[c["cohort"]] = cohorts.get(c["cohort"], 0) + 1
            statuses[c["status"]] = statuses.get(c["status"], 0) + 1
        print(f"corpus: {len(corpus)} packs  cohorts={cohorts}  statuses={statuses}  "
              f"status_changed={sum(1 for c in corpus if c['changed'])}")
        if corpus:
            print("\n--- example prompt (truncated) ---")
            print(_prompt_for(corpus[0]["pack"])[:2000])
        return 0

    run(args.limit, args.seed, args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

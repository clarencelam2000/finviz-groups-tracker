# WS3b — Pre-close (~15:30 ET) confirmation surface

> **Status:** scoped, ready for implementation. Issue [#268](https://github.com/clarencelam2000/finviz-groups-tracker/issues/268).
> **Owner decisions (all made, 2026-08-17):** dispatch **15:30 ET**; **one tab + toggle** (no new tab);
> tab label stays **"Morning"**; **"since AM" delta chips are in for v1**; **generalize, don't clone.**
> **Mock:** `planning/mocks/ws3b-preclose-toggle.html` (interactive — toggle Morning · Pre-close).

## 1. What this is

A ~15:30 ET (last half-hour) read that tags each of today's tradeable setups with a live status —
**is this setup confirming *into the close*?** — so the swing trader can enter near the close rather
than waiting a full session. Sibling of WS3 (#262, the 10:05 ET morning surface). The morning read
answers *"did yesterday's setup survive the open?"*; the pre-close read answers *"is it worth taking
at the close?"* — the moment the user actually decides to enter.

## 2. Guiding principle: this is the morning pipeline, run once more

Everything load-bearing already exists and was **deliberately built session-agnostic** for this exact
reuse. WS3b adds `pre_close` as **data**, not as a parallel code path.

| Piece | Already built | WS3b action |
|---|---|---|
| Status engine `compute_pick_status()` | `scripts/pick_status.py` — pure, no I/O, docstring names WS3b as a caller | **reuse verbatim** |
| Session registry | `scripts/session_config.py` — `pre_close` already registered (`capture_et="15:50"`, `settled=False`) | reuse; **change capture time to 15:30** |
| Writer | `scripts/collect_morning.py` (`fetch_ticker_quotes`, `build_ticker_url`, `write_store`, `assert_provisional`) | **generalize to `--session`** |
| Store shape | `data/picks/sessions/morning{,_latest}.csv` | clone shape → `pre_close{,_latest}.csv` |
| PWA surface | `#tab-morning`, `renderMorning()`, `loadMorning()`, `MORNING_STATUS_META` | **generalize to take a session** |
| Cron dispatch | `worker-cron/src/routing.js` `JOB_SCHEDULE` + `jobsForTick` | **add one gated 15:30 job** |

The only genuinely new things: (1) one more scheduled trigger, (2) a session toggle in the tab,
(3) the "since AM" delta chips (morning→pre_close join). That's the whole change.

## 3. Non-goals / explicit scope guards

- **No new selection logic.** The pre-close surface evaluates the **same latest-EOD picks list** the
  morning surface uses (today's picks don't exist until 17:00). Strictly read-only against existing picks.
- **No settled-pipeline changes.** `pre_close` is a provisional session under ADR-011 Option C —
  `data/sectors|industries/*.csv`, `deltas.csv`, and `picks.csv` are untouched. Writer MUST call
  `session_config.assert_provisional("pre_close")`.
- **Do not touch the existing `collect_preclose` cron job.** WS1 already claimed that name for an
  *unrelated* settled-data backstop that dispatches `collect.yml` for the #259 picks gate. It is
  load-bearing — the WS3b job is a **separate, differently-named** job. (Naming: §5.)
- **Engine stays pure.** `GAPPED_THROUGH` is a morning-open concept; at 15:30 it's meaningless. Do
  **not** fork the engine — handle it as a *display* decision (§6): the pre-close render suppresses/relabels
  `gapped_through`, the engine keeps returning whatever it returns.

## 4. Phase A — Writer: generalize `collect_morning.py`, don't clone

Refactor `scripts/collect_morning.py` → a session-parameterized writer (`--session {morning,pre_close}`,
default `morning`). Rename to `collect_session.py` **or** keep the filename and add the arg — implementer's
call, lower-churn wins; whichever is chosen, the morning workflow reference must be updated in lockstep.

- Capture time and output path derive from `session_config.py` (`SESSIONS[session].capture_et`, store path),
  not hardcoded `morning`.
- Writes `data/picks/sessions/pre_close.csv` + `pre_close_latest.csv`, **identical schema** to `morning.csv`
  (`date, session, collected_at, ticker, group, list_category, trigger, stop, atr, price, open, high, low,
  change, status, atr_from_lod`), with `session=pre_close`.
- Calls `session_config.assert_provisional("pre_close")` at the write boundary.
- **Regression guard:** morning output must stay byte-identical. Add a test asserting `--session morning`
  produces the same rows as before the refactor.
- **`session_config.py`:** change `pre_close` `capture_et` from `15:50` → **`15:30`**. Triple-document the
  constant (in-code comment + README § Configurable parameters + CLAUDE.md § Automation), per the 3-places rule.
- **Tests:** clone the morning-writer tests for the pre_close session (status classification, provisional
  guard, store dedup on `(date, session, ticker)`). If any imports Playwright, add it to the
  `--ignore=` list in `.github/workflows/tests.yml` (same PR).

## 5. Phase B — Dispatch: one more gated run at 15:30 ET (senior)

Add **one** gated job to `worker-cron/src/routing.js` `JOB_SCHEDULE`, at **15:30 ET, Mon–Fri**, self-healing
via its own KV key (mirror the `collect_morning` job entry). Name it distinctly to avoid the existing
`collect_preclose` backstop — suggest **`preclose_status`** (KV key `last_dispatch_preclose_status`).

Dispatch mechanism — implementer picks the lower-risk of:
1. Extend `routing.js`'s GitHub dispatch to pass `inputs.session=pre_close` to the shared workflow, **or**
2. Add a thin `.github/workflows/collect_preclose.yml` wrapper (cloned from `collect_morning.yml`) that
   just calls the shared script with `--session pre_close`. DRY still holds — the *logic* is shared at the
   script level; only a ~20-line yml wrapper is duplicated.

Also: healthchecks.io dead-man's-switch for the new run; leave the existing `collect_preclose` settled
backstop and the #259 picks gate **untouched** (verify no interaction). Triple-document the 15:30 constant.

## 6. Phase C — PWA: make the Morning tab session-aware (design lead owns taste)

Keep the single **"Morning"** tab (per owner). Add a segmented toggle **[ Morning · Pre-close ]** at the top,
defaulting to the freshest read for today (pre-close after 15:30, morning before). Generalize
`renderMorning()`/`loadMorning()` to take a session param and fetch the matching `*_latest.csv`.
Provisional chrome (amber banner + timestamp) is **non-negotiable** per ADR-011 — pre-close uses the
"confirming into the close" copy; morning keeps "survived the open."

**Delta chips (in for v1):** on the pre-close read only, each ticker that also appeared in today's
morning read gets a small chip — green `held since AM` if its status held/improved, red `faded from AM`
if it degraded (e.g. Triggered→below-trigger). Join morning_latest ↔ pre_close_latest on ticker. A
ticker with no morning row shows no chip (silence = no signal). This is the surface's payoff: "did the
setup hold from the open into the close?" without a second tab.

**`GAPPED_THROUGH` display handling:** the pre-close render must not show `gapped_through` (morning-open
concept). Map it to the relevant close-context status or suppress the pill — display-side only, engine
unchanged.

Match the existing design language exactly (Tailwind slate, `MORNING_STATUS_META` colors, unicode glyphs
— no emoji). Reuse the existing segmented-pill pattern (Picks All/Focus toggle, `docs/index.html` ~line 277).
See the mock for exact placement, copy, and chip styling.

## 7. Phase D — Ship

- **Release surface (hard rule, same PR as the PWA change):** prepend `docs/releases.json` entry
  (`version` `YYYY.MM.DD`, `tag: feature`, `tab: morning`), set `current`, bump `CACHE` in `docs/sw.js`.
- Session notes entry, `.session/SPRINT.md` task state.
- **Tracked follow-up:** ADR-014 says the WS4 trade-ticket `pre_close` phase is blocked on this — open/
  reference that follow-up so it isn't orphaned.

## 8. Acceptance criteria

- [ ] `collect_session.py --session pre_close` writes `data/picks/sessions/pre_close{,_latest}.csv`,
      schema-identical to morning, `session=pre_close`, provisional guard fires.
- [ ] `--session morning` output byte-identical to pre-refactor (regression test green).
- [ ] `session_config.SESSIONS["pre_close"].capture_et == "15:30"`, triple-documented.
- [ ] One new gated `preclose_status` job at 15:30 ET in `routing.js`; existing `collect_preclose` backstop
      and #259 picks gate provably unaffected; unit test for the routing entry.
- [ ] Morning tab shows the [Morning · Pre-close] toggle, defaults to freshest read, provisional chrome
      on both, "into the close" copy on pre-close.
- [ ] Pre-close read shows `held since AM` / `faded from AM` delta chips; `gapped_through` not shown at pre-close.
- [ ] `releases.json` + `sw.js` bumped in the same PR; `tests/test_guide_releases.py` green.
- [ ] Session notes + SPRINT updated; WS4 pre_close follow-up tracked.

## 9. Key files & resources

- Engine: `scripts/pick_status.py` · Sessions: `scripts/session_config.py`
- Writer template: `scripts/collect_morning.py` · Workflow template: `.github/workflows/collect_morning.yml`
- Cron: `worker-cron/src/routing.js` (`JOB_SCHEDULE`, `jobsForTick`), `worker-cron/README.md`
- PWA: `docs/index.html` (`#tab-morning`, `renderMorning`, `loadMorning`, `MORNING_STATUS_META` ~line 4975)
- Store precedent: `data/picks/sessions/morning{,_latest}.csv`
- ADRs: `knowledge/decisions/ADR-011-session-dimension.md`, `ADR-013-ws3-morning-status.md`,
  `ADR-014-ws4-trade-tickets.md` · Ideation: `knowledge/cron-lifecycle-ideation-and-alignment.md` §10
- Rules: `docs/CLAUDE.md` (release process, PWA testing), `scripts/CLAUDE.md` (picks pipeline),
  `.claude/rules/data-pipeline.md`, `.claude/rules/branch-commit-discipline.md`
- Mock: `planning/mocks/ws3b-preclose-toggle.html`

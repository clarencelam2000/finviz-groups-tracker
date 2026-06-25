# Plan: Replace GitHub Actions cron with a Cloudflare Cron Trigger scheduler

## Context

**Problem.** The daily Finviz scrape is scheduled by three `cron:` entries in
`.github/workflows/collect.yml`. GitHub's *scheduled* workflows are documented to be
delayed under load and **dropped entirely** during peak periods — and our own
`data/fetch_log.csv` confirms 4–10 hour drift between the scheduled UTC time and the
actual run. This makes "the EOD snapshot just before the close" unreliable.

**Key constraint (the part that shapes everything).** The complaint is about *scheduling*,
but the scrape itself is pinned to GitHub's infrastructure for a hard reason:
`scripts/collect.py` drives Playwright/Chromium for 2–4 minutes, and Finviz sits behind
Cloudflare bot-detection that **403s Google Cloud IPs** (our Claude/cloud IP) while letting
GitHub's **Azure IPs** through (documented in `CLAUDE.md` § Playwright/Finviz notes). A
Cloudflare Worker cannot host this job: Workers can't run a 2–4 min Chromium session, can't
run the pandas `compute_deltas.py` step, can't `git commit` the CSVs — and would scrape
*from Cloudflare IPs into a Cloudflare-protected site*, an untested and likely-blocked path.

**Therefore the fix decouples the two concerns.** Use Cloudflare's reliable, precise Cron
Trigger purely as the **scheduler**, which pokes GitHub's `workflow_dispatch` API to launch
the existing, proven `collect.yml` on Azure runners. `workflow_dispatch` events are
event-driven and processed promptly — they are *not* subject to the schedule-drop behavior
that causes the drift. `trading_date()` in `collect.py` already normalizes any residual
timing drift to the correct trading day, so the pipeline needs no logic changes.

**Decisions already made with the VP:**
- **Scope:** ship the scheduler replacement now; include a *time-boxed research spike* (no
  implementation) to learn whether Cloudflare Browser Rendering could ever scrape Finviz.
- **GitHub cron:** keep **one** entry (the EOD `48 19 * * 1-5`) as a redundancy backstop;
  Cloudflare becomes primary. Both fire simultaneously at `:48` every trading day — this is
  intentional redundancy, not a delayed fallback. A true time-offset fallback (e.g. fire
  GitHub 15 min later) would still be subject to GitHub's unreliable scheduling and provides
  no meaningful safety guarantee. Last-write-wins per date makes the expected double-run harmless.
- **Worker placement (staff call):** a **new dedicated `finviz-cron-dispatcher` Worker**,
  not a `scheduled()` handler bolted onto the live `finviz-ticker-lookup` Worker — so the
  scheduler has an independent deploy cycle and zero blast radius on ticker lookups.

**Intended outcome:** the scrape fires on time, every trading day, with the EOD run actually
landing near the close — while the working scrape pipeline is left untouched.

---

## Phase 0 — Land this plan (do this first, then PAUSE)

1. Create branch `claude/sweet-thompson-9i1l7d` from `origin/claude/elegant-babbage-hlxnfy`.
2. Commit this plan file into the repo at `planning/cloudflare-cron-scheduler.md`.
3. Push and open a **draft PR** targeting the default branch; mark ready; **merge it**.
4. **Stop and wait for the VP's go-ahead** before implementing Phases 1–4.

---

## Phase 1 — The `finviz-cron-dispatcher` Worker ✅ DONE (code/tests; deploy pending VP PAT)

New directory `worker-cron/` (mirrors the structure/tooling of `worker/`, including Vitest).

- **`worker-cron/wrangler.toml`**
  - `name = "finviz-cron-dispatcher"`, `main = "src/index.js"`.
  - `[triggers] crons = ["49 13 * * 1-5", "51 14 * * 1-5", "48 19 * * 1-5"]`
    (UTC, weekday-only — identical expressions to today's GitHub cron; Cloudflare cron is
    also fixed-UTC, so DST behaves exactly as documented in `CLAUDE.md` § Automation).
  - `[vars] DISPATCH_REF = "claude/elegant-babbage-hlxnfy"` — the branch that `collect.yml`
    runs on. Stored as a var (not a secret) so it can be changed without touching Worker code.
    TODO(D1): change to `"main"` once SPRINT.md task D1 (create `main`, set as default) is done.
  - Small KV namespace binding `DISPATCH_LOG` for observability (last-fire timestamp + outcome).
- **`worker-cron/src/index.js`**
  - `scheduled(event, env, ctx)` handler → `POST` to
    `https://api.github.com/repos/clarencelam2000/finviz-groups-tracker/actions/workflows/collect.yml/dispatches`
    with body `{ "ref": env.DISPATCH_REF }`, headers `Authorization: Bearer ${env.GITHUB_DISPATCH_TOKEN}`,
    `Accept: application/vnd.github+json`, `User-Agent: finviz-cron-dispatcher`,
    `X-GitHub-Api-Version: 2022-11-28`. Record `{ ts, status, cron: event.cron }` to KV.
  - Minimal `fetch()` handler exposing `GET /health` (KV connectivity) and `GET /last`
    (last dispatch record) for debugging — same response conventions as `worker/src/index.js`.
- **Secret:** `GITHUB_DISPATCH_TOKEN` — a **GitHub fine-grained PAT** scoped to this single
  repo with **Actions: Read and write** (nothing else). Set via `wrangler secret put`
  (headless-token deploy pattern in `knowledge/cloudflare-headless-deploy.md`).
  *VP action item:* mint this PAT; it's the one credential I can't create.
- **`worker-cron/test/index.test.js`** — Vitest, offline, mirroring `worker/test/`:
  assert the `scheduled` handler calls the correct GitHub URL/headers/body (mocked `fetch`),
  handles non-204 responses, and writes the KV record. No real network.

Reuses: existing Cloudflare account + headless deploy flow (`knowledge/cloudflare-headless-deploy.md`),
Worker/Vitest test conventions (`worker/test/index.test.js`), KV binding pattern (`worker/wrangler.toml`).

---

## Phase 2 — Trim `collect.yml` to a backstop ✅ DONE

- In `.github/workflows/collect.yml`, remove the two intraday `schedule:` entries; **keep
  `48 19 * * 1-5`** as the EOD redundancy backstop. Keep `workflow_dispatch` (now the primary
  entry path).
- Add a comment block explaining: Cloudflare `finviz-cron-dispatcher` is the primary
  scheduler via `workflow_dispatch`; the single remaining cron fires simultaneously at the
  same time as the CF cron and acts as redundancy (not a delayed fallback — GitHub's cron is
  too timing-unreliable for that). Last-write-wins per date makes the double-run harmless.
  No step/logic changes — the runner still does collect → verify → deltas → commit.

---

## Phase 3 — Edge-scrape research spike (investigate only, no implementation) ⏳ DEFERRED to its own session

Time-boxed (~half a session). Deliverable is a written verdict, not code:
- Stand up a throwaway Cloudflare Browser Rendering (`@cloudflare/puppeteer`) test that
  loads the Finviz groups URL and checks for `.groups_table` vs. a Turnstile/403 challenge.
- Record: does Cloudflare→Finviz (CF-behind-CF) pass or get challenged? Worker CPU/duration
  limits vs. our 2–4 min scrape. Where would `compute_deltas.py` + `git commit` run?
- Write findings to `knowledge/decisions/` as an ADR (recommend keep-on-GitHub-Actions vs.
  pursue-edge), so this is never re-litigated from scratch.

---

## Phase 4 — Docs, tests, handoff ✅ DONE (ADR-004; Phase 3 spike findings deferred)

- **`CLAUDE.md` § Automation:** rewrite to describe Cloudflare Cron Trigger as primary
  scheduler + GitHub cron backstop; note cron expressions now live in `worker-cron/wrangler.toml`.
- **`README.md` § Configurable parameters:** add the cron schedule + its location (per the
  project's "document configurable items in all three places" rule).
- **`knowledge/`:** ADR for the scheduler decision (the option debate: Cron→dispatch vs.
  edge Browser Rendering vs. removing GitHub cron) + the Phase 3 spike findings.
- **`.session/` notes + `WORK_LOG.md` + `SPRINT.md`:** updated per branch-commit-discipline.
- **No PWA "What's New" release cut** — this is backend/scheduling, invisible to PWA users,
  so `releases.json`/`sw.js` are intentionally untouched.

Suggested commit slicing (small, focused, each with its test/doc): (1) dispatcher Worker +
tests + add `worker-cron-test:` job to `.github/workflows/tests.yml` (mirrors the existing
`worker-test:` job; `working-directory: worker-cron`), (2) collect.yml backstop trim,
(3) Phase 3 spike ADR, (4) docs/session handoff.

---

## Verification

- **Worker unit tests:** `cd worker-cron && npm install && npm test` — all green, offline.
- **Repo tests:** `python3 -m pytest tests/ -q` (unchanged; confirms no pipeline regression).
- **Live dispatch (post-merge, with VP's PAT set):** deploy the Worker, then run
  `wrangler dev --test-scheduled` / trigger `scheduled` and confirm a new `collect.yml` run
  appears in GitHub Actions and a fresh row lands in `data/fetch_log.csv` at the expected ET time.
- **Timing validation:** over the following trading days, compare `fetch_log.csv`
  `timestamp` vs. the cron schedule — drift should collapse from hours to minutes.
- **Backstop check:** confirm the single remaining GitHub cron still independently produces a
  run if the Worker is paused.

## Prerequisites / VP action items
- Mint a GitHub fine-grained PAT (this repo only, **Actions: Read and write**) for `GITHUB_DISPATCH_TOKEN`.
- Confirm the existing Cloudflare account/headless deploy token can create a second Worker + a small KV namespace (expected yes, per `knowledge/cloudflare-headless-deploy.md`).

---

## Phase 5 — Extend dispatcher for `collect_picks.yml` (PICKS-2-CRON) ⏳ PLANNED

### Context

`collect_picks.yml` currently fires on a single GitHub `schedule:` cron (`8 20 * * 1-5`). Same
reliability problem that drove `collect.yml` to the CF dispatcher: GitHub cron drifts hours and
is dropped under load. The shared concurrency group serialises the two workflows but does **not**
order them — if deltas aren't pushed before the picks cron fires, the stale-read guard aborts
safely but that day's picks are **unrecoverable** (no backfill). A GitHub cron backstop is not
appropriate for picks: `collect_picks.py` scrapes up to 50 Finviz screener pages per run —
misfiring that from an unreliable backstop is too expensive. Instead, a 90-minute margin gives
the CF cron high confidence that deltas are ready, and a healthchecks.io dead-man's-switch
provides the before-bed alert if the CF flow fails silently.

### Architecture

Extend the existing `finviz-cron-dispatcher` Worker — no new Worker needed. The `scheduled()`
handler routes by `event.cron` string. The three existing entries continue dispatching only
`collect.yml`; the new 4th entry dispatches only `collect_picks.yml` (once/day).

### Timing

| UTC cron | EDT (summer) | PDT (summer) | PST (winter) | What |
|----------|--------------|--------------|--------------|------|
| `30 14 * * 1-5` | 10:30 AM | 9:30 AM | 9:30 AM | collect — intraday |
| `48 19 * * 1-5` |  3:48 PM | 2:48 PM | 2:48 PM | collect — pre-close |
| `01 21 * * 1-5` |  5:01 PM | 3:01 PM | 4:01 PM | collect — EOD post-close |
| `31 22 * * 1-5` | **6:31 PM** | **3:31 PM** | **2:31 PM** | picks — EOD +90 min |

90 min after the EOD post-close collect (`01 21`) gives ample time for
`collect.yml + compute_deltas + git push` before picks selects groups from `deltas.csv`.

DST: same rule as existing entries — adjust manually on 2nd Sunday March and 1st Sunday November.

### Implementation (next session)

1. **`worker-cron/wrangler.toml`** — add `"31 22 * * 1-5"` to `[triggers] crons`.

2. **`worker-cron/src/index.js`** — refactor around `dispatchWorkflow(env, cron, url, kvKey)`:
   - `PICKS_CRON = '31 22 * * 1-5'` constant (must match `wrangler.toml` exactly)
   - `scheduled()` routes: `event.cron === PICKS_CRON` → picks, else → collect
   - Separate KV keys: `last_dispatch_collect` / `last_dispatch_picks`
   - All `log()` calls gain `workflow: "collect"|"picks"` for `wrangler tail` filtering
   - `/last` returns `{ collect: {...}, picks: {...} }`

3. **`worker-cron/test/index.test.js`** — extend with picks routing + separate KV key tests.

4. **`.github/workflows/collect_picks.yml`** — remove `schedule:` block; keep `workflow_dispatch:`;
   add healthcheck ping step (see §Observability).

### Observability / before-bed alert

Add to `collect_picks.yml` on success:
```yaml
- name: Ping healthcheck on success
  if: success()
  env:
    PICKS_HEALTHCHECK_URL: ${{ secrets.PICKS_HEALTHCHECK_URL }}
  run: |
    [ -n "$PICKS_HEALTHCHECK_URL" ] && curl -fsS "$PICKS_HEALTHCHECK_URL" || true
```

Failure modes: CF+picks succeed → ping sent; CF+picks fail → GitHub emails; CF never fires →
no ping → healthchecks.io alerts. **VP action item:** create a healthchecks.io monitor
(period=24h, grace=2h; picks completes ~23:00 UTC so grace to ~01:00 UTC covers before-bed
review). Add `PICKS_HEALTHCHECK_URL` as a repo secret. Same pattern as `HEALTHCHECK_URL`.

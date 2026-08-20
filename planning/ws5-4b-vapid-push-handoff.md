# WS5-4b — VAPID push notifications: cold-start handoff

> **Status:** not started. This is the last remaining piece of the WS5 exit-confirmation surface.
> Self-sufficient for a fresh session — read this end-to-end, then `planning/trade-lifecycle-engine.md`
> §8 (two-tier notifications) before writing code. SPRINT: **WS5-4b**. Design authority: §8 + the
> already-shipped WS5-4a strip (`docs/index.html` `posConfirmStripHtml`). Issue: #264 (epic).

## Why this exists / what's already done

WS5-4 was split (owner-approved 2026-08-19) into **4a — in-app confirmation strip** (SHIPPED, PR #341:
`closing` positions hoist into a "Needs your confirmation" strip with Confirm-fill / Still-holding) and
**4b — VAPID push** (THIS doc). The design (§8) is explicit: **the in-app strip is the source of truth;
push is only the nudge.** So 4b is a convenience layer — a missed push never strands a position because
the strip catches it on next app-open. Build 4b to that framing: it must never be load-bearing.

Backend session fields (`sessions_in_closing`, `auto_confirm_sessions`) and the transition routes
(`confirm-exit`/`still-holding`) are already live (PRs #340/#341). Push adds a NEW notification channel
on top; it does not change the exit loop's correctness.

## Greenfield state (verified 2026-08-19 — recon in this session)

Push is **100% unbuilt** in this repo — confirmed by grep across `docs/`, `worker-positions/`,
`worker/`, `worker-cron/`:
- **No** service-worker push handlers in `docs/sw.js` (no `addEventListener('push'|'notificationclick')`,
  no `showNotification`).
- **No** `pushManager` / `applicationServerKey` / `Notification.requestPermission` anywhere in `docs/`.
- **No** `push_subscriptions` table (migrations are only `0001_init`, `0002_ticker_quotes`,
  `0003_watchlist`), **no** subscribe/unsubscribe route in `worker-positions/src/index.js`.
- **`distil` is an EXTERNAL worker, not in this repo** — it's referenced in `worker-positions/src/auth.js:16`
  and CLAUDE.md phase-4 as "the sibling worker that already implements web-push + `push_subscriptions`".
  `distil` / `distil-staging` D1 databases DO exist in the same Cloudflare account (visible via
  `d1_databases_list`), so a future session with owner OK may inspect distil's schema/worker as a
  reference — but treat it as another project; don't copy its private data.

## The VAPID keys (owner delegated key-gen to Claude, 2026-08-19)

The owner explicitly said: **don't ask the CEO to generate VAPID keypairs — Claude drives it** using
`CLOUDFLARE_API_TOKEN` / `CLOUDFLARE_ACCOUNT_ID` (present in the session env). A VAPID keypair is a
standard ECDSA P-256 pair; generation is a local crypto op, not a Cloudflare API call. Procedure:

1. Generate the keypair. Cleanest: `npx web-push generate-vapid-keys` (from the `web-push` npm pkg you'll
   add to `worker-positions`), or Node `crypto.generateKeyPairSync('ec', {namedCurve:'prime256v1'})` +
   base64url export. You get `VAPID_PUBLIC_KEY` (goes into the PWA client, safe to commit as a public
   constant) and `VAPID_PRIVATE_KEY` (SECRET — never commit).
2. Set the private key + subject as worker secrets on `finviz-positions` (NOT in wrangler.toml, NOT in
   git). Either `wrangler secret put VAPID_PRIVATE_KEY` (interactive) or the CF API
   (`PUT .../workers/scripts/finviz-positions/secrets` with `{name,text,type:"secret_text"}` using the
   env token). Also set `VAPID_SUBJECT` (a `mailto:` — use the owner's email or a project contact).
   Get owner sign-off before writing the live secret (same discipline as any prod secret write).
3. The public key ships in the PWA as a plain constant (e.g. `VAPID_PUBLIC_KEY` near `POSITIONS_API` in
   `docs/index.html`) — it's designed to be public (`applicationServerKey`).

## What to build (backend: `worker-positions/`)

> **⚠ Migration number update (2026-08-20):** WS5-8 shipped first and took `0004_preclose_advisory.sql`.
> Use **`0005_push_subscriptions.sql`** here (not `0004`), and add it to `test/helpers/d1.js`'s
> `MIGRATIONS` array after `0004`. Everything else below is unchanged.

1. **Migration `0005_push_subscriptions.sql`** (applied out-of-band, like 0001–0004 — `wrangler deploy`
   does NOT run migrations; `test/helpers/d1.js`'s `MIGRATIONS` array runs it in tests). Table:
   `push_subscriptions(id, user_id, endpoint UNIQUE, p256dh, auth, created_at, last_seen_at, [ua])`,
   user-scoped (private, like `watchlist` — mirror that privacy posture, NOT `ticker_quotes`'s public one).
2. **Routes (owner-bearer, below the auth gate in `index.js`):**
   `POST /push/subscribe` (upsert a PushSubscription JSON), `POST /push/unsubscribe` (delete by endpoint).
   Follow the existing route-matching + `authenticate()` pattern. Tests in `test/index.test.js` style.
3. **Send logic** (`src/push.js`): a `sendPush(env, subscription, payload)` using VAPID (the Web Push
   protocol — encrypt per RFC 8291, VAPID JWT per RFC 8292). In a Worker you can use the `web-push`
   library if it runs on `workerd`, else implement the encryption with WebCrypto (subtle). **Verify
   `web-push` runs under workerd before committing to it** — if not, hand-roll with `crypto.subtle`
   (there are known Cloudflare-Workers web-push snippets). On a `410 Gone`/`404` from the push service,
   delete that subscription (stale endpoint cleanup).
4. **Two-tier send wired into the sweep** (`src/sweep.js`, design §8):
   - **Tier 1 — exit signal** (fires ONCE, when `advance()` first signals an exit → position enters
     `closing`): high-salience, actionable. Fire from the sweep right after a position transitions to
     `closing` (the sweep already knows this — it's where `exit_signal_date` gets stamped).
   - **Tier 2 — reminder** (any later day still in `closing`; decaying cadence day 1–2 then every other
     day; silent/digest; distinct tag so they collapse; ends at auto-confirm). Also earnings-approach
     push (reuse the engine's `days_to_earnings` ≤ `EARNINGS_WARN_SESSIONS`).
   - Push send must be **best-effort / non-fatal** — a push failure NEVER fails the sweep or blocks the
     D1 writes (the strip is the source of truth). Wrap in try/catch, count failures, move on. Consider
     firing pushes AFTER the D1 batch commits so a push error can't roll back state.
   - Idempotency: don't re-fire Tier-1 for a position already past its first `closing` day. The sweep's
     per-position state (`exit_signal_date`, `last_advanced_date`) + a `push_sent` marker (event or a
     column/`meta` flag) can gate it. Decide the marker; test it. Do NOT double-alert on same-day re-runs.

## What to build (PWA: `docs/index.html` + `docs/sw.js`)

1. **`docs/sw.js`:** add `self.addEventListener('push', …)` → `showNotification(title, {body, tag, data,
   actions})` and `self.addEventListener('notificationclick', …)` → focus/open the app to the Positions
   tab (the strip). Bump `CACHE` (currently `finviz-v73` — will be higher after PR C; check).
2. **`docs/index.html`:** a subscribe affordance on the Positions tab (signed-in) — "Turn on exit alerts"
   → `Notification.requestPermission()` → `registration.pushManager.subscribe({userVisibleOnly:true,
   applicationServerKey: urlBase64ToUint8Array(VAPID_PUBLIC_KEY)})` → `POST /push/subscribe` with the
   subscription JSON. An unsubscribe/"alerts on" state. Handle: permission denied, unsupported browser,
   and **iOS (needs install-to-home-screen before push works — surface that instruction on iOS Safari)**.
   Reuse `posApi` for the authed calls.
3. Release triplet (releases.json + sw.js CACHE + docs/CLAUDE.md) — user-facing feature.
4. Tests: `tests/test_pwa_positions.py` (or a new `test_pwa_push.py` ADDED to `tests.yml --ignore`) for
   the subscribe-button flow (mock `pushManager`/`Notification`); worker `test/push.test.js` for
   subscribe/unsubscribe routes + the stale-410 cleanup + Tier-1-once gating.

## Sequencing / gotchas
- **Backend-first, then PWA** (same deploy-ordering discipline as WS5-6/PR#340): the subscribe route must
  be live before the PWA calls it. Worker auto-deploys on merge (`deploy-workers.yml`).
- The sweep runs at 17:30 ET (held feed → `/advance`). Tier-1 push fires there. There is **no live push
  path until real held bars trigger a real `closing` transition** — so e2e is gated on live data, same as
  the rest of WS5. A dry-run `POST /advance?dry_run=1` writes nothing (and should send nothing).
- Keep the sweep's push send OUTSIDE the D1 `db.batch` transaction (best-effort, post-commit).
- `worker-positions` tests need **Node 22** (`test/helpers/d1.js` uses `node:sqlite`).
- Verify `web-push` under workerd BEFORE building on it; have the WebCrypto fallback ready.

## Read list for the cold session
- `planning/trade-lifecycle-engine.md` §8 (two-tier notifications — the spec).
- `worker-positions/CLAUDE.md` (phase status, sweep architecture, the persist-disjointness rules).
- `docs/CLAUDE.md` § Positions tab (the WS5-4a strip this pushes toward; release-triplet rules).
- `worker-positions/src/sweep.js` (`sweep()` — where a position enters `closing`; where to fire Tier-1).
- `worker-positions/src/index.js` (route-matching + auth gate pattern for the new /push routes).
- This session's session-notes entry (2026-08-19/20 WS5-4/5-5) for the PRs #340/#341/#342 context.

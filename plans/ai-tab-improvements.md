# AI Tab Improvements — PWA (Mobile) Focus

## Scope

In scope: 8 mobile PWA improvements (Items 1–8 below).
Deferred to backlog: Streamlit improvements, generation quality improvements (see Backlog section).

---

## Pre-Execution Checklist

Before writing any code:

```bash
git fetch origin
git rebase origin/claude/elegant-babbage-hlxnfy   # remote has new data commits
git log --oneline HEAD ^origin/claude/elegant-babbage-hlxnfy  # confirm clean base
git status                                         # confirm clean working tree
```

---

## Files in Scope

| File | Why it changes |
|------|---------------|
| `scripts/generate_ai.py` | Items 1, 2, 3, 8 — new prompts + JSON schema additions |
| `tests/test_generate_ai.py` | Corresponding tests for every generation change |
| `docs/index.html` | Items 1–8 — all PWA rendering |
| `plans/ai-tab-improvements.md` | This plan file, committed to repo |

---

## Progress Checklist

- [x] Phase 1 — Items 6, 7 (pure frontend fast wins)
  - [x] Item 6: Relative timestamp
  - [x] Item 7: One-tap native share
- [x] Phase 2 — Item 1 (structured takeaways)
  - [x] Item 1: Key signals bullets + collapsible briefing
- [x] Phase 3 — Item 8 (conviction tags)
  - [x] Item 8: Conviction tags on watchlist items
- [x] Phase 4 — Item 3 (industries structure)
  - [x] Item 3: Industries watchlist + rotation micro-phase
- [x] Phase 5 — Item 2 (delta card)
  - [x] Item 2: "What changed since yesterday" delta card
- [x] Phase 6 — Item 5 (phase history strip)
  - [x] Item 5: Rotation phase history strip
- [x] Phase 7 — Item 4 (historical navigation)
  - [x] Item 4: Historical briefing date navigation

---

## Task Specifications

### Item 1 — Structured bullet takeaways

**Purpose / motivation / what it fixes**
The current briefing is 3 dense paragraphs of prose. A mobile user checking the app quickly cannot extract the 2–3 key signals without reading the whole thing. Surfacing 3–5 one-line bullet "Key Signals" above the fold gives instant value before the full briefing.

**Detailed task description**
1. In `generate_ai.py`, add a new `key_signals` field to the briefing prompt. Instruct the model to return a JSON object with `key_signals` (array of 3–5 strings) and `briefing` (existing prose). Update the JSON schema for both sectors and industries.
2. Handle backward-compatibility: if `key_signals` is absent in an older JSON file, skip the bullet section and render briefing text only.
3. In `docs/index.html`, render the `key_signals` array as a `<ul>` with distinct styling (e.g., left-border accent) before the collapsible full briefing.
4. Make the full briefing text collapsible (`<details>`/`<summary>` or a "Read more" toggle) with bullets always visible.
5. Write tests in `tests/test_generate_ai.py` covering: correct `key_signals` array in output, correct briefing prose preserved, fallback when `key_signals` absent.

**Potential alternatives**
- Post-process the existing prose with a second LLM call to extract bullets (extra API cost, latency). Rejected — better to get structured output in one pass.
- Parse bullet-style prose from the existing briefing with regex. Fragile. Rejected.

**Acceptance criteria**
- [ ] `data/ai/{date}.json` contains `sectors.key_signals` (array of ≥3 strings)
- [ ] `data/ai/{date}.json` contains `industries.key_signals` (array of ≥3 strings)
- [ ] PWA shows bullet list above the fold when `key_signals` present
- [ ] PWA gracefully shows only prose when `key_signals` absent (old files)
- [ ] Full briefing is collapsible/expandable
- [ ] Tests pass: `python3 -m pytest tests/test_generate_ai.py -q`

**Happy path**
User opens AI tab → sees 3–5 bullet "Key Signals" instantly → taps "Read more" to see full briefing.

**Edge cases**
- Old JSON files (before this change) lack `key_signals` — must not break rendering.
- Model returns fewer than 3 bullets (e.g., sparse market day) — render whatever it returns, no minimum enforcement.
- Model returns `key_signals` as a string rather than array (prompt non-compliance) — catch in parsing, log warning, fall back to prose-only.

**Dependencies**
- None. Can be built independently.

**Error / failure cases**
- Gemini fails to return valid JSON for the new schema — `generate_ai.py` incremental completion retries; on repeated failure, file is written without `key_signals` and PWA falls back gracefully.

**Follow-up backlog items**
- Consider A/B testing with a "compact" vs "full" mode toggle in the PWA settings.

---

### Item 2 — "What changed since yesterday" delta card

**Purpose / motivation / what it fixes**
A daily returning user already knows yesterday's context. The highest-value content is the *delta*: what changed, what's new, what's reversed. Currently the user must mentally diff today's briefing against their memory of yesterday's. A delta card eliminates that friction.

**Detailed task description**
1. In `generate_ai.py`, after loading today's data, attempt to load yesterday's AI JSON file (search for the most recent file dated before today, within 5 calendar days).
2. If a prior file is found, include its `briefing` text as context in a new `daily_delta` prompt. Ask the model: "Given yesterday's analysis [text] and today's data [data], what are 2–3 key things that changed?"
3. Output: `sectors.daily_delta` — array of short strings (change observations).
4. If no prior file exists (first run, gap > 5 days), skip the prompt entirely and omit `daily_delta` from JSON.
5. In `docs/index.html`, render a "What changed" card at the top of the AI tab (above key signals) when `daily_delta` is present. Hide the card entirely when absent.
6. Write tests: correct `daily_delta` array in output; correct skip behavior when no prior file; fallback when field absent in JSON.

**Potential alternatives**
- Compute the delta programmatically by diffing the raw CSV data (no LLM needed). Cheaper but produces numeric diffs, not narrative insight. Could be added as a future enhancement. For now, narrative delta is more useful.
- Show yesterday's briefing side-by-side. Too much text on mobile.

**Acceptance criteria**
- [ ] When a prior day's file exists, JSON contains `sectors.daily_delta` (array of ≥2 strings)
- [ ] When no prior file exists, `daily_delta` field is absent (not null)
- [ ] PWA shows "What changed" card when field present
- [ ] PWA does not show the card when field absent
- [ ] Card appears above key signals / briefing
- [ ] Tests pass

**Happy path**
After daily run: delta card shows "Energy moved from rank 3 → rank 1 this week" and "Healthcare lost 2 spots in YTD rank, now at 8." User immediately grasps the change.

**Edge cases**
- Prior file exists but has no `briefing` (partial generation failure) — skip delta prompt, omit `daily_delta`.
- Weekend: Friday's file is the prior day's — the 5-day lookback window handles this correctly.
- Model returns a single item in the array — render it, no minimum enforced.

**Dependencies**
- Requires at least 1 prior AI JSON file to exist. (Files already exist from current production runs.)

**Error / failure cases**
- Gemini prompt for delta fails — log warning, omit `daily_delta` from JSON, PWA shows nothing (graceful).
- Prior file is corrupt/unparseable JSON — treat as "no prior file," skip delta prompt.

**Follow-up backlog items**
- Numeric delta card (computed from CSVs, no LLM) as a complement or fallback.

---

### Item 3 — Industries watchlist + rotation micro-phase

**Purpose / motivation / what it fixes**
Industries are more granular and actionable than sectors for traders. Currently the industries tab shows only a briefing — no structured watchlist, no phase label. This puts industries at a significant disadvantage vs sectors in the AI tab.

**Detailed task description**
1. In `generate_ai.py`, add two new prompts for the industries group:
   - **Rotation micro-phase**: Given top 5 industry movers by 7d rank delta and momentum leaders, classify into a micro-phase label (e.g., "Commodity rotation," "Defensive consumer," "Tech pullback," "Broad advance," "Sector dispersion"). Return `PHASE: [label]\nREASONING: [one sentence]`.
   - **Industries watchlist**: Top 3 industry setups. Same format as sectors watchlist: `1. NAME: [X] | THESIS: [one-liner]`.
2. Update JSON schema: `industries.rotation_phase` (same structure as `sectors.rotation_phase`), `industries.watchlist` (same array structure).
3. In `docs/index.html`, render industries watchlist and rotation phase using the same card components already used for sectors. Reuse the existing rendering functions — do not duplicate code.
4. Write tests: correct JSON schema for both new fields, correct skip when industries data is empty.

**Potential alternatives**
- Use the same 4 macro rotation phase labels for industries. Rejected — industries are more granular and deserve more specific labels.
- Display only the watchlist (skip the phase label). Feasible but the phase label adds navigation context.

**Acceptance criteria**
- [ ] JSON contains `industries.rotation_phase.label` and `industries.rotation_phase.reasoning`
- [ ] JSON contains `industries.watchlist` array (3 items with `name` and `thesis`)
- [ ] PWA industries tab shows rotation phase card (same layout as sectors)
- [ ] PWA industries tab shows watchlist card (same layout as sectors)
- [ ] Old JSON without these fields renders industries tab without crashing
- [ ] Tests pass

**Happy path**
User taps "Industries" toggle → sees "Defensive consumer" phase with "Staples and discount retail outperforming" reasoning, plus 3 specific industry setups below.

**Edge cases**
- Industries CSV is empty (no data yet) — skip both prompts, omit fields from JSON, PWA shows only briefing (current behavior).
- Model returns fewer than 3 watchlist items — render whatever count is returned.
- Phase label is something unexpected/long — truncate at 40 chars in render, show full in tooltip or subtitle.

**Dependencies**
- Item 1 (key_signals for industries) should be done first, as this item reuses the same industries JSON block.

**Error / failure cases**
- One of the two new prompts fails (Gemini error) — log, skip that field, write partial JSON, PWA falls back for that specific section.

**Follow-up backlog items**
- Add `industries.daily_delta` (Item 2 extended to industries).
- Industries conviction tags (Item 8 extended).

---

### Item 4 — Historical briefing navigation

**Purpose / motivation / what it fixes**
The current AI tab only shows today's analysis. If a user missed a day, was curious about a prior market period, or wants to see trend context in prose form, there's no way to access prior briefings. All the data already exists as JSON files in the repo.

**Detailed task description**
1. In `docs/index.html`, add a date navigation UI at the top of the AI tab:
   - A "← Prev" and "Next →" button (disable "Next" when already on the latest date).
   - Display the current date label between the buttons: "Jun 11, 2026".
2. On load, start at the latest available AI date (current behavior). Track a `currentAiDate` state variable.
3. On "← Prev" click: decrement date by 1 day, attempt to fetch that date's JSON. If not found (weekend/holiday/gap), keep decrementing up to 7 days until a file is found.
4. On fetch failure after 7-day scan: show a "No data available for this period" placeholder.
5. All rendering functions already receive the AI JSON object — pass the loaded historical JSON to the same render pipeline.
6. No changes to `generate_ai.py` or tests (pure frontend).

**Potential alternatives**
- A date picker dropdown. More complex to build for a PWA. Arrow navigation is simpler and touch-friendly.
- A "history" modal showing the last 14 days as a list. Higher information density but more complex. Add to backlog.

**Acceptance criteria**
- [x] Prev/Next buttons render in AI tab header
- [x] "Next" is disabled when on the latest date
- [x] Clicking "Prev" loads and renders the prior available date's JSON
- [x] If no file found within 7-day scan, shows "No data available" message
- [x] Date label updates correctly with each navigation
- [x] Navigation works across the sectors/industries toggle (same date, different group)

**Happy path**
User taps "← Prev" 3 times → navigates back through Monday/Friday/Thursday briefings → sees older analysis.

**Edge cases**
- User navigates to a very old date where JSON was in an older schema (no `key_signals`) — backward-compatibility fallback from Item 1 handles this.
- User is on a weekend date (no file) — scan skips to Friday correctly.
- User has slow connection and clicks rapidly — debounce or disable buttons during fetch.

**Dependencies**
- No code dependencies. Can be built independently.
- Logically after Items 1–3 (historical files won't have new fields, but that's fine with fallbacks).

**Error / failure cases**
- Network error fetching historical JSON — show "Failed to load data" error state with a retry button.

**Follow-up backlog items**
- "History" list modal showing 14-day calendar with which days have data.
- `data/ai/index.json` manifest file listing all available dates (avoids sequential probing).

---

### Item 5 — Rotation phase history strip

**Purpose / motivation / what it fixes**
The rotation phase label (🟢 Early Cycle / 🟡 Mid Cycle / 🟠 Late Cycle / 🔵 Defensive) changes infrequently but its transitions are highly significant. Currently there's no way to see how the call has evolved. A 14-day strip of phase pills makes trend and persistence immediately visible.

**Detailed task description**
1. In `docs/index.html`, add a "Phase History" section below the current rotation phase card (sectors view only).
2. On load, fetch the last 30 `data/ai/*.json` files. Since we can't list a directory from GitHub CDN, derive dates: start from today, walk backward day by day, fetch each date's JSON, stop after 30 attempts or when 14 successful fetches are accumulated.
3. Extract `sectors.rotation_phase.label` from each loaded file. Map label → emoji + short text:
   - "Early Cycle" → 🟢 Early
   - "Mid Cycle" → 🟡 Mid
   - "Late Cycle" → 🟠 Late
   - "Defensive" → 🔵 Def
4. Render as a horizontal scrollable strip of pill chips (oldest left, newest right). Highlight today's chip.
5. Cap at 14 visible days. Fetch happens async after the main AI content loads — do not block initial render.
6. No `generate_ai.py` or test changes (pure frontend).

**Potential alternatives**
- Store a pre-computed phase history JSON (e.g., `data/ai/phase-history.json`) built by a script, avoiding N individual fetches. More robust but requires a new script + CI step. Add to backlog as a future optimization.
- Show a simple text list "Last 7 days: 🟠🟠🟠🟡🟠🟠🟠" inline. Simpler but less visual.

**Acceptance criteria**
- [ ] Phase history strip renders below rotation phase card (sectors view only)
- [ ] Strip is absent in industries view
- [ ] Shows up to 14 days of pills
- [ ] Today's pill is visually highlighted/differentiated
- [ ] Scrollable horizontally on mobile
- [ ] Strip loads async — does not delay main AI content
- [ ] If < 2 historical files found, strip is hidden entirely

**Happy path**
User sees "🟠🟠🟠🟠🟠🟡🟠🟠🟠🟠🟠🟠🟠🟠" strip — immediately sees the market has been in Late Cycle for 2 weeks except one day.

**Edge cases**
- All historical files show same phase (boring) — still render; repetition is also signal.
- Gap in data (missed collection days) — just fetch fewer pills, render what's available.
- Historical files have `label` in different capitalization — normalize to title case before mapping.
- Network failures for historical files — silently skip failed dates, show what was loaded.

**Dependencies**
- Requires multiple days of AI JSON files in the repo (already exists).
- No code dependency on other items.

**Error / failure cases**
- All fetches fail (offline) — strip not shown, no error surfaced to user (strip is supplemental).

**Follow-up backlog items**
- `data/ai/phase-history.json` manifest to replace per-date fetches.
- Chart view (step chart) in Streamlit dashboard (deferred).

---

### Item 6 — Relative timestamp

**Purpose / motivation / what it fixes**
The AI tab currently shows "Generated: Jun 11, 2026, 1:37 PM ET". A mobile user's primary question isn't the exact timestamp — it's "is this fresh?" Showing "Updated 3h ago" alongside the absolute time answers the staleness question instantly without mental arithmetic.

**Detailed task description**
1. In `docs/index.html`, in the timestamp rendering logic (wherever `generated_at` is displayed), compute a relative string from `now - generated_at`:
   - < 1 min: "just now"
   - 1–59 min: "Xm ago"
   - 1–23 hours: "Xh ago"
   - 1–6 days: "Xd ago"
   - > 6 days: show absolute date only (relative loses meaning)
2. Render as: "Updated 3h ago · Jun 11, 2026, 1:37 PM ET" (relative first, absolute second in muted text).
3. Pure JS change. No test required (frontend-only per testing rules).

**Potential alternatives**
- Replace absolute timestamp entirely with relative. Rejected — absolute time is still useful for audit/debugging.
- Live-updating relative time (interval refresh). Unnecessary complexity — data is only updated once per day.

**Acceptance criteria**
- [ ] Timestamp shows relative format ("Xh ago") when data is < 24h old
- [ ] Absolute ET timestamp still visible (muted/smaller)
- [ ] "just now" shows for freshly generated data
- [ ] Relative display disappears / shows absolute only when data is > 6 days old
- [ ] Correct in all timezone scenarios (uses `generated_at` UTC value, displayed in ET)

**Happy path**
User opens app at 6pm ET after a 5pm data run → sees "Updated 1h ago · Jun 11, 2026, 5:00 PM ET".

**Edge cases**
- `generated_at` is null/malformed — fall back to absolute-only display.
- System clock is wrong (rare) — cap relative display at "0m ago" floor; never show negative.

**Dependencies**
- None.

**Error / failure cases**
- JS date parsing fails → catch, show absolute timestamp only.

**Verification**
Open `docs/index.html` in browser → manually set a mock `generated_at` that is 3 hours before current time → confirm "3h ago · [absolute]" renders.

**Follow-up backlog items**
- None.

---

### Item 7 — One-tap native share

**Purpose / motivation / what it fixes**
A user who wants to share the daily briefing with a colleague or save it to notes currently has no affordance. Adding a native share button makes this a one-tap action using the platform's built-in share sheet.

**Detailed task description**
1. In `docs/index.html`, add a share icon button in the AI tab header area.
2. On click:
   - Compose share text: title ("Finviz AI Briefing — Jun 11, 2026"), body (key signals bullets + briefing snippet, truncated to ~500 chars), URL (current page URL).
   - Call `navigator.share({ title, text, url })`.
3. Graceful fallback: if `navigator.share` is undefined (desktop Chrome, Firefox), fall back to `navigator.clipboard.writeText(fullText)` and show a brief "Copied!" toast notification.
4. Share only the currently visible group's content (sectors or industries, whichever is active).

**Potential alternatives**
- Copy-to-clipboard only (no native share). Works on desktop but misses mobile share sheet. The two-path approach is better.
- "Export as PDF". Overkill for a daily briefing.

**Acceptance criteria**
- [ ] Share button visible in AI tab header
- [ ] On mobile: tapping share opens the native share sheet with correct content
- [ ] On desktop (no `navigator.share`): button copies text to clipboard + shows "Copied!" toast
- [ ] Share text includes date, key signals (if present), and briefing snippet
- [ ] Share URL is the PWA URL
- [ ] Button disabled / shows loading state if no AI data has loaded yet

**Happy path**
User on iPhone taps share → iOS share sheet opens → user taps "Messages" → briefing text pasted into message.

**Edge cases**
- User cancels the share sheet — no error shown (share rejection is not an error).
- `navigator.clipboard` also unavailable — fail silently, no toast.
- Briefing text is very long — truncate to ~500 chars with "…" before sharing.

**Dependencies**
- Item 1 desirable before this for share text quality, but Item 7 can ship independently.

**Error / failure cases**
- `navigator.share` throws (non-user-cancel error) — log to console, fall back to clipboard copy.

**Verification**
Open `docs/index.html` in Chrome DevTools device emulation → tap share button → confirm sheet opens (or clipboard copy + toast on desktop).

**Follow-up backlog items**
- "Share as image" card. Backlog.

---

### Item 8 — Conviction tags on watchlist items

**Purpose / motivation / what it fixes**
The current watchlist gives 3 setups with thesis text but no signal strength. A user can't quickly distinguish "this is a strong confirmed move" from "this is early speculation." Adding a conviction tag makes the watchlist scannable at a glance.

**Detailed task description**
1. In `generate_ai.py`, update the sectors watchlist prompt to request a `conviction` field for each item. Expected values: "strong", "moderate", "speculative". Instruction: base conviction on agreement between multiple timeframes (high `momentum_score`, consistent rank_deltas = "strong"; mixed signals = "moderate"; early/single-timeframe signal = "speculative").
2. Update JSON schema: each watchlist item gains a `conviction` field.
3. In `docs/index.html`, render each watchlist item with a small colored tag:
   - "strong" → green tag
   - "moderate" → yellow/orange tag
   - "speculative" → blue/gray tag
4. Tags are hidden if `conviction` field absent (backward-compatible with old JSON).
5. Extend to industries watchlist when Item 3 is implemented.
6. Write tests: `conviction` field present and valid in output; fallback when absent.

**Potential alternatives**
- Compute conviction programmatically from `momentum_score` and `rank_agreement` (no LLM needed). More deterministic but loses the model's holistic judgment about a setup. Add to backlog.
- Use a numeric 1–5 scale instead of labels. Labels are more scannable on mobile.

**Acceptance criteria**
- [ ] JSON `sectors.watchlist` items include `conviction` field ("strong" | "moderate" | "speculative")
- [ ] PWA renders color-coded conviction tag on each watchlist item
- [ ] Tag is absent on watchlist items in older JSON files (no crash)
- [ ] Tag absent when model omits `conviction` field
- [ ] Tests pass

**Happy path**
User sees watchlist: "Energy — [strong] — Commodities catching a bid as rate fears ease" (green tag) and "Technology — [speculative] — Early signs of rotation back in" (blue tag).

**Edge cases**
- Model returns a `conviction` value outside the 3 allowed values — treat as "moderate" or hide tag.
- Model returns `conviction` as an integer — discard, hide tag.
- Very long thesis text pushes tag off screen — tag wraps or is inline with name.

**Dependencies**
- Item 3 (industries watchlist) should be done before extending conviction tags to industries.

**Error / failure cases**
- Watchlist prompt fails after retry — field omitted, existing watchlist behavior preserved.

**Verification**
Run `python3 -m pytest tests/test_generate_ai.py -q` + open PWA with today's JSON → confirm colored tags visible. Then test with an old JSON (no `conviction` field) → confirm no crash.

**Follow-up backlog items**
- Programmatic conviction cross-check (compare model's tag against data-computed score).

---

## Execution Order

| Phase | Items | Rationale |
|-------|-------|-----------|
| 1 | 6, 7 | Pure frontend, no generation changes — fast wins |
| 2 | 1 | Structured takeaways — foundational PWA layout rework |
| 3 | 8 | Conviction tags — small generation change on watchlist |
| 4 | 3 | Industries watchlist + phase — larger generation addition |
| 5 | 2 | Delta card — requires prior AI files to test |
| 6 | 5 | Phase history strip — requires multiple historical files |
| 7 | 4 | Historical navigation — needs backward-compat from Items 1–3 |

Each item = 1 focused commit. Run `python3 -m pytest tests/ -q` before every commit.

---

## Verification Commands

```bash
# After any generate_ai.py change:
python3 -m pytest tests/test_generate_ai.py -q

# Full test suite before each commit:
python3 -m pytest tests/ -q

# Confirm new JSON fields after a generation run:
cat data/ai/$(date +%Y-%m-%d).json | python3 -c "import json,sys; d=json.load(sys.stdin); print(list(d['sectors'].keys()))"
```

PWA verification: open `docs/index.html` in Chrome (served from a local HTTP server or directly) and manually verify each feature.

---

## Deferred Backlog

### Streamlit dashboard
- Collapsible briefing with key takeaways visible by default
- Rotation phase history chart (step chart, 30 days)
- Side-by-side sectors + industries briefings
- Export to markdown download button

### Generation quality
- Risk + opportunity structured fields (`top_opportunity`, `top_risk`)
- Sector → industry drill-down in sectors briefing
- Momentum divergence flag (computed, no LLM)
- Industries `daily_delta` (extend Item 2 to industries)

### Future PWA
- `data/ai/index.json` manifest (avoid per-date probing in Items 4 and 5)
- History list modal (calendar view of available dates)
- "Share as image" card
- Programmatic conviction cross-check

---

## Session Handoff

After each phase:
1. Check off completed items in the Progress Checklist above
2. Update `.session/session-notes.md`
3. Commit (plan file + code changes together or separately)
4. Keep draft PR open: `claude/ai-tab-improvements-gdi56v`

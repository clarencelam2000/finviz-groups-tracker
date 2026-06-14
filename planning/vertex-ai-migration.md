# Plan: Migrate AI Generation from Gemini AI Studio to Google Cloud Vertex AI

**Status:** Ready for implementation
**Owner:** Phase 1 = repo owner (GCP console); Phases 2–4 = any dev / Claude session
**Target file of change:** `scripts/generate_ai.py`, `.github/workflows/generate_ai.yml`, `tests/`, docs
**Base branch:** `claude/elegant-babbage-hlxnfy` (repo default)

---

## 1. Why we are doing this (motivation)

The daily AI analysis step (`scripts/generate_ai.py`, model `gemini-2.5-flash`)
calls the **Gemini AI Studio API** authenticated by a `GEMINI_API_KEY` secret.
Two concrete problems make this unreliable:

1. **The free tier is capped at 20 requests/day (RPD).** Google cut
   `gemini-2.5-flash` free tier from 250 → 20 RPD in late 2025. A normal run
   makes ~5–7 calls, but any retries, manual re-dispatches, or partial-run
   resumes push past 20, and the run then fails with
   `429 RESOURCE_EXHAUSTED ... 'quotaId':
   'GenerateRequestsPerDayPerProjectPerModel-FreeTier' ... limit: 20`. This is
   recorded in `data/ai_run_log.jsonl` (e.g. the 2026-06-13 run: 24 requests,
   `rate_limit_hits: 17`, 20+ minutes elapsed) and analyzed in
   `planning/ai-quota-exhaustion-fix.md`.

2. **We have $10/month of Google Cloud credits (Gemini Advanced/Pro
   subscription) that can ONLY be spent through Vertex AI** — they are not
   redeemable against the AI Studio Gemini API. Today those credits go unused.

**Decision:** Move `generate_ai.py` to **Vertex AI**. This:
- replaces the 20 RPD free wall with paid-tier quota (~2,000 RPD /
  high RPM — the daily wall disappears);
- routes the small spend (~$0.30–0.50/month at current volume) through the
  $10/month Vertex-only credits, so the workload is **effectively $0**;
- as a secondary benefit, lets us authenticate GitHub Actions with **Workload
  Identity Federation (WIF)** — short-lived OIDC tokens instead of a long-lived
  `GEMINI_API_KEY` secret.

**Explicitly NOT the motivation:** This is not primarily a security project.
Keyless auth is a nice-to-have. The driver is *quota reliability + using credits
we already pay for.*

### Cost expectation (so nobody is surprised)
- `gemini-2.5-flash` pricing ≈ $0.30 / 1M input tokens, $2.50 / 1M output tokens.
- ~7 calls/day, small prompts → **~$0.30–0.50/month**, fully absorbed by the
  $10/month credit. Vertex AI has **no perpetual free tier**; after any trial
  credit it bills per token, but our volume keeps this inside the monthly credit.

---

## 2. Current state (facts, verified against the code)

| Thing | Current value / location |
|---|---|
| SDK | `google-genai>=2.8.0,<3.0.0` (`requirements.txt:12`) |
| Model | `GEMINI_MODEL = "gemini-2.5-flash"` (`generate_ai.py:22`) |
| Auth read | `os.getenv("GEMINI_API_KEY")` (`generate_ai.py:845`) |
| Client init | `client = genai.Client(api_key=api_key)` (`generate_ai.py:858`) |
| Inter-call delay | `_INTER_CALL_DELAY = 13` with comment "Free tier: 5 requests/minute" (`generate_ai.py:103-104`) — **comment is factually wrong; real constraint is 20/day, not 5/min** |
| Retry/backoff | `_call_api()` — 3 retries, 30s/60s/120s; already aborts on daily quota via `DailyQuotaExhaustedError` and `GenerateRequestsPerDayPerProjectPerModel` detection |
| Run log | `_write_run_artifacts()` writes `data/ai_run_log.jsonl` (`generate_ai.py:734-750`); fields include `model`, `outcome`, `api_calls`, `rate_limit_hits` — **no `backend` field yet** |
| Tracking reset | `_reset_tracking()` (`generate_ai.py:172-176`) resets counters each run |
| Workflow auth | `.github/workflows/generate_ai.yml:46-47` passes `GEMINI_API_KEY` secret |
| Workflow perms | `permissions: contents: write` (`generate_ai.yml:13-14`) — **no `id-token: write`** |

**Important:** The existing daily-quota handling (`DailyQuotaExhaustedError`,
incremental partial-file resume) was added in prior work (PR #58) and **must be
preserved** — do not remove or rewrite it during this migration.

---

## 3. Target state

| Thing | Target |
|---|---|
| SDK | unchanged (`google-genai` already supports `vertexai=True`) |
| Auth (CI) | WIF via `google-github-actions/auth@v2`; no `GEMINI_API_KEY` |
| Auth (local) | `gcloud auth application-default login` (ADC), or keep `GEMINI_API_KEY` to use the AI Studio fallback path |
| Client init | dual-mode, selected by `GOOGLE_GENAI_USE_VERTEXAI` env var |
| Secrets | `WIF_PROVIDER`, `GCP_SA_EMAIL`, `GOOGLE_CLOUD_PROJECT` (none are credentials on their own) |
| Run log | adds `"backend": "vertex_ai" \| "google_ai_studio" \| "unset"` |

---

## 4. Phase 1 — GCP infrastructure (repo owner, one-time, ~45–75 min)

These steps run in the Google Cloud Console / `gcloud` CLI by the repo owner.
They are prerequisites; no code change works without them.

### G1 — Project, API, billing **(this is the step that captures the credits)**
1. Use or create a GCP project (record the **Project ID**, e.g. `finviz-tracker`).
2. **Attach the billing account that carries the $10/month Gemini credits to this
   project.** This is what makes the migration pay off — verify the credits show
   on this project's billing page.
3. Enable the API:
   ```bash
   gcloud services enable aiplatform.googleapis.com --project=<PROJECT_ID>
   ```
4. Region: **`us-central1`** (broad model availability, low latency from GitHub's
   US runners).

**Done when:**
`gcloud services list --project=<PROJECT_ID> --filter="NAME:aiplatform"` shows
`ENABLED`, and the billing page shows the credits attached.

### G2 — Service account (least privilege)
```bash
gcloud iam service-accounts create finviz-ai-runner \
  --display-name="Finviz AI Runner" --project=<PROJECT_ID>

gcloud projects add-iam-policy-binding <PROJECT_ID> \
  --member="serviceAccount:finviz-ai-runner@<PROJECT_ID>.iam.gserviceaccount.com" \
  --role="roles/aiplatform.user"
```
**Do NOT create or download a key JSON.** WIF makes keys unnecessary.
**Done when:** `gcloud iam service-accounts describe finviz-ai-runner@<PROJECT_ID>.iam.gserviceaccount.com` succeeds and the IAM binding shows `roles/aiplatform.user`.

### G3 — Workload Identity Federation
```bash
# Pool
gcloud iam workload-identity-pools create github-pool \
  --location="global" --display-name="GitHub Actions Pool" --project=<PROJECT_ID>

# Provider — note the attribute-condition scoping trust to THIS repo only
gcloud iam workload-identity-pools providers create-oidc github-provider \
  --workload-identity-pool="github-pool" --location="global" \
  --issuer-uri="https://token.actions.githubusercontent.com" \
  --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository,attribute.repository_owner=assertion.repository_owner" \
  --attribute-condition="assertion.repository=='clarencelam2000/finviz-groups-tracker'" \
  --project=<PROJECT_ID>

# Bind SA to the pool (uses the numeric project NUMBER, not the ID)
PROJECT_NUMBER=$(gcloud projects describe <PROJECT_ID> --format="value(projectNumber)")
gcloud iam service-accounts add-iam-policy-binding \
  finviz-ai-runner@<PROJECT_ID>.iam.gserviceaccount.com \
  --role="roles/iam.workloadIdentityUser" \
  --member="principalSet://iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/github-pool/attribute.repository/clarencelam2000/finviz-groups-tracker" \
  --project=<PROJECT_ID>
```
> **Critical:** the `attribute-condition` is the security boundary — without it,
> any GitHub repo could impersonate this SA. If the repo is ever renamed, this
> condition must be updated.
> **Gotcha:** the `principalSet` uses the numeric **project number**, not the ID.

Then add three **GitHub repository secrets** (Settings → Secrets and variables →
Actions):
- `WIF_PROVIDER` = `projects/<PROJECT_NUMBER>/locations/global/workloadIdentityPools/github-pool/providers/github-provider`
- `GCP_SA_EMAIL` = `finviz-ai-runner@<PROJECT_ID>.iam.gserviceaccount.com`
- `GOOGLE_CLOUD_PROJECT` = `<PROJECT_ID>`

**Done when:** a test workflow step using `google-github-actions/auth@v2`
authenticates without error.

### Fallback (only if WIF debugging exceeds ~1 hour)
Create an SA key JSON, store it as secret `GCP_SA_KEY`, and in G3/Phase 2 use
`credentials_json: ${{ secrets.GCP_SA_KEY }}` instead of the WIF inputs. This is
a long-lived credential needing rotation — use only as a last resort and set a
90-day rotation reminder.

---

## 5. Phase 2 — Code changes

### Task C1 — Dual-mode client init in `generate_ai.py`
**Where:** `generate_ai.py:845-858` (the `api_key`/`genai.Client` block).
**Goal:** select Vertex AI vs AI Studio by an explicit env toggle; keep the
existing graceful-skip behavior; preserve everything below it untouched.

Replace lines 845–858 with:
```python
    use_vertexai = os.getenv("GOOGLE_GENAI_USE_VERTEXAI", "").lower() in ("1", "true", "yes")
    api_key = os.getenv("GEMINI_API_KEY")
    gcp_project = os.getenv("GOOGLE_CLOUD_PROJECT")

    # Graceful skip when the selected backend is not configured (exit 0, not error).
    if use_vertexai and not gcp_project:
        print("GOOGLE_GENAI_USE_VERTEXAI=true but GOOGLE_CLOUD_PROJECT not set — skipping AI generation.")
        _write_run_artifacts("no_key", False, time.monotonic() - run_start, today)
        sys.exit(0)
    if not use_vertexai and not api_key:
        print("GEMINI_API_KEY not set — skipping AI generation.")
        _write_run_artifacts("no_key", False, time.monotonic() - run_start, today)
        sys.exit(0)

    try:
        import google.genai as genai
    except ImportError:
        print("google-genai not installed. Run: pip install google-genai")
        _write_run_artifacts("no_key", False, time.monotonic() - run_start, today)
        sys.exit(0)

    if use_vertexai:
        # Vertex AI: identity comes from ADC (CI: google-github-actions/auth; local: gcloud ADC).
        # If both the toggle and GEMINI_API_KEY are set, the toggle wins.
        client = genai.Client(
            vertexai=True,
            project=gcp_project,
            location=os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1"),
        )
    else:
        client = genai.Client(api_key=api_key)

    global _backend
    _backend = "vertex_ai" if use_vertexai else "google_ai_studio"
    print(f"  [backend] {_backend}")
```

> Verify the line numbers above are still accurate at implementation time; the
> file changes over time. Anchor on the `api_key = os.getenv("GEMINI_API_KEY")`
> statement rather than the literal line number.

### Task C2 — `_backend` module variable + reset
**Where:** near the other run-level tracking globals (`generate_ai.py:107-110`)
and `_reset_tracking()` (`generate_ai.py:172-176`).

Add the global:
```python
_backend: str = "unset"   # "vertex_ai" | "google_ai_studio" | "unset"; set during client init
```
Extend `_reset_tracking()`:
```python
def _reset_tracking() -> None:
    global _api_call_count, _rate_limit_hits, _field_log, _backend
    _api_call_count = 0
    _rate_limit_hits = 0
    _field_log = {}
    _backend = "unset"
```

### Task C3 — Add `backend` to run log
**Where:** `_write_run_artifacts()` `log_entry` dict (`generate_ai.py:738-750`).
Add one line after `"model": GEMINI_MODEL,`:
```python
        "backend": _backend,
```
Backward compatible — older entries simply lack the key.

### Task C4 — Correct the rate-limit comment (independent correctness fix)
**Where:** `generate_ai.py:103-104`.
The current comment ("Free tier: 5 requests/minute") is wrong; the real
free-tier constraint is **20/day**, and after this migration we're on Vertex
paid quota. Replace with:
```python
# Courtesy spacing between calls. The binding free-tier limit was 20 requests/DAY
# (RPD), not per-minute; on Vertex AI paid tier per-minute limits are high.
# Daily-quota exhaustion is handled separately (DailyQuotaExhaustedError, abort-no-retry).
_INTER_CALL_DELAY = 2
```
> Note for the implementer: this does **not** "save ~50s by fixing a per-minute
> throttle" — that framing (seen elsewhere) is based on a wrong premise. The
> change is purely a comment-correctness fix plus a modest spacing reduction that
> is safe on paid quota. `COLLECT_RETRY_DELAY=0` still suppresses the delay for
> tests (unchanged).

### Task C5 — Workflow `.github/workflows/generate_ai.yml`
1. Add `id-token: write` at the workflow `permissions` block (lines 13-14):
   ```yaml
   permissions:
     contents: write
     id-token: write   # required for WIF OIDC token issuance
   ```
2. Add an auth step **before** the "Generate AI analysis" step:
   ```yaml
   - name: Authenticate to Google Cloud
     uses: google-github-actions/auth@v2
     with:
       workload_identity_provider: ${{ secrets.WIF_PROVIDER }}
       service_account: ${{ secrets.GCP_SA_EMAIL }}
   ```
   *(SA-key fallback: replace the two `with:` inputs with
   `credentials_json: ${{ secrets.GCP_SA_KEY }}`.)*
3. Swap the env block (lines 46-48) from `GEMINI_API_KEY` to:
   ```yaml
       env:
         GOOGLE_GENAI_USE_VERTEXAI: 'true'
         GOOGLE_CLOUD_PROJECT: ${{ secrets.GOOGLE_CLOUD_PROJECT }}
         GOOGLE_CLOUD_LOCATION: us-central1
         FORCE_AI: ${{ github.event.inputs.force_ai == 'true' && '1' || '' }}
   ```

### Task C6 — Requirements check
Confirm the installed SDK exposes the `vertexai` param (it should at our pinned
range):
```bash
python3 -c "import google.genai as g, inspect; assert 'vertexai' in inspect.signature(g.Client.__init__).parameters; print('ok')"
```
Only bump the `google-genai` minimum in `requirements.txt` if this assertion
fails. No new packages are required (`google-auth` comes transitively; ADC is
supplied by the auth action in CI and by `gcloud` locally).

---

## 6. Phase 3 — Tests (`tests/test_generate_ai.py`)

Mock-based unit tests only — no live API calls. Mock `genai.Client` and assert on
the kwargs it receives. Reset `_backend` between tests
(`monkeypatch.setattr(generate_ai, "_backend", "unset")`).

Add:
1. **Vertex client when flag set** — with `GOOGLE_GENAI_USE_VERTEXAI=true`,
   `GOOGLE_CLOUD_PROJECT=test-project`, `GOOGLE_CLOUD_LOCATION=us-east1`: captured
   kwargs include `vertexai=True`, `project="test-project"`, `location="us-east1"`;
   `_backend == "vertex_ai"`.
2. **AI Studio client when flag absent (backward compat)** — only
   `GEMINI_API_KEY=test-key` set: kwargs include `api_key="test-key"`, no
   `vertexai`; `_backend == "google_ai_studio"`.
3. **Graceful exit: flag on, no project** — `SystemExit` with code 0.
4. **Graceful exit: no flag, no key** — `SystemExit` with code 0 (existing
   behavior preserved).
5. **Run log has `backend`** — extend the `_write_run_artifacts` test to assert
   the `backend` key is present with the expected value.

**Pass bar:** all existing tests still pass; new tests pass. Run:
```bash
python3 -m pytest tests/ -q
```

---

## 7. Phase 4 — Documentation

1. **`CLAUDE.md` "Automation" section** — replace the `GEMINI_API_KEY` reference
   with the three new secrets, and add a "Local AI development" note:
   - Vertex: `gcloud auth application-default login && export GOOGLE_GENAI_USE_VERTEXAI=true GOOGLE_CLOUD_PROJECT=<id>`
   - or AI Studio fallback: `export GEMINI_API_KEY=<key>` (leave the toggle unset).
   - Record the SA email and that spend is covered by the $10/mo credits.
2. **`generate_ai.py` module docstring (lines 1-6)** — replace "Exits 0 silently
   if GEMINI_API_KEY is not set" with a dual-mode description.
3. **`.session/session-notes.md`** — update the Current Status block: migration
   done, which auth mode is live (WIF vs SA-key).
4. **`.session/WORK_LOG.md`** — milestone entry: "Gemini AI Studio → Vertex AI
   migration complete (credits-funded, 20 RPD wall removed)".

---

## 8. Commit strategy

One logical commit per slice, per `.claude/rules/branch-commit-discipline.md`:
```
feat: add Vertex AI client backend to generate_ai.py      (C1–C4)
feat: migrate generate_ai workflow to Vertex AI WIF auth   (C5)
chore: bump google-genai minimum for vertexai support      (C6, only if needed)
test: add Vertex AI auth path coverage                     (Phase 3)
docs: document Vertex AI auth and local dev setup          (Phase 4)
```
Phase 1 (G1–G3) is manual GCP work — no commits.

---

## 9. Verification (end-to-end)

```bash
# 1. Tests green
python3 -m pytest tests/ -q

# 2. No stale API-key reference in the workflow
grep -n "GEMINI_API_KEY" .github/workflows/generate_ai.yml && echo "STALE — remove" || echo CLEAN

# 3. id-token permission present
grep -n "id-token" .github/workflows/generate_ai.yml

# 4. SDK supports vertexai
python3 -c "import google.genai as g, inspect; assert 'vertexai' in inspect.signature(g.Client.__init__).parameters; print('SDK ok')"

# 5. Graceful skip: flag on, no project
GOOGLE_GENAI_USE_VERTEXAI=true python3 scripts/generate_ai.py 2>&1 | head -2
# Expected: "...GOOGLE_CLOUD_PROJECT not set — skipping AI generation."
```

After the **first real GitHub Actions run on Vertex AI**:
```bash
python3 -c "import json; e=json.loads(open('data/ai_run_log.jsonl').read().splitlines()[-1]); print(e.get('backend'), e.get('outcome'))"
# Expected: vertex_ai complete
```
Then confirm in the **GCP billing console** that the spend lands on the **$10
credit**, not a card.

---

## 10. Rollback

The dual-mode design makes rollback cheap; `GEMINI_API_KEY` stays in GitHub
Secrets until after 2+ stable Vertex runs.

| Regression at | Action | Time |
|---|---|---|
| Workflow (C5) | Revert `generate_ai.yml`; restore `GEMINI_API_KEY` env | 5 min |
| Script (C1–C4) | Revert client-init diff; unset `GOOGLE_GENAI_USE_VERTEXAI` in workflow | 5 min |
| Rate-limit (C4) | Revert `_INTER_CALL_DELAY` to 13 | 2 min |

---

## 11. Cleanup (follow-up, after 2+ stable Vertex runs)

- Delete `GEMINI_API_KEY` from GitHub Secrets.
- Remove the AI Studio (`api_key`) branch from `generate_ai.py`, simplifying to a
  single backend; update docs again.
- Optional: tighten the WIF `attribute-condition` to a specific branch once the
  default branch is settled.

---

## 12. Out of scope (deliberately)

- **Model upgrade** (e.g. the 3.5-Flash analysis in
  `knowledge/GEMINI_UPGRADE_RESEARCH.md`) — a separate cost/quality decision.
- **Quota-waste fixes** — already shipped (incremental resume +
  `DailyQuotaExhaustedError`); this plan must preserve, not re-do them.
- **Custom IAM roles, budget-alert automation** — over-engineering at this scale;
  `roles/aiplatform.user` is sufficient.

---

## 13. Open items for the owner to confirm before Phase 2

1. Project ID and region (default `us-central1`).
2. WIF (recommended) vs SA-key fallback.
3. Confirm the $10/mo credit is attached to the chosen project's billing account.

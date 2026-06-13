# Gemini AI Studio → Google Cloud Vertex AI Migration Plan

**Created:** 2026-06-13  
**Branch:** `claude/gemini-vertex-api-migration-wrigfw`  
**Status:** Draft — awaiting implementation

---

## Executive Summary

**Recommendation: Proceed with migration — conditionally.**

The current implementation uses the `google-genai` SDK (already the right SDK for both platforms — no SDK change required). The migration reduces to: GCP infrastructure setup, GitHub Actions auth swap, and ~15 lines of code changes in `generate_ai.py`. The primary benefit is eliminating the `GEMINI_API_KEY` long-lived secret from GitHub Secrets in favor of keyless Workload Identity Federation (OIDC). Secondary benefit: higher rate limits (360+ RPM on Vertex AI vs 500 RPM free-tier AI Studio, but with guaranteed SLA headroom for scale).

**Proceed if:** GCP is already being used in your infrastructure, or you want to eliminate key-rotation overhead.  
**Defer if:** GCP is net-new infrastructure for this project — the WIF setup (~1–2 hours one-time) outweighs the benefits for a personal project making ~5–10 API calls/day.

**Note on branding:** As of April 2026, "Vertex AI" was rebranded to "Gemini Enterprise Agent Platform" by Google. The technical API, SDK parameter (`vertexai=True`), and endpoints remain identical. This plan uses "Vertex AI" throughout as the technical reference.

---

## Key Findings

1. **No SDK change required** — `google-genai>=2.8.0,<3.0.0` (already installed) supports Vertex AI via `vertexai=True` parameter. The code change is ~15 lines.
2. **Rate limit bug pre-exists migration** — `_INTER_CALL_DELAY = 13` with comment "Free tier: 5 req/min" is wrong for `gemini-2.5-flash` (actual free tier: 500 RPM). Fix in T6 regardless of migration decision.
3. **WIF is the hard part** — GCP infrastructure setup (T1–T3) is 60–90 minutes of one-time manual work. All code changes together are <30 minutes.
4. **Backward compatible** — Dual-mode design (AI Studio fallback) means CI can migrate without touching local dev; rollback takes 5 minutes.

---

## Current vs Target State

| Attribute | Current (AI Studio) | Target (Vertex AI) |
|---|---|---|
| SDK | `google-genai>=2.8.0,<3.0.0` | Same (no change) |
| Auth | `GEMINI_API_KEY` env var | Workload Identity Federation (OIDC) |
| Client init | `genai.Client(api_key=...)` | `genai.Client(vertexai=True, project=..., location=...)` |
| GitHub Secret | `GEMINI_API_KEY` | `WIF_PROVIDER`, `GCP_SA_EMAIL`, `GOOGLE_CLOUD_PROJECT` |
| Rate limit | 500 RPM (flash, free tier) | 360+ RPM (paid, SLA-backed) |
| Rate limit comment in code | "Free tier: 5 requests/minute" (**WRONG**) | Accurate Vertex AI quota note |
| Local dev auth | API key in env | ADC via `gcloud auth application-default login` |

---

## Phase Checklist (Execution Tracker)

Update this checklist as tasks complete. Each item maps to a concrete, verifiable state change.

### Phase 1 — Infrastructure (User-executed, GCP Console)
- [ ] **T1** GCP project identified/created; Vertex AI API enabled; billing active
- [ ] **T2** Service account `finviz-ai-runner@<project>.iam.gserviceaccount.com` created with `roles/aiplatform.user`
- [ ] **T3** Workload Identity Federation pool + provider configured; GitHub Actions can authenticate

### Phase 2 — CI/CD Migration
- [ ] **T4** `generate_ai.yml` updated: WIF auth step, Vertex AI env vars, `GEMINI_API_KEY` removed

### Phase 3 — Script & Test Changes
- [ ] **T5** `generate_ai.py` client init migrated; dual-mode auth; env var guards updated
- [ ] **T6** Rate limit comment and `_INTER_CALL_DELAY` corrected (independent of Vertex AI decision)
- [ ] **T7** `ai_run_log.jsonl` includes `backend` field
- [ ] **T8** `requirements.txt` verified; SDK supports `vertexai=True`
- [ ] **T9** Test suite updated; all tests pass

### Phase 4 — Documentation
- [ ] **T10** `CLAUDE.md`, session notes, and local dev docs updated

---

## Open Questions / Prerequisites

Confirm before starting implementation:

1. **GCP project**: Does one already exist, or must it be created? What will the Project ID be?
2. **WIF vs SA key**: Prefer WIF (T3 as specified) or simpler SA key JSON (T3 Alt A)? Affects T4.
3. **Migration timing**: Orthogonal to the current 2-week monitoring period (post-Phase 1 skip logic), but confirm it won't interfere.
4. **Cleanup timeline**: After migration confirms stable, when to remove the AI Studio fallback path and delete `GEMINI_API_KEY` from GitHub Secrets?

---

## Task Definitions

---

### T1: GCP Project & Vertex AI API Enablement

**Phase:** 1 — Infrastructure | **Owner:** User (manual) | **Effort:** Low (15–30 min, one-time)

#### Purpose / Motivation / What It Fixes

Vertex AI API calls require a GCP project with `aiplatform.googleapis.com` enabled and billing active. This is the foundational prerequisite — no code change is possible without it. There is no per-call "API key" equivalent for Vertex AI; identity is project-based.

#### Detailed Task Description

1. Identify or create a GCP project (e.g., `finviz-tracker-prod`).
2. Enable the Vertex AI API:
   ```bash
   gcloud services enable aiplatform.googleapis.com --project=<PROJECT_ID>
   ```
3. Confirm billing is active. Free trial credits ($300, 90 days) cover this project's usage level.
4. Choose a region. Recommended: `us-central1` (lowest latency from GitHub Actions East US runners; broadest model availability).
5. Record Project ID and region in the "Open Questions" section above.

#### Acceptance Criteria

- `gcloud services list --project=<PROJECT_ID> --filter="NAME:aiplatform"` returns `ENABLED`
- Billing account is associated with the project
- Project ID and region are recorded in this plan

#### Verification Command

```bash
gcloud services list --project=<PROJECT_ID> \
  --filter="NAME:aiplatform" \
  --format="table(NAME,STATE)"
# Expected: aiplatform.googleapis.com  ENABLED
```

#### Alternatives

- **Alt A: Use existing GCP project** — If you already have a personal GCP project, add Vertex AI API to it. Avoids creating new project; SA isolation is weaker but acceptable for a personal project. **Recommended if GCP already in use.**
- **Alt B: GCP Free Trial** — 90-day/$300 trial covers years of this project's usage. No upfront billing commitment. Requires upgrade to paid when trial expires.
- **Alt C: Defer indefinitely (stay on AI Studio)** — No GCP project needed. Keep `GEMINI_API_KEY`. Valid for a personal project; the security benefit of WIF is more meaningful in team/org contexts.

#### Alternative Assessment

Alt A is best if GCP is already present. Alt B is good for evaluation. Alt C is technically valid — the code change in T5 is small enough that deciding later costs little.

#### Decision

Proceed with T1 if any apply: (a) GCP already exists, (b) free trial available, (c) want to eliminate key rotation overhead. Defer if this would be your first GCP project — the WIF setup in T3 is the real cost.

#### Happy Path

User enables Vertex AI API → confirms billing → records project ID → proceeds to T2.

#### Edge Cases

- Google Workspace org admin policies may block personal GCP projects or restrict Vertex AI API. Check "Organization Policies" in Console.
- `gemini-2.5-flash` may not be available in all regions. `us-central1` has the broadest model availability.

#### Dependencies

None. First task.

#### Error / Failure Cases

- "Billing account required": Add a payment method. Free trial credits mean no actual charges at this usage level.
- "API not available in this region": Switch to `us-central1`.
- Org policy blocks: Use a personal (non-Workspace) Google account to create the project.

#### Follow-up Backlog Items

- Consider enabling Cloud Audit Logs for `aiplatform.googleapis.com` (free; useful for debugging).
- If usage grows, set up a budget alert at $5/month.

---

### T2: Service Account & IAM Configuration

**Phase:** 1 — Infrastructure | **Owner:** User (manual) | **Effort:** Low (10–15 min)

#### Purpose / Motivation / What It Fixes

GitHub Actions needs a Google identity to call Vertex AI. A dedicated service account (SA) with minimum permissions provides least-privilege access and limits blast radius if credentials are ever compromised.

#### Detailed Task Description

1. Create service account:
   ```bash
   gcloud iam service-accounts create finviz-ai-runner \
     --display-name="Finviz AI Runner" \
     --project=<PROJECT_ID>
   ```
2. Grant minimum required role:
   ```bash
   gcloud projects add-iam-policy-binding <PROJECT_ID> \
     --member="serviceAccount:finviz-ai-runner@<PROJECT_ID>.iam.gserviceaccount.com" \
     --role="roles/aiplatform.user"
   ```
3. Record the full SA email: `finviz-ai-runner@<PROJECT_ID>.iam.gserviceaccount.com`
4. **Do NOT create or download a key JSON file** — WIF (T3) makes keys unnecessary.

#### Acceptance Criteria

- SA exists: `gcloud iam service-accounts describe finviz-ai-runner@<PROJECT_ID>.iam.gserviceaccount.com` returns successfully
- IAM binding: `gcloud projects get-iam-policy <PROJECT_ID> --flatten="bindings[].members" --filter="bindings.members:finviz-ai-runner"` shows `roles/aiplatform.user`
- No key JSON file exists or is stored anywhere

#### Verification Command

```bash
gcloud iam service-accounts describe \
  finviz-ai-runner@<PROJECT_ID>.iam.gserviceaccount.com \
  --format="value(email,disabled)"
# Expected: finviz-ai-runner@<PROJECT_ID>.iam.gserviceaccount.com  False
```

#### Alternatives

- **Alt A: `roles/aiplatform.admin`** — Broader role; includes model management rights. Unnecessary for inference-only use case. Rejected.
- **Alt B: Custom IAM role** — Only `aiplatform.endpoints.predict`. Most restrictive possible. Maintenance overhead disproportionate to security gain at this scale.
- **Alt C: Service account key JSON** — Create a JSON key and store as GitHub Secret. Simpler than WIF (~5 min vs ~45 min). Long-lived credential requiring manual rotation. Valid fallback if WIF (T3) proves too complex.

#### Alternative Assessment

Alt A grants unnecessary permissions. Alt B is marginal security gain at too much maintenance cost. Alt C is the valid fallback if WIF setup stalls.

#### Decision

Use `roles/aiplatform.user` (minimum for inference). No key JSON. Proceed to T3 for WIF. Fall back to Alt C if WIF fails.

#### Happy Path

SA created → IAM binding applied → no key JSON → proceed to T3.

#### Edge Cases

- SA creation may require `iam.serviceAccounts.create` permission in a Google Workspace org. Check with org admin.
- Role name may evolve with "Gemini Enterprise Agent Platform" rebrand. Verify `roles/aiplatform.user` still exists in GCP IAM roles list if not found.

#### Dependencies

T1 (project must exist and have Vertex AI API enabled).

#### Error / Failure Cases

- "Permission denied on iam.serviceAccounts.create": Grant yourself `roles/iam.serviceAccountAdmin` or use the Console UI.
- "Role not found": Verify role name in GCP IAM → Roles → search "aiplatform.user".

#### Follow-up Backlog Items

- Add SA email to `CLAUDE.md` "Automation" section for future reference.

---

### T3: Workload Identity Federation (WIF) for GitHub Actions

**Phase:** 1 — Infrastructure | **Owner:** User (manual, ~30–45 min) | **Effort:** Medium (most complex step)

#### Purpose / Motivation / What It Fixes

WIF allows GitHub Actions runners to authenticate with GCP without any long-lived credential stored in GitHub Secrets. The runner carries a short-lived OIDC token (valid for one run); WIF exchanges it for a short-lived GCP access token. This eliminates `GEMINI_API_KEY` entirely and replaces it with two non-sensitive configuration values (`WIF_PROVIDER`, `GCP_SA_EMAIL`), neither of which is a credential on its own.

#### Detailed Task Description

1. Create a Workload Identity Pool:
   ```bash
   gcloud iam workload-identity-pools create github-pool \
     --location="global" \
     --display-name="GitHub Actions Pool" \
     --project=<PROJECT_ID>
   ```

2. Create a WIF Provider (GitHub is the OIDC issuer):
   ```bash
   gcloud iam workload-identity-pools providers create-oidc github-provider \
     --workload-identity-pool="github-pool" \
     --location="global" \
     --issuer-uri="https://token.actions.githubusercontent.com" \
     --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository,attribute.repository_owner=assertion.repository_owner" \
     --attribute-condition="assertion.repository=='clarencelam2000/finviz-groups-tracker'" \
     --project=<PROJECT_ID>
   ```
   **Critical:** `attribute-condition` scopes trust to only this repository. Without it, any GitHub Actions workflow in any repo could impersonate this SA.

3. Bind the SA to the WIF provider:
   ```bash
   # Get project number first:
   PROJECT_NUMBER=$(gcloud projects describe <PROJECT_ID> --format="value(projectNumber)")

   gcloud iam service-accounts add-iam-policy-binding \
     finviz-ai-runner@<PROJECT_ID>.iam.gserviceaccount.com \
     --role="roles/iam.workloadIdentityUser" \
     --member="principalSet://iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/github-pool/attribute.repository/clarencelam2000/finviz-groups-tracker" \
     --project=<PROJECT_ID>
   ```

4. Add to GitHub Secrets (Settings → Secrets and variables → Actions):
   - `WIF_PROVIDER`: `projects/<PROJECT_NUMBER>/locations/global/workloadIdentityPools/github-pool/providers/github-provider`
   - `GCP_SA_EMAIL`: `finviz-ai-runner@<PROJECT_ID>.iam.gserviceaccount.com`
   - `GOOGLE_CLOUD_PROJECT`: `<PROJECT_ID>`

#### Acceptance Criteria

- A test GitHub Actions run using `google-github-actions/auth@v2` completes without error
- `gcloud auth print-identity-token` works in the Actions run (confirms WIF exchange succeeded)
- No service account key JSON file exists or is stored
- All three secrets (`WIF_PROVIDER`, `GCP_SA_EMAIL`, `GOOGLE_CLOUD_PROJECT`) set in GitHub Secrets

#### Verification (run in GitHub Actions test step)

```yaml
- uses: google-github-actions/auth@v2
  with:
    workload_identity_provider: ${{ secrets.WIF_PROVIDER }}
    service_account: ${{ secrets.GCP_SA_EMAIL }}
- name: Verify auth
  run: gcloud auth print-identity-token --audiences=https://aiplatform.googleapis.com
```

#### Alternatives

- **Alt A: Service Account Key JSON as GitHub Secret** — Generate `key.json`, store entire contents as `GCP_SA_KEY` secret. ~5 min setup vs ~45 min for WIF. Long-lived credential requiring manual rotation every 90 days. Google explicitly recommends WIF over SA keys for GitHub Actions since 2023. **Valid fallback if WIF stalls.**
- **Alt B: Keep AI Studio API key** — Zero infrastructure change. `GEMINI_API_KEY` stays in GitHub Secrets. Requires manual rotation when key expires or is compromised. Fully valid for a single-developer personal project.
- **Alt C: Cloud Build triggered from GitHub** — Route AI generation through GCP Cloud Build (native GCP auth). Eliminates WIF entirely. Adds significant complexity (new workflow engine, Cloud Build billing). Not appropriate for this simple use case.

#### Alternative Assessment

Alt A is the recommended fallback — simpler setup, acceptable security for a personal project. Alt B is the no-change option (valid). Alt C is over-engineered.

#### Decision

Attempt WIF first. If WIF setup stalls or produces persistent auth errors within 45 minutes, fall back to Alt A (SA key JSON). Document which approach was used.

#### Happy Path

WIF pool created → provider created with repository attribute-condition → SA bound to pool → secrets added to GitHub → test workflow step authenticates successfully.

#### Edge Cases

- `attribute-condition` must exactly match the repository string: `clarencelam2000/finviz-groups-tracker`. If the repo is renamed, this condition breaks.
- **Project number ≠ Project ID.** The WIF member principal requires the numeric project number. Use `gcloud projects describe <PROJECT_ID> --format="value(projectNumber)"`.
- GitHub's OIDC token `sub` field contains `repo:owner/name:ref:refs/heads/branch`. The attribute mapping covers this.

#### Dependencies

T1, T2.

#### Error / Failure Cases

- "UNAUTHENTICATED: Request had invalid authentication credentials": WIF provider URL is wrong or `attribute-condition` syntax error.
- "Permission denied calling aiplatform.googleapis.com": SA does not have `roles/aiplatform.user`. Re-check T2.
- GitHub OIDC token not trusted: Confirm issuer URI is exactly `https://token.actions.githubusercontent.com` (no trailing slash).
- **Fallback trigger:** If WIF takes >1 hour to debug, switch to Alt A (SA key) and log "WIF debugging" as a backlog item.

#### Follow-up Backlog Items

- After migration stabilizes, consider scoping WIF attribute-condition further to a specific branch (e.g., `assertion.ref=='refs/heads/main'`) once the default branch is renamed.
- If Alt A (SA key) was used: set a 90-day rotation reminder.

---

### T4: GitHub Actions Workflow Update (`generate_ai.yml`)

**Phase:** 2 — CI/CD | **Owner:** Claude (code change) | **Effort:** Low (30 min)

#### Purpose / Motivation / What It Fixes

`generate_ai.yml` currently passes `GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}` to the script (line 47). After migration, the workflow must: (1) authenticate with GCP via WIF before the Python step, (2) inject Vertex AI env vars instead of an API key, and (3) require `id-token: write` permission for OIDC token issuance.

#### Detailed Task Description

Current relevant section:
```yaml
permissions:
  contents: write

# ...
- name: Generate AI analysis
  id: ai_gen
  env:
    GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}
    FORCE_AI: ${{ github.event.inputs.force_ai == 'true' && '1' || '' }}
  run: python scripts/generate_ai.py
```

Replace with:
```yaml
permissions:
  contents: write
  id-token: write   # required for WIF OIDC token issuance

# ...
- name: Authenticate to Google Cloud
  uses: google-github-actions/auth@v2
  with:
    workload_identity_provider: ${{ secrets.WIF_PROVIDER }}
    service_account: ${{ secrets.GCP_SA_EMAIL }}

- name: Generate AI analysis
  id: ai_gen
  env:
    GOOGLE_GENAI_USE_VERTEXAI: 'true'
    GOOGLE_CLOUD_PROJECT: ${{ secrets.GOOGLE_CLOUD_PROJECT }}
    GOOGLE_CLOUD_LOCATION: us-central1
    FORCE_AI: ${{ github.event.inputs.force_ai == 'true' && '1' || '' }}
  run: python scripts/generate_ai.py
```

If Alt A (SA key) was used in T3, replace the WIF auth step with:
```yaml
- uses: google-github-actions/auth@v2
  with:
    credentials_json: ${{ secrets.GCP_SA_KEY }}
```

#### Acceptance Criteria

- YAML passes syntax check
- `GEMINI_API_KEY` not referenced anywhere in the workflow file
- `id-token: write` permission present (WIF approach) or omitted (SA key approach)
- `google-github-actions/auth@v2` step appears before the Python step
- GitHub Actions workflow run succeeds end-to-end

#### Verification

```bash
# Syntax check
python3 -c "import yaml; yaml.safe_load(open('.github/workflows/generate_ai.yml'))" && echo "YAML OK"

# No stale API key reference
grep -n "GEMINI_API_KEY" .github/workflows/generate_ai.yml \
  && echo "FOUND — must remove" || echo "CLEAN"

# id-token permission present (WIF only)
grep -n "id-token" .github/workflows/generate_ai.yml
```

#### Alternatives

- **Alt A: SA key approach** — Skip WIF auth step; use `credentials_json: ${{ secrets.GCP_SA_KEY }}`. Compatible with T3 Alt A.
- **Alt B: Keep dual secrets (GEMINI_API_KEY + WIF)** — Keep old secret as fallback for local dispatch. Extends migration indefinitely; defeats the cleanup goal.

#### Alternative Assessment

Alt B leaves the old secret in place with no removal path. Not recommended as a final state.

#### Decision

Implement as described above (WIF or SA key depending on T3 outcome). Remove `GEMINI_API_KEY` reference. Single auth mechanism.

#### Happy Path

Workflow updated → WIF auth step authenticates → Python script receives `GOOGLE_GENAI_USE_VERTEXAI=true` and project env vars → calls Vertex AI → writes AI JSON → commits and pushes.

#### Edge Cases

- `id-token: write` must be at the workflow `permissions` level (where `contents: write` already lives). Adding it at the job level instead would shadow the workflow-level block.
- `GOOGLE_CLOUD_LOCATION: us-central1` is hardcoded (not a secret). This is intentional.
- WIF token is automatically refreshed by `google-github-actions/auth`; no manual token handling needed.

#### Dependencies

T1, T2, T3 (WIF configured before this can be tested end-to-end).

#### Error / Failure Cases

- "Error: google-github-actions/auth failed": Check `id-token: write` permission present. Verify `WIF_PROVIDER` and `GCP_SA_EMAIL` secret values match what was created in T3.
- "GOOGLE_CLOUD_PROJECT not set": Secret was not added or was named differently. Verify exact secret name.
- 429 rate limit on first Vertex AI run: existing exponential backoff handles this correctly.

#### Follow-up Backlog Items

- After 2+ stable Vertex AI runs confirmed: delete `GEMINI_API_KEY` from GitHub Secrets (Settings → Secrets → delete).
- Add an inline comment in the workflow explaining why `id-token: write` is needed.

---

### T5: `generate_ai.py` Auth & Client Migration

**Phase:** 3 — Script Changes | **Owner:** Claude (code change) | **Effort:** Low (~15 lines)

#### Purpose / Motivation / What It Fixes

Lines 830–843 read `GEMINI_API_KEY` and create `genai.Client(api_key=api_key)`. This must become `genai.Client(vertexai=True, project=..., location=...)` when running against Vertex AI. The graceful degradation logic (exit 0 silently if not configured) must check for `GOOGLE_CLOUD_PROJECT` in the Vertex AI path.

#### Detailed Task Description

Current code (lines 830–843):
```python
api_key = os.getenv("GEMINI_API_KEY")
if not api_key:
    print("GEMINI_API_KEY not set — skipping AI generation.")
    _write_run_artifacts("no_key", False, time.monotonic() - run_start, today)
    sys.exit(0)

try:
    import google.genai as genai
except ImportError:
    print("google-genai not installed. Run: pip install google-genai")
    _write_run_artifacts("no_key", False, time.monotonic() - run_start, today)
    sys.exit(0)

client = genai.Client(api_key=api_key)
```

Replace with:
```python
use_vertexai = os.getenv("GOOGLE_GENAI_USE_VERTEXAI", "").lower() in ("1", "true", "yes")
api_key = os.getenv("GEMINI_API_KEY")
gcp_project = os.getenv("GOOGLE_CLOUD_PROJECT")

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
    client = genai.Client(
        vertexai=True,
        project=gcp_project,
        location=os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1"),
    )
else:
    client = genai.Client(api_key=api_key)
```

Also add at module level (alongside `_api_call_count`):
```python
_backend: str = "unset"   # set during client initialization
```

And set after client creation:
```python
_backend = "vertex_ai" if use_vertexai else "google_ai_studio"
```

Update `_reset_tracking()` to reset `_backend`:
```python
def _reset_tracking() -> None:
    global _api_call_count, _rate_limit_hits, _field_log, _backend
    _api_call_count = 0
    _rate_limit_hits = 0
    _field_log = {}
    _backend = "unset"
```

Update `_write_run_artifacts()` `log_entry` dict to include `"backend": _backend` (see T7).

Update module docstring to reflect dual-mode auth.

#### Acceptance Criteria

- `python3 -m pytest tests/ -q` passes all 114+ tests
- When `GOOGLE_GENAI_USE_VERTEXAI=true` and `GOOGLE_CLOUD_PROJECT=<id>`: client uses Vertex AI
- When only `GEMINI_API_KEY` set: client uses AI Studio (backward compat)
- When neither set: exits 0 with clear message
- When `GOOGLE_GENAI_USE_VERTEXAI=true` but no project: exits 0 with clear message
- `_backend` module variable is set to `"vertex_ai"` or `"google_ai_studio"` after init

#### Verification

```bash
# Test SDK supports vertexai param
python3 -c "
import google.genai as genai, inspect
sig = inspect.signature(genai.Client.__init__)
assert 'vertexai' in sig.parameters, 'vertexai param missing from SDK!'
print('SDK check: vertexai param present ✓')
"

# Test graceful exit when Vertex AI configured but no project
GOOGLE_GENAI_USE_VERTEXAI=true python3 scripts/generate_ai.py 2>&1 | head -3
# Expected: "GOOGLE_GENAI_USE_VERTEXAI=true but GOOGLE_CLOUD_PROJECT not set — skipping AI generation."

# Test backward compat exit (no key, no project)
python3 scripts/generate_ai.py 2>&1 | head -3
# Expected: "GEMINI_API_KEY not set — skipping AI generation." (or "No new delta data...")

# Full test suite
python3 -m pytest tests/ -q
```

#### Alternatives

- **Alt A: Hard-switch only (remove AI Studio path)** — Remove all `GEMINI_API_KEY` support. Simpler final state. Breaks local development immediately if ADC not yet configured.
- **Alt B: Dual-mode with env var toggle (as described)** — Both paths coexist, selected by `GOOGLE_GENAI_USE_VERTEXAI`. No behavior change unless flag is set. Cleanest migration path.
- **Alt C: Auto-detect (no toggle)** — Try Vertex AI first if `GOOGLE_CLOUD_PROJECT` is set, fall back to API key. Ambiguous behavior; confusing error messages if both are partially configured.

#### Alternative Assessment

Alt A is too aggressive — breaks local dev. Alt C is fragile. Alt B (explicit toggle) matches how the google-genai SDK itself documents the two modes.

#### Decision

Alt B: explicit `GOOGLE_GENAI_USE_VERTEXAI` toggle. AI Studio path removed in a follow-up cleanup task after 2+ weeks of stable Vertex AI production runs.

#### Happy Path

GitHub Actions sets `GOOGLE_GENAI_USE_VERTEXAI=true` → client created with `vertexai=True` → calls succeed → `_backend = "vertex_ai"` → run log entry reflects correct backend.

#### Edge Cases

- ADC not configured locally when `GOOGLE_GENAI_USE_VERTEXAI=true` is set: `genai.Client` will fail at first API call (not at init time). Local dev requires `gcloud auth application-default login` first.
- `GOOGLE_CLOUD_LOCATION` defaults to `us-central1` if not set. This is intentional.
- If both `GOOGLE_GENAI_USE_VERTEXAI=true` and `GEMINI_API_KEY` are set: `use_vertexai` flag takes priority. Document in a comment.

#### Dependencies

T4 (workflow sets the env vars this code reads). T6 and T7 are batched with this task.

#### Error / Failure Cases

- `google.auth.exceptions.DefaultCredentialsError`: ADC not configured locally. Run `gcloud auth application-default login`.
- `google.api_core.exceptions.PermissionDenied`: SA lacks `roles/aiplatform.user`. Re-check T2.
- `google.api_core.exceptions.NotFound` on model: `gemini-2.5-flash` unavailable in the chosen region. Try `us-central1`.
- Existing tests that mock `genai.Client` may need updating (see T9).

#### Follow-up Backlog Items

- After 2+ weeks of stable Vertex AI runs: remove the AI Studio (`api_key`) path and delete `GEMINI_API_KEY` from GitHub Secrets.
- Add a startup log line: `print(f"  [backend] {_backend}")` for CI log observability.

---

### T6: Rate Limit Comment & `_INTER_CALL_DELAY` Correction

**Phase:** 3 — Script Changes | **Owner:** Claude (code change) | **Effort:** Very Low (5 min) | **Independent: valid regardless of Vertex AI decision**

#### Purpose / Motivation / What It Fixes

Line 99–100 in `generate_ai.py`:
```python
# Free tier: 5 requests/minute. Enforce >=13s between calls to stay safely under.
_INTER_CALL_DELAY = 13
```

This is **factually wrong** for the current setup. `gemini-2.5-flash` on AI Studio free tier is 500 RPM (≥1.2s between calls, not 13s). On Vertex AI paid tier, limits are 360+ RPM. The 13-second delay adds ~65 seconds of unnecessary overhead per run (5 tasks × 13s).

#### Detailed Task Description

Replace:
```python
# Free tier: 5 requests/minute. Enforce >=13s between calls to stay safely under.
_INTER_CALL_DELAY = 13
```

With:
```python
# Vertex AI gemini-2.5-flash: 360 RPM default (paid tier).
# AI Studio gemini-2.5-flash: 500 RPM (free tier).
# 2s spacing is a courtesy buffer; exponential backoff handles actual 429s.
_INTER_CALL_DELAY = 2
```

#### Acceptance Criteria

- No "Free tier: 5 requests/minute" comment remains in the file
- `_INTER_CALL_DELAY` is 2 (or another value that is accurate for the configured backend)
- `COLLECT_RETRY_DELAY=0` env var still suppresses the delay (existing behavior unchanged)
- Test suite passes

#### Verification

```bash
grep -n "_INTER_CALL_DELAY\|requests/minute\|Free tier" scripts/generate_ai.py
# Expected: updated comment with accurate rate limits; _INTER_CALL_DELAY = 2
```

#### Alternatives

- **Alt A: Remove delay entirely** — Let 429 responses trigger backoff naturally. Fastest execution. Risk: bursty behavior; 30s/60s/120s backoff is more disruptive than a 2s proactive delay.
- **Alt B: Configurable via env var** — `_INTER_CALL_DELAY = int(os.getenv("AI_INTER_CALL_DELAY", "2"))`. Flexible but over-engineered for this project scale.
- **Alt C: Keep 13s** — Safe, no change. Wrong comment persists. ~50 seconds slower per run than necessary.

#### Alternative Assessment

Alt A introduces risk at no meaningful benefit (5 calls/run is not "bursty"). Alt B is over-engineered. 2s (main task) is conservative enough to avoid 429s while recovering the ~50s overhead.

#### Decision

Update to 2s with accurate comment.

#### Happy Path

Comment updated → delay set to 2s → run time reduced by ~50s/run → no 429s observed.

#### Edge Cases

- `COLLECT_RETRY_DELAY=0` env var already disables delays for testing. This continues to work unchanged.

#### Dependencies

Can be committed alongside T5 in the same change.

#### Error / Failure Cases

- 429 hit after delay reduction: existing 30s/60s/120s backoff handles correctly. If this occurs in production, increase delay to 3s.

#### Follow-up Backlog Items

- None. Pure correctness fix.

---

### T7: Add `backend` Field to `ai_run_log.jsonl`

**Phase:** 3 — Observability | **Owner:** Claude (code change) | **Effort:** Very Low (5 min)

#### Purpose / Motivation / What It Fixes

`ai_run_log.jsonl` records `model`, `outcome`, `elapsed_seconds`, etc., but not which API backend was used. After migration, it needs to be auditable whether a given run used Vertex AI or AI Studio — useful for debugging failures and comparing run behavior across the migration boundary.

#### Detailed Task Description

In `_write_run_artifacts()` (line ~723), add `"backend": _backend` to `log_entry`:
```python
log_entry = {
    "timestamp": timestamp,
    "run_id": os.environ.get("GITHUB_RUN_ID", ""),
    "trigger": os.environ.get("GITHUB_EVENT_NAME", ""),
    "date": date_str,
    "model": GEMINI_MODEL,
    "backend": _backend,      # NEW: "vertex_ai" | "google_ai_studio" | "unset"
    "outcome": outcome,
    ...
}
```

`_backend` is set in T5 during client initialization.

#### Acceptance Criteria

- `ai_run_log.jsonl` entries after migration contain `"backend"` key
- Value is `"vertex_ai"` when `GOOGLE_GENAI_USE_VERTEXAI=true`, `"google_ai_studio"` otherwise
- Existing entries (without `backend` key) parse correctly (key absent = pre-migration)

#### Verification (after first Vertex AI production run)

```bash
python3 -c "
import json
with open('data/ai_run_log.jsonl') as f:
    last = json.loads(list(f)[-1])
assert last.get('backend') == 'vertex_ai', f'backend={last.get(\"backend\")}'
print('Run log backend:', last['backend'], '✓')
"
```

#### Alternatives

- **Alt A: Infer from date** — Don't add the field; entries before the migration date are AI Studio, after are Vertex AI. Fragile — requires knowing the exact migration date; not self-documenting.
- **Alt B: Log full client config** — Log `project`, `location`, model version. More detail, but exposes project ID in a committed data file (acceptable for personal project, but not for shared repos).

#### Alternative Assessment

Alt A is fragile. Alt B is over-specified. A single `backend` string field is the right balance.

#### Decision

Add `"backend": _backend` field as described.

#### Happy Path

`_backend` set in T5 → included in `_write_run_artifacts` call → logged in `ai_run_log.jsonl`.

#### Edge Cases

- `_write_run_artifacts` called on `"skipped"` outcome before client initialization: `_backend` will be `"unset"`. Initialize at module level and reset in `_reset_tracking()` (covered in T5).

#### Dependencies

T5 (sets `_backend`).

#### Error / Failure Cases

None. Additive field; no existing functionality affected.

#### Follow-up Backlog Items

None.

---

### T8: Requirements Verification & Dependency Update

**Phase:** 3 — Dependencies | **Owner:** Claude | **Effort:** Very Low (15 min)

#### Purpose / Motivation / What It Fixes

Confirm that `google-genai>=2.8.0,<3.0.0` (currently installed) supports `vertexai=True`. If the minimum version is insufficient, update it. This prevents silent breakage on a fresh install.

#### Detailed Task Description

1. Verify `vertexai=True` param present in installed SDK:
   ```bash
   python3 -c "
   import google.genai as genai, inspect
   sig = inspect.signature(genai.Client.__init__)
   print('vertexai param:', 'vertexai' in sig.parameters)
   "
   ```
2. If param is present: no change to `requirements.txt` needed.
3. If param is absent (requires newer version): update minimum bound in `requirements.txt`.
4. Confirm no additional packages needed. `google-genai` already depends on `google-auth` transitively; no explicit add required for WIF (ADC is handled by the `google-github-actions/auth` action in CI, and by `gcloud auth application-default login` locally).

#### Acceptance Criteria

- `vertexai` parameter confirmed present in the installed SDK version
- `pip install -r requirements.txt` succeeds without conflicts
- `python3 -m pytest tests/ -q` passes

#### Verification

```bash
pip install -r requirements.txt
python3 -c "
import google.genai as genai, inspect
sig = inspect.signature(genai.Client.__init__)
assert 'vertexai' in sig.parameters, 'vertexai param MISSING — update min version in requirements.txt'
print('SDK check passed ✓')
"
```

#### Alternatives

- **Alt A: Pin to exact version** — e.g., `google-genai==2.9.0`. Maximally reproducible; misses security patches.
- **Alt B: Widen upper bound to `<4.0.0`** — Allows major version upgrades; risky if v3.x has breaking changes.
- **Alt C: Keep current range `>=2.8.0,<3.0.0`** — No change if vertexai param is confirmed present at 2.8.0.

#### Alternative Assessment

Alt A adds manual maintenance. Alt B is too permissive. Alt C (no change) is correct if the SDK check passes.

#### Decision

Alt C (no change) if the verification passes. Update minimum only if the vertexai param requires a higher version.

#### Happy Path

SDK check passes → no `requirements.txt` change → existing CI passes unchanged.

#### Edge Cases

- If `vertexai=True` was added in a version higher than 2.8.0, update the lower bound accordingly.

#### Dependencies

None. Independent check.

#### Error / Failure Cases

- `vertexai param MISSING`: Update minimum version to the first 2.x release that includes it.

#### Follow-up Backlog Items

- Schedule a quarterly `requirements.txt` audit to catch SDK deprecations.

---

### T9: Test Suite Updates for Vertex AI Auth Paths

**Phase:** 3 — Quality | **Owner:** Claude (code change) | **Effort:** Low (45–60 min)

#### Purpose / Motivation / What It Fixes

The current 114 tests cover AI Studio paths only. After T5 introduces dual-mode auth, the new Vertex AI branch needs test coverage to prevent regressions: correct client creation per mode, graceful degradation for missing config, and correct `_backend` value.

#### Detailed Task Description

Add to `tests/test_generate_ai.py`:

1. **Test: Vertex AI client created when env var set**
   ```python
   def test_main_creates_vertex_ai_client_when_flag_set(monkeypatch):
       monkeypatch.setenv("GOOGLE_GENAI_USE_VERTEXAI", "true")
       monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "test-project")
       monkeypatch.setenv("GOOGLE_CLOUD_LOCATION", "us-east1")
       # monkeypatch _has_new_delta_data to return True
       # monkeypatch genai.Client to capture kwargs
       created_with = {}
       def mock_client(**kwargs):
           created_with.update(kwargs)
           return MagicMock()
       # Verify: created_with["vertexai"] is True
       # Verify: created_with["project"] == "test-project"
       # Verify: created_with["location"] == "us-east1"
   ```

2. **Test: Exit 0 when Vertex AI flag set but no project**
   ```python
   def test_main_exits_when_vertexai_set_no_project(monkeypatch):
       monkeypatch.setenv("GOOGLE_GENAI_USE_VERTEXAI", "true")
       monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
       with pytest.raises(SystemExit) as exc:
           generate_ai.main()
       assert exc.value.code == 0
   ```

3. **Test: AI Studio client created when no Vertex AI flag (backward compat)**
   ```python
   def test_main_creates_ai_studio_client_without_flag(monkeypatch):
       monkeypatch.delenv("GOOGLE_GENAI_USE_VERTEXAI", raising=False)
       monkeypatch.setenv("GEMINI_API_KEY", "test-key")
       # Verify: created_with["api_key"] == "test-key"
       # Verify: "vertexai" not in created_with
   ```

4. **Test: `_backend` set correctly in each mode**
   - `"vertex_ai"` when `GOOGLE_GENAI_USE_VERTEXAI=true`
   - `"google_ai_studio"` when only `GEMINI_API_KEY` set

5. **Test: `ai_run_log.jsonl` entry contains `backend` field**
   - Extend existing `_write_run_artifacts` test to assert `backend` key present.

#### Acceptance Criteria

- All 114 existing tests still pass
- 5+ new tests added covering Vertex AI auth paths
- `python3 -m pytest tests/ -q` shows all passing (119+)

#### Verification

```bash
python3 -m pytest tests/ -q
# Expected: X passed, 0 failed where X >= 119
python3 -m pytest tests/ -v -k "vertex" 2>&1 | grep -E "PASSED|FAILED"
# Expected: all vertex-related tests PASSED
```

#### Alternatives

- **Alt A: No new tests** — Mock at a higher level; existing tests already cover execution paths. Leaves the new conditional `if use_vertexai` branches uncovered.
- **Alt B: Integration tests with real Vertex AI** — Live API call in CI. Requires real GCP credentials in test environment; adds cost and latency; fails in PR runs from forks.

#### Alternative Assessment

Alt A leaves a coverage gap in new code. Alt B is too heavy for unit test scope. Mock-based unit tests are the right approach.

#### Decision

Add mock-based unit tests for new conditional auth logic.

#### Happy Path

Tests added → all 119+ tests pass → CI green.

#### Edge Cases

- Existing tests that call `main()` mock `sys.modules["google.genai"]`. New tests need to mock `genai.Client` at the correct path: `scripts.generate_ai.genai.Client` (or via `monkeypatch.setattr`).
- `_backend` module variable may retain state between tests. Reset with `monkeypatch.setattr(generate_ai, "_backend", "unset")`.

#### Dependencies

T5 (code to test must exist).

#### Error / Failure Cases

- `AttributeError: module 'generate_ai' has no attribute '_backend'`: Ensure T5 initializes `_backend = "unset"` at module level.
- Monkeypatch path for `genai.Client` may need adjustment depending on import structure.

#### Follow-up Backlog Items

- Add a CI-only Vertex AI smoke test workflow that runs against a real test GCP project after merges.

---

### T10: Documentation & CLAUDE.md Updates

**Phase:** 4 — Documentation | **Owner:** Claude (code change) | **Effort:** Low (20 min)

#### Purpose / Motivation / What It Fixes

`CLAUDE.md` currently references `GEMINI_API_KEY` as the only AI configuration needed. After migration, future Claude sessions need accurate auth information, the dual-mode toggle, and local dev setup. Stale docs cause session-start confusion.

#### Detailed Task Description

1. **`CLAUDE.md`** — "Automation" section:
   - Replace `secrets.GEMINI_API_KEY` with new secrets (`WIF_PROVIDER`, `GCP_SA_EMAIL`, `GOOGLE_CLOUD_PROJECT`)
   - Add a "Local AI development" note: either `gcloud auth application-default login && gcloud config set project <PROJECT_ID>` for Vertex AI, or set `GEMINI_API_KEY` to use AI Studio fallback.

2. **`scripts/generate_ai.py` module docstring** (lines 1–6):
   - Replace "Exits 0 silently if GEMINI_API_KEY is not set" with accurate dual-mode description.

3. **`.session/session-notes.md`**: Update Current Status block to reflect migration complete; record which auth mode (WIF vs SA key) is active.

4. **`.session/WORK_LOG.md`**: Add milestone entry: "Gemini AI Studio → Vertex AI migration complete".

#### Acceptance Criteria

- `grep -rn "GEMINI_API_KEY" CLAUDE.md` returns no results
- `CLAUDE.md` includes local dev instructions for both auth modes
- Module docstring is accurate
- Session notes reflect migration state

#### Verification

```bash
grep -n "GEMINI_API_KEY" CLAUDE.md && echo "STALE REF" || echo "CLEAN"
grep -n "GOOGLE_GENAI_USE_VERTEXAI\|GOOGLE_CLOUD_PROJECT" CLAUDE.md | head -5
```

#### Alternatives

- **Alt A: Minimal update** — Only update the module docstring; leave CLAUDE.md for next session.
- **Alt B: Full CLAUDE.md AI section rewrite** — Comprehensive docs including all env vars, both modes, pricing context. Over-scoped.

#### Alternative Assessment

Alt A leaves the next Claude session with stale instructions. Targeted updates (main task) are correct.

#### Decision

Targeted updates to CLAUDE.md Automation section, module docstring, and session notes.

#### Happy Path

CLAUDE.md updated → next session can orient from accurate docs without confusion.

#### Edge Cases

- CLAUDE.md is long. Use Edit tool with targeted old/new strings, not a full rewrite.

#### Dependencies

T1–T9 (documentation reflects final state; should be last).

#### Error / Failure Cases

None. Documentation-only change.

#### Follow-up Backlog Items

- After AI Studio fallback is removed (T5 follow-up), update docs again to reflect single-backend setup.

---

## Verification Commands (End-to-End)

Run after T5–T9 before pushing:

```bash
# 1. All tests pass
python3 -m pytest tests/ -q
# Expected: 119+ passed, 0 failed

# 2. No stale GEMINI_API_KEY in workflow
grep -n "GEMINI_API_KEY" .github/workflows/generate_ai.yml \
  && echo "STALE" || echo "CLEAN"

# 3. Rate limit comment updated
grep -n "_INTER_CALL_DELAY" scripts/generate_ai.py

# 4. SDK supports vertexai param
python3 -c "
import google.genai as genai, inspect
sig = inspect.signature(genai.Client.__init__)
assert 'vertexai' in sig.parameters
print('SDK check ✓')
"

# 5. Graceful exit when Vertex AI flag set but no project
GOOGLE_GENAI_USE_VERTEXAI=true python3 scripts/generate_ai.py 2>&1 | head -2
# Expected: "...GOOGLE_CLOUD_PROJECT not set — skipping..."

# 6. After first Vertex AI GitHub Actions run — confirm run log backend
python3 -c "
import json
with open('data/ai_run_log.jsonl') as f:
    last = json.loads(list(f)[-1])
print('backend:', last.get('backend', 'MISSING'))
# Expected: backend: vertex_ai
"
```

---

## Rollback Strategy

The dual-mode design (T5) makes rollback simple at every phase:

| Regression at... | Rollback action | Time |
|---|---|---|
| T4 (workflow) | Revert `generate_ai.yml`; restore `GEMINI_API_KEY` secret if deleted | 5 min |
| T5 (script) | Revert client-init diff; remove `GOOGLE_GENAI_USE_VERTEXAI` from workflow | 5 min |
| T6 (rate limit) | Revert `_INTER_CALL_DELAY` to 13 | 2 min |
| Post-migration cleanup | Re-add API key path | 15 min |

**Rollback is safe because:**
- `GEMINI_API_KEY` is not deleted from GitHub Secrets until after 2+ stable Vertex AI runs are confirmed
- AI Studio client path is preserved in code throughout migration (removed only as a follow-up task)
- Data files (`data/ai/*.json`) are unaffected by backend changes

---

## Commit Strategy

Each phase should be a separate commit following repo conventions:

```
T1–T3: User actions (no commits)
T4:    feat: migrate generate_ai workflow to Vertex AI WIF auth
T5–T7: feat: add Vertex AI client backend support to generate_ai.py
T8:    (only if requirements change) chore: update google-genai minimum version for Vertex AI support
T9:    test: add Vertex AI auth path coverage to generate_ai tests
T10:   docs: update CLAUDE.md and docstring for Vertex AI auth
```

---

*Research basis: google-genai SDK v2.x documentation, Google Cloud Vertex AI migration guides (June 2026), GitHub Actions OIDC workload identity federation documentation.*

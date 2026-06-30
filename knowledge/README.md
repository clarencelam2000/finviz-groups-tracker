# Knowledge

Research logs, architecture decisions, and hard-won findings that future Claude sessions or human readers should not have to rediscover.

## When to add here

- A Claude session spent significant effort researching APIs, model choices, library trade-offs, or Finviz behavior — save the findings here rather than letting them vanish with the context window
- An architectural decision was made (and alternatives rejected) — record the reasoning in `decisions/`
- A debugging session uncovered a non-obvious root cause — write a short post-mortem in `investigations/`

## Structure

```
knowledge/
  README.md                    ← this file
  decisions/                   ← Architecture Decision Records (ADRs)
  investigations/              ← debugging post-mortems and root cause analyses
    playwright-cloud-session-testing.md ← Playwright/Chromium gotchas specific to running
                                           tests in a Claude Code cloud session (browser
                                           revision mismatch, CDN reachability, route glob
                                           patterns) — read before writing or debugging any
                                           Playwright test in this kind of session
  GEMINI_UPGRADE_RESEARCH.md   ← Gemini model research (June 2026)
```

## ADR format (decisions/)

```markdown
# ADR-NNN: <Decision title>

**Date**: YYYY-MM-DD
**Status**: Accepted | Superseded by ADR-NNN

## Context
What problem were we solving and what constraints existed?

## Decision
What did we choose?

## Alternatives considered
What else was evaluated and why was it rejected?

## Consequences
What trade-offs does this create going forward?
```

## Research log format

Free-form is fine. Include: date, scope, what was found, what was ruled out, and any caveats or expiry (e.g., "verified against Gemini API as of June 2026 — re-check if >6 months old").

---
name: restate-intent
description: >-
  Use BEFORE acting when the owner's message is long, rambling, dictated, or
  bundles several asks — i.e. "I'm going to yap", a wall of text, a mix of
  question + command + complaint, pasted notes/screenshots with a vague ask,
  ambiguous referents ("this", "that one"), a request that reverses or
  conflicts with an earlier decision, two readings that would lead to
  materially different work, or a hard-to-undo action asked for casually.
  Also before a CSV schema change and before delegating a big task to a
  subagent, and when resuming after a context reset. Restates the owner's
  goal and the problem being solved in plain language, separates what they
  said from what is being inferred, flags low-confidence spots and questions,
  then waits for a correction. Also invocable by hand as /restate-intent.
  Skip for short, unambiguous asks, mid-flow follow-ups, and a plain "yes, go".
---

# Restate intent

The owner thinks out loud and fast. A ten-minute ramble contains the real goal
somewhere inside it, plus asides, half-decisions and things they'd drop if asked.
Misreading it costs a wasted PR; confirming it costs one sentence. So: say back
what you understood, in your own words, before doing anything.

## Output (plain language — no section numbers, invariant names, or code terms)

Keep each part to a sentence or two. No hard length cap overall — a big ramble
earns a longer restatement — but never pad.

1. **Your goal** — what you're trying to end up with, in your own words.
2. **The problem** — what's hurting or missing today that makes this worth doing.
3. **What I'm treating as fixed** — things you said that I'm taking as given.
   Quote the owner's own words where you can.
4. **What I'm inferring** — things you did *not* say that I'm assuming. Mark each
   plainly as a guess so it can be corrected.
5. **What I'm not going to touch** — scope edges, so silence isn't read as consent.
6. **Questions / low confidence** — anything ambiguous, or where two readings would
   lead to materially different work. Say "I'm not sure about X because Y."
   If there are none, say "no open questions" — don't invent some.

## Then: stop or continue?

- **Stop and wait for a correction** if anything is low-confidence, any inference
  would change what gets built, the action is hard to undo (prod ops, merges,
  schema changes, deletes), or the message reversed an earlier decision.
- **Otherwise continue** in the same turn — state the restatement, then proceed;
  the owner can interrupt. Never continue on a guess that changes what gets built.
- Ground-truth CSV schema changes still need explicit owner approval first
  (`.claude/rules/data-pipeline.md`), restatement or not.

## Don't

- Don't parrot the message back. If the restatement adds nothing the owner didn't
  literally say, it is noise — sharpen it into goal + problem, or skip the skill.
- Don't restate short, clear asks or every follow-up; it becomes a ritual that
  gets skimmed and stops catching misreads.
- Don't ask questions you can answer by reading the repo or the docs.
- Don't relitigate prior decisions here; just flag where the ask points
  a different way than a recorded decision, and say which you're following.
- Don't bury the questions. If the owner reads only one part, it should be #6.

## Other agents

Non-Claude agents: read this file and follow it — same trigger, same output.

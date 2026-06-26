# Product Intro Copy

> Canonical source for the onboarding intro content shown in the **"Start Here"** section
> of the hub and in the first-run carousel. The `WELCOME` constant in `docs/index.html`
> is kept **verbatim-synced** with this file — edit body/desc strings here, then update
> `WELCOME` to match exactly. See `CLAUDE.md` § Code quality for the sync rule.
>
> `tests/test_pwa_intro.py::test_welcome_body_strings_in_product_intro_copy` enforces
> the sync automatically: every `body` and `desc` string in `WELCOME` must appear
> verbatim in this file (same mechanism as `moaty-metrics.md` ↔ `GUIDE`).

---

## O'Neil / IBD citation (Slide 2 source)

> "37% of a stock's price movement is directly tied to the performance of the industry
> group the stock is in. Another 12% is due to strength in its overall sector. Therefore,
> about half of a stock's move is due to the strength of its respective group."

Source: William O'Neil, *How to Make Money in Stocks* / Investor's Business Daily (IBD).
Chosen because it is swing-trading-relevant by origin (O'Neil's CANSLIM methodology),
which matches the user's framing. Referenced in Slide 2 as: *"37% from the group, 12%
from the sector (William O'Neil / IBD)".*

---

## Slide 1 — Welcome

See where the market's money is actually moving — every sector and industry group, ranked daily, with history to show what's rising before it's obvious.

---

## Slide 2 — Why groups matter

About half of any stock's price move comes from its industry group and sector — 37% from the group, 12% from the sector (William O'Neil / IBD). The highest-leverage question isn't whether the company is good — it's whether its group is strong.

---

## Slide 3 — What's different from Finviz

Finviz shows today's snapshot — who's winning right now. We keep the history and track how the rankings change over time, so you can spot capital rotating into a group before the headline numbers move. That derived layer — momentum, rotation, and relative strength vs the S&P 500 — is what you won't find on Finviz.

---

## Slide 4 — Your 7 tabs

| Tab | Description |
|-----|-------------|
| Today | Every group ranked by current strength. |
| Movers | Biggest rank climbers and fallers. |
| Momentum | Broad strength scores and the Rotation view. |
| Strength | Proven, sustained leaders. |
| AI | A plain-English daily rotation briefing. |
| Lookup | Type any ticker — see if its group is a tailwind or headwind. |
| Picks | Daily stock picks inside leading groups — the strongest names in the strongest groups. |

---

## Slide 5 — You're set

Tap the ⓘ icon anytime to open the Guide (what every number means) or replay this intro.

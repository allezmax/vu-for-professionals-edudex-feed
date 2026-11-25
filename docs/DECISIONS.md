# EDU-DEX feed -- what's going on, in plain language

This file exists so that anyone covering for Max (Edo, or whoever's next)
can understand this project **without needing any Claude account** -- it's
a condensed version of a longer running decision log Max has kept
elsewhere. If you're reading this because you're covering while Max is
away: welcome, and see `edo-handover.md` in this same folder for the actual
step-by-step "what to do" guide. This file is the "why things are the way
they are" reference.

## What this is
A daily, automatic process that reads VU's "for Professionals" course pages
(the School of Business and Economics for Professionals, SBE), turns each
one into the data format EDU-DEX (a national course database) expects, and
publishes it. It runs by itself every day -- nobody needs to click anything
for it to keep working. `edo-handover.md` explains what to do if it breaks.

## Current status (as of 2026-11-24)
- The feed is **built and technically working**, but **not yet registered
  with EDU-DEX itself** -- that's the last step before this actually shows
  up on EDU-DEX's public database. It's being held back deliberately until
  Max's team finishes checking the data (see "Team review" below).
- 63 programs are included; 3 look-alike programs were deliberately left out
  because they're not actually run by VU's SBE for Professionals (see table
  below).
- A handful of specific things are still open questions -- see "Open
  questions" below. None of them are urgent; they're all things to decide,
  not things that are currently broken.
- **As of 2026-11-24, problems are reported automatically**: every day's
  run checks itself and posts to the "EDU-DEX feed alert" Teams channel if
  something's actually broken or needs a human look (a page the scraper can
  no longer read, a hand-typed price/fact that no longer matches what's
  live on vu.nl). No message = nothing needs attention. See
  `edo-handover.md`, section 1, for exactly what the messages mean and what
  to do about them.

## Programs deliberately left out of the feed
| Program | Why |
|---|---|
| Actualiteitenlezingen Pensioenrecht | Belongs to VU Law Academy, not SBE |
| International Executive Master in Auditing (IEMA) | Actually run by Maastricht University |
| Investment masterclasses | Actually run by CFA Society NL |

## Pricing rules, if you ever need to check or correct a price
- Always the **full/standard price**, never an early-bird or member
  discount, even if the course's own page shows a discount too.
- If a course is billed per year or per module, the price in the feed is
  the **total for the whole course**, not one year/module.
- If a course's page quotes a price range ("between €30,000 and €35,000"),
  the feed uses the **top of the range**.

## Team review (the main reason the feed isn't fully live yet)
Max's team is going through a spreadsheet (a colour-coded Excel file, not
part of this repo) marking each of the 63 programs as "Good to go," "Needs
fixes," or "Exclude for now." Once that's done, anything not "Good to go"
should be added to this repo's `excluded_programs` list (see
`edo-handover.md` for exactly how) so it doesn't go live with bad data. This
hasn't happened yet as of 2026-11-19.

## Open questions (not broken, just undecided -- leave these alone unless Max weighs in)
- **Executive Master in Coaching**: the course's own page says, in its own
  words, that it does *not* count as a real "MSc" degree under Dutch law --
  but the feed currently guesses MSc anyway, because that's what the
  automated system assumes from the course's name. Needs a person to
  confirm the right replacement value (most likely something like
  "certificate of participation"). Same course's real location (a venue in
  Ouderkerk aan de Amstel, not VU's main campus) is also not yet corrected.
- **Zijlstra PE programma**: this course is priced three different,
  incompatible ways on its own page (a yearly subscription, a per-day rate,
  or a per-webinar rate) -- nobody's decided yet what single price, if any,
  to put in the feed.
- Both of the above are intentionally left blank/unconfirmed rather than
  guessed at -- don't fill in a value yourself unless Max or someone with
  real knowledge of the course confirms it first.

## Where things live
- **The actual feed (the thing that matters)**: this GitHub repository.
  Runs automatically every day.
- **This file**: the plain-language "why" reference, for anyone without
  deep technical background or a paid Claude account.
- **`edo-handover.md`**: the practical "what to do" guide -- read that one
  if something looks broken.
- A more detailed, technical decision log also exists in a Claude Project
  Max uses, with finer-grained history (schema corrections, exact
  reasoning for each override). This file is a deliberately simplified
  summary of it for anyone without access to that.

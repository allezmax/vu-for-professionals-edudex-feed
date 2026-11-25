# EDU-DEX feed -- handover for Edo while Max is away (2 months)

You already have access to the repository, so this is the "what to actually
do" guide. No coding background needed -- everything here is done by
clicking around on the github.com website, the same as editing a document.

**The repo**: `https://github.com/allezmax/vu-for-professionals-edudex-feed`

For the full "why things are the way they are" background, see
`docs/DECISIONS.md` in that same repository -- it's written for exactly this
situation (no technical background, no Claude account needed).

---

## The short version

A program on GitHub's side rebuilds and republishes this feed **automatically, every day**. You don't need to do anything most days, and you don't need to go looking for problems either -- **if something needs your attention, a message appears by itself in the "EDU-DEX feed alert" Teams channel.** Your job is just:
1. Watch that Teams channel (you're already in it). No news in there is good news -- a clean day posts nothing at all.
2. If a message shows up, use it to figure out what's going on (see section 1 below for how to read it), then either fix it using one of the recipes below, or -- if you're not sure -- just leave it and make a note for Max. Nothing here is so urgent it can't wait if you're unsure.

---

## 1. Where alerts show up, and how to check manually just in case

**Primary: the "EDU-DEX feed alert" Teams channel.** Every day's automatic run checks itself for two kinds of problems and posts a message there if it finds either:
- **"BUILD FAILED"** -- something broke badly enough that the feed itself couldn't be rebuilt. GitHub Pages keeps serving yesterday's last-good version in the meantime, so nothing wrong goes live -- but it does mean the feed is stuck until this is fixed.
- **"content changed"** -- the automatic checker spotted something worth a human look: a program's page changed in a way the scraper can no longer read correctly, or a price/fact we typed by hand in `overrides.yaml` no longer matches what's now live on vu.nl. The message itself lists which program(s) and why.

A routine, correctly-handled change (like vu.nl's own prices ticking up for the new year, for a program where we're *not* overriding the price) does **not** trigger a message -- the scraper just picks up the new number on its own. You'll only hear about things that actually need a look.

**Backup, in case Teams is ever down or you just want to double-check:**
1. Go to `https://github.com/allezmax/vu-for-professionals-edudex-feed/actions`
2. Look at the top entry in the list. A **green checkmark** means the most recent daily run succeeded. A **red X** means it failed.
3. If it's red, click on that entry, then click on the job name inside it, and read the red/failed step near the bottom of the log. It will usually say something like "XSD validation failed" and name a specific file. Don't panic -- see section 3 below for the most common cause and fix.
4. You can also just read `https://allezmax.github.io/vu-for-professionals-edudex-feed/report.md` in your browser any time -- it's a plain-English summary of the current state (no login needed), including anything that needs a human to confirm.

---

## 2. The one file you'll mostly ever need to touch

**`config/overrides.yaml`** -- this is where you correct or confirm information for one specific program (a wrong price, a wrong contact, etc.) without touching any code. To open it for editing:

1. Go to the repo link above.
2. Click the `config` folder, then click `overrides.yaml`.
3. Click the **pencil icon** (top-right of the file, "Edit this file").
4. Make your change (see the two recipes below for exactly what to type).
5. Scroll to the bottom of the page. Under "Commit changes," leave **"Commit directly to the main branch"** selected, type a short message describing what you changed (e.g. "Fix price for Bestuur & Toezicht"), and click the green **Commit changes** button.
6. That's it -- the next daily run (within 24 hours) will pick it up automatically. If you want it to happen sooner, go to the Actions tab (link above), click "Build and publish EDU-DEX feed" on the left, then the "Run workflow" button on the right, and confirm.

**Important: indentation matters in this file.** Every line in the `programs:` section lines up exactly 2 spaces from the left margin, consistently. When in doubt, copy the exact spacing of the line just above the one you're adding/editing, and never use the Tab key (use spaces).

### Recipe A: correcting a price for a program that's already listed
Find the program's line (use Ctrl+F / Cmd+F in your browser to search for the program's name, which is in a comment after `#`). It looks like this:

```yaml
  70a92744-0255-46f2-b859-94d5f7747935: {tuitionFeeAmount: 4950}    # Bestuur & Toezicht
```

Just change the number after `tuitionFeeAmount:`. Don't change anything else on the line.

### Recipe B: adding a correction for a program that ISN'T listed yet
You'll need that program's id (a long code like `70a92744-0255-...`) -- find it in `report.md` (see section 1 above), which lists every program by name next to its id. Then add a new block under the `programs:` section, matching this exact pattern (replace the id and the number, keep everything else, including the 2-space indent and the colon):

```yaml
  <paste-the-program-id-here>: {tuitionFeeAmount: 1234}    # <program name, for your own reference>
```

### Recipe C: "something's wrong with this program and I don't know how to fix the actual data"
You don't have to fix bad data yourself. You can safely take a program out of the feed temporarily instead -- this is completely reversible and never breaks anything else. Near the top of `config/overrides.yaml` there's a list called `excluded_programs:`. Add the program's id as a new line in that list, in the same format as the existing ones:

```yaml
excluded_programs:
  - 664e7478-7403-4e7e-ada4-fa468f74671f  # Actualiteitenlezingen Pensioenrecht
  - <the-program-id-you-want-to-pull>  # <your name>, <today's date>, <why>
```

That program simply won't appear in the feed until someone removes that line again. This is the safest option whenever you're unsure -- better to temporarily leave a program out than to guess.

### Recipe D: a Teams alert says "content changed" for a specific program
This is the stale-price/broken-scraper scenario from section 1. The message names the program and gives a short reason (e.g. "could previously read a cost/price bullet off this page; can no longer find one" or "the override no longer matches the current scrape"). To handle it:

1. Open the real program page on vu.nl (the message/`report.md` gives the URL) and check the actual current value yourself.
2. If you can tell what the correct value is, use **Recipe A** above to type the right number/fact into `overrides.yaml`.
3. If you genuinely can't tell what's right (the page itself is confusing, or the price is quoted several incompatible ways), don't guess -- use **Recipe C** to pull just that one program out, and leave a note for Max with what you saw.

### Recipe E: "something's seriously wrong and I don't know where to start" (safe mode)
This is the worst-case option -- pulling the **entire** feed out, all at once, without taking anything offline or touching EDU-DEX's own systems. It's completely reversible and uses the exact same mechanism as Recipe C, just applied to every program. Use it if several programs look wrong at once, if a "BUILD FAILED" alert doesn't make sense to you and you'd rather be safe, or if you're simply not sure what else to do and want to stop the bleeding until Max is reachable.

1. Open `config/overrides.yaml` for editing (same pencil-icon steps as section 2).
2. Under `excluded_programs:`, add every program id currently listed in `report.md` (`https://allezmax.github.io/vu-for-professionals-edudex-feed/report.md`), one per line, same format as Recipe C.
3. Commit with a message like "Safe mode -- pulling all programs, see Teams alert from <date>."
4. The next run will publish a technically valid but **empty** feed -- nothing goes out with wrong data, but nothing goes out at all either. Leave a clear note for Max explaining why you did this.
5. To undo later (you or Max): just remove the lines you added and commit again.

This is a blunt instrument on purpose -- it trades "nothing is visible" for "nothing is wrong," which is always the safer trade when you can't tell what's actually broken. It does **not** remove VU from EDU-DEX's own catalogue (that's a different, portal-side action only Max can do) -- it only means this feed itself temporarily has nothing in it to publish.

---

## 3. If a daily run shows a red X (failed)

The most common cause: a typo or indentation mistake in `overrides.yaml` from a recent edit (by you or anyone else). To fix:

1. Go to `config/overrides.yaml`, click the clock/history icon near the top of the file ("History").
2. Find the commit just *before* the one that broke things, click on it, and view the file at that point (there should be a way to view/copy its full text).
3. Go back to the current file, click the pencil (edit) icon, select all the text (Ctrl+A / Cmd+A) and delete it, then paste in the older, working version you just copied.
4. Commit with a message like "Revert -- undo my last change." This puts things back to a known-good state. You (or Max, later) can retry the actual fix more carefully.

If the red X's error message doesn't look like a simple YAML typo (e.g. it mentions a `.py` file, or looks like a real error message in code), **don't try to fix it yourself** -- that's a genuine code problem, not a data problem, and it's fine to just leave it and flag it for Max. This repo has run successfully every single day for months, so this should be rare.

---

## 4. What NOT to touch

Everything under `src/edudex_feed/` (files ending in `.py`) is actual code, not configuration. Leave these alone -- there should be no reason to ever need to edit them while covering. If something there seems broken, that's a "wait for Max" situation.

---

## 5. The two config files that are already set up correctly

- `config/institute.yaml` -- VU's own registration details. Already correct; no reason to touch it.
- `config/overrides.yaml` -- see sections 2-3 above, this is the one you'll actually use.

---

## 6. Open decisions you're inheriting (not your job to solve -- just don't guess at these)

- **Executive Master in Coaching**: its listed "degree" type and location are both known to be wrong, but the correct replacement values need someone with real knowledge of the course to confirm -- don't guess.
- **Zijlstra PE programma**: priced three incompatible ways on its own page; no single price has been agreed on yet.
- **The team review**: Max's team is working through a separate spreadsheet marking each program "Good to go" / "Needs fixes" / "Exclude for now." Once that's finished, anything not "Good to go" should go into the `excluded_programs` list (Recipe C above) before this feed is registered with EDU-DEX for real.

Full background on all of this is in `docs/DECISIONS.md` in the repo.

---

## 7. Who to contact

- **EDU-DEX's own support**: `support@edudex.nl` -- only for questions about EDU-DEX itself (their portal, their rules), never for anything about this repo.
- **Max**: for anything you're not sure about. There's no rush on almost anything here -- the safest move is always "leave it as-is and make a note" over guessing.

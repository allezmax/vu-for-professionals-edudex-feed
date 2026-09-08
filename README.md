# edudex-feed

Scrapes the "VU for Professionals" course pages on vu.nl and generates an
[EDU-DEX](https://www.edudex.nl/)-compliant XML feed, republished daily via
GitHub Actions + GitHub Pages -- no VU IT infrastructure required.

## What this actually does

1. **Discover** every program under the "School of Business and Economics
   for Professionals" filter on
   https://vu.nl/nl/onderwijs/professionals/cursussen-opleidingen
   (currently ~63 programs). The listing page loads its results via
   JavaScript, so this step drives a real headless browser (Playwright) and
   reads the site's own search API response.
2. **Scrape** each program's overview page plus its `/inhoud` (content) and
   `/toelating` (admission) sub-pages with plain HTTP requests (these pages
   are server-rendered, so no browser is needed here) and pull out title,
   description, duration, price, contact person, and any "Label: waarde"
   facts (Duur, Kosten, Vorm, Startdatum, ...).
3. **Generate** one `program.xml` per course plus one shared `institute.xml`
   and a `directory.xml` that points EDU-DEX at both -- following the exact
   XML structure documented at https://edudex.nl/edudox/.
4. **Validate** every generated file against the *live* EDU-DEX XSDs
   (downloaded fresh each run from `studieData.nl`), so a schema change on
   EDU-DEX's end fails the build loudly instead of silently producing a feed
   they'll reject.
5. **Publish** the `feed/` folder to GitHub Pages, giving you one stable
   public URL to hand to EDU-DEX.

Runs daily via a scheduled GitHub Action (see `.github/workflows/build-feed.yml`),
comfortably before EDU-DEX's nightly 18:00 (Europe/Amsterdam) import.

## Why some fields are "guessed"

VU's course pages describe programs the way a prospective student needs, not
in EDU-DEX's own vocabulary. Things like the exact NLQF-style level, what
kind of certificate/diploma is issued, or whether payment is due up-front vs.
in installments usually aren't stated on the page at all -- they're policy
decisions PDO/finance make, not facts to scrape. For those fields, the
generator uses a conservative default and flags the program in
`data/report.md` (also uploaded as a workflow artifact on every run) so a
human can confirm the right value once in `config/overrides.yaml`. After
that, the override is remembered on every future run until the program
disappears from vu.nl.

## One-time setup

You'll need a GitHub account with permission to create a repository (a
personal account works fine, or ask IT for a spot in VU's GitHub
organisation if VU has one -- either works, this doesn't touch any VU
servers).

1. **Create a new GitHub repository** (public -- GitHub Pages on the free
   tier only serves public repos) and push this folder's contents to it.
2. **Fill in the institute config**:
   ```
   cp config/institute.example.yaml config/institute.yaml
   ```
   Edit `config/institute.yaml`: at minimum set `org_unit_id` (ask
   support@edudex.nl for VU's registered id, or check
   https://feeds.edudex.nl/organizatie-ids/ ) and `editor_email` (a team
   inbox EDU-DEX can email when something fails validation -- not a personal
   address). Commit the file.
3. **Enable GitHub Pages**: repo Settings -> Pages -> Source: "GitHub
   Actions" (not "Deploy from a branch" -- the workflow uses the newer Pages
   deployment action).
4. **Run the workflow once by hand**: Actions tab -> "Build and publish
   EDU-DEX feed" -> "Run workflow". Check the run's summary and download the
   `edudex-feed-report` artifact -- `report.md` lists every program with a
   field that needs a human decision.
5. **Fill in `config/overrides.yaml`** for anything report.md flagged that
   matters to you (see `config/overrides.example.yaml` for the format), then
   re-run the workflow.
6. **Find your feed URL**: once the workflow succeeds, your directory file is
   at `https://<your-github-username>.github.io/<repo-name>/directory.xml`
   (shown in the workflow's "deploy" job summary too).
7. **Register the feed with EDU-DEX**: validate it yourself first at
   https://feeds.edudex.nl/ (the "Validator" they link handles one file at a
   time -- check the directory file, the institute file, and a couple of
   program files), then email the directory URL to support@edudex.nl. They
   integrate it within one business day and read it nightly after 18:00
   from then on.

## Running locally

```
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pip install -e .
playwright install chromium

cp config/institute.example.yaml config/institute.yaml   # then edit it
python -m edudex_feed.main --base-url "https://yourname.github.io/edudex-feed"
```

Output lands in `feed/` (the XML) and `data/` (`report.md` and a raw
`scraped.json` dump useful for debugging a parsing problem on one program).

## Repo layout

```
src/edudex_feed/
  discover.py   # Playwright: finds every program URL via vu.nl's search API
  scrape.py     # requests+BeautifulSoup: pulls fields off each program page
  mapping.py    # EDU-DEX's controlled vocabularies (levels, forms, etc.)
  xmlgen.py     # builds the actual <program>/<institute>/<directory> XML
  validate.py   # validates output against the live EDU-DEX XSDs
  main.py       # orchestrates the above, writes data/report.md
config/
  institute.example.yaml   # copy to institute.yaml and fill in
  overrides.example.yaml   # copy to overrides.yaml, fill in as report.md flags things
.github/workflows/build-feed.yml   # the scheduled job
tests/                       # offline tests against a saved real-page fixture
```

## Known limitations / next steps

- **Scope**: currently hard-coded to the "School of Business and Economics
  for Professionals" filter (`discover.DEFAULT_LISTING_URL`). Widening it to
  all of VU for Professionals is a one-line change but will surface a wider
  variety of page layouts that may need extra parsing rules.
- **Cost/price parsing** only picks up a single "Kosten: €X,-" bullet as the
  tuition fee. Programs with itemized costs (tuition + materials + exam fees
  broken out) will need either smarter parsing or a manual override per
  program.
- **Language**: Dutch-only for now, per the initial scope. Every VU program
  page links its English translation (`hreflang="en"`) if one exists, so
  adding a second `xml:lang="en"` block per text field is a natural next
  step if EDU-DEX consumers need it.
- **This has not yet been run against the live site or the live EDU-DEX
  validator** -- do that as step 4 above before emailing EDU-DEX. The
  parsing logic is tested against a real saved page (`tests/`), and the XML
  structure/enumerations come directly from EDU-DEX's own reference tool,
  but only a real end-to-end run (which needs unrestricted internet access
  this development environment didn't have) can catch everything.

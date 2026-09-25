"""
Offline sanity test: parses a saved fixture of a real vu.nl program page
(captured 2026-09-07 from basisopleiding-verandermanagement) and checks the
scraper pulls out the fields we expect, then runs the XML generator over the
result and checks the output is well-formed and has the mandatory elements.

This does NOT hit the network and does NOT replace real XSD validation
(see validate.py, which needs network access to fetch the live XSDs) -- it
only guards against regressions in the HTML-parsing logic itself.
"""
import sys
from pathlib import Path
from xml.etree import ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bs4 import BeautifulSoup
from edudex_feed.mapping import guess_degree
from edudex_feed.scrape import (
    ScrapedProgram, _parse_head, _parse_main_body, _first_fact, _parse_usp_bar, _parse_accordion_facts,
)
from edudex_feed.xmlgen import (
    build_program_xml, _extract_price, _looks_like_range_or_itemized, _extract_duration, _apply_cost_period,
    _select_cost_text, _prefer_total_over_per_unit_amount, _detect_program_location,
)

FIXTURE = Path(__file__).parent / "fixtures" / "basisopleiding-verandermanagement.html"


def load_fixture() -> ScrapedProgram:
    soup = BeautifulSoup(FIXTURE.read_text(encoding="utf-8"), "html.parser")
    program = ScrapedProgram(url="https://vu.nl/nl/onderwijs/professionals/cursussen-opleidingen/basisopleiding-verandermanagement")
    _parse_head(soup, program)
    _parse_main_body(soup, program)
    return program


def test_head_fields():
    p = load_fixture()
    assert p.vu_id == "7e838533-cc22-427b-9d54-b552ad5eb9dc"
    assert "Basisopleiding Verandermanagement" in p.title
    assert p.meta_description.startswith("Met eigen ervaring")
    assert p.last_modified == "Mon, 06 Jul 2026 18:33:17 GMT"


def test_facts_extracted():
    p = load_fixture()
    assert "Duur" in p.facts
    assert p.facts["Duur"] == "4 maanden"
    assert "Vorm" in p.facts
    assert p.facts["Vorm"] == "Klassikaal"
    assert "Kosten" in p.facts


def test_contact_extracted():
    p = load_fixture()
    assert p.contact_email == "pdo.vm.sbe@vu.nl"
    assert p.contact_name == "Lilian Dekker"
    assert p.contact_role == "Opleidingscoördinator"
    assert "06-23519129" in p.contact_phone


def test_description_paragraphs():
    p = load_fixture()
    assert len(p.description_paragraphs) >= 1
    joined = " ".join(p.description_paragraphs)
    assert "Basisopleiding Verandermanagement legt het fundament" in joined
    # bare "<strong>Header:</strong>"-only paragraphs should be filtered out
    assert "Wat levert de opleiding op?" not in joined
    assert "in het kort:" not in joined


def test_heading_extracted():
    p = load_fixture()
    assert p.heading == "Basisopleiding Verandermanagement"


def test_xml_generation_is_well_formed_and_has_mandatory_elements():
    p = load_fixture()
    element, review = build_program_xml(
        p,
        org_unit_id="vu",
        editor_email="edudex@vu.nl",
        generator_name="test",
        expires_in_days=21,
        override={},
    )
    xml_bytes = ET.tostring(element, encoding="utf-8")
    # round-trips through the XML parser without error => well-formed
    reparsed = ET.fromstring(xml_bytes)

    mandatory_top_level = [
        "editor", "expires", "format", "generator", "lastEdited",
        "programAdmission", "programClassification", "programContacts",
        "programCurriculum", "programDescriptions", "programSchedule",
    ]
    def local_name(tag: str) -> str:
        return tag.split("}", 1)[1] if "}" in tag else tag

    child_tags = {local_name(child.tag) for child in reparsed}
    for tag in mandatory_top_level:
        assert tag in child_tags, f"missing mandatory element <{tag}>"

    # a couple of guessed fields should be flagged for review given this
    # fixture has no override data
    assert "programLevel" in review
    # paymentDue is a confirmed constant now (Max, 2026-09-15: every VU for
    # Professionals programme pays in installments), not a guess -- it should
    # NOT be flagged for review any more.
    assert "paymentDue" not in review


def test_extract_price_handles_english_and_dutch_thousands_separators():
    # BUG (2026-09-10): the old parser treated "," as a hard stop, so an English
    # page's "€5,975" (comma thousands separator) came out as 5.0 instead of 5975.0
    # -- confirmed live on the "Enterprise Risk & Compliance Management" course.
    assert _extract_price("€5,975") == 5975.0
    # Dutch pages use the opposite convention: "." groups thousands, trailing ",-"
    # means no cents.
    assert _extract_price("€ 27.500,-") == 27500.0
    assert _extract_price("€7.250,-") == 7250.0
    # a real decimal amount should still work
    assert _extract_price("$1,234.56") == 1234.56
    assert _extract_price("no price here") is None


def test_looks_like_range_or_itemized_ignores_unrelated_numbers():
    # A single, unambiguous amount alongside unrelated numbers (here, an academic
    # year) must NOT be flagged as a range.
    assert _looks_like_range_or_itemized("€ 23.000 bij start in academisch jaar 2026-2027") is False
    assert _looks_like_range_or_itemized("between € 32.000 and € 34.000") is True
    assert _looks_like_range_or_itemized("€6000 / €4000") is True


def test_first_fact_matches_compound_labels_by_substring():
    # Newer VU page template uses compound labels like "Investering tweejarige
    # master" / "Investering premaster" instead of a plain "Investering" bullet --
    # confirmed live 2026-09-10 on the Deeltijd Master Bedrijfskunde page. The
    # full-track cost (listed first) should win over the pre-master cost.
    facts = {
        "Investering tweejarige master": "€ 23.000 bij start in academisch jaar 2026-2027",
        "Investering premaster": "€ 3.000 bij start in 2026",
    }
    assert _first_fact(facts, "Kosten", "Costs", "Cost", "Investering") == facts["Investering tweejarige master"]


def test_first_fact_does_not_match_search_term_fused_onto_another_word():
    """BUG FOUND 2026-09-17: plain substring matching also matched a search
    term glued onto the END of an unrelated Dutch compound word --
    "Investering" (looking for the tuition-cost bullet) matched inside
    "Tijdsinvestering" ("time investment"), confirmed live on the CMA page,
    where "Tijdsinvestering: 8-10 uur per week" appears before the real
    "Investering: ..." bullet and so won outright, emitting an hours-per-week
    figure as the tuition fee. The needle must start a real word -- not be
    preceded by another letter -- to match."""
    facts = {
        "Tijdsinvestering": "8-10 uur per week",
        "Investering": "€ 1.900 per deel",
    }
    assert _first_fact(facts, "Kosten", "Costs", "Cost", "Investering") == "€ 1.900 per deel"

    facts_reiskosten = {"Reiskosten": "wordt vergoed", "Kosten": "€ 5.000"}
    assert _first_fact(facts_reiskosten, "Kosten") == "€ 5.000"


def test_guess_degree_prefers_explicit_diploma_fact():
    # "Diploma: MSc" (confirmed live on the EMFC/Controllersopleiding page) is a
    # real statement, not a guess -- should win over any keyword scan.
    code, needs_review = guess_degree("MSc, EMFC, Register Controller (RC)", "some unrelated body text")
    assert code == "MSc"
    assert needs_review is False


def test_guess_degree_falls_back_to_body_text_keyword():
    # "Master of Science (MSc)" often only appears in body copy, not the title --
    # confirmed live on the Deeltijd Master Bedrijfskunde page, where it's a bullet
    # under "Wat levert de Master Bedrijfskunde je op?". The code is still trusted,
    # but -- unlike an explicit "Diploma:"/"Titels:" fact bullet -- a body-text
    # match always comes back flagged for review (see guess_degree's docstring for
    # the live 2026-09-11 catalog cases that motivated this: body text is an
    # open-ended source of unrelated keyword mentions no amount of extra guarding
    # fully closes off).
    code, needs_review = guess_degree("", "Een internationaal erkende Master of Science (MSc)")
    assert code == "MSc"
    assert needs_review is True

    code, needs_review = guess_degree("", "Part-time PhD in Finance")
    assert code == "PhD"
    assert needs_review is True


def test_guess_degree_defaults_to_certificate_when_nothing_found():
    code, needs_review = guess_degree("", "Basisopleiding Verandermanagement")
    assert code == "certificate of participation"
    assert needs_review is True


def test_guess_degree_ignores_keyword_hiding_inside_an_unrelated_word():
    # Confirmed live 2026-09-11: "Escaperoom Het Huis van Toezicht" was tagged
    # "DBA" because a testimonial says "...persoonlijke feedback levert." --
    # "feedback" contains the literal substring "dba" (fee-D-B-Ack). A plain
    # substring scan can't tell that apart from a real "DBA" mention.
    code, needs_review = guess_degree(
        "", "Je wordt begeleid door een team dat hele goede persoonlijke feedback levert."
    )
    assert code == "certificate of participation"
    assert needs_review is True


def test_guess_degree_ignores_a_lecturers_own_credentials_in_a_bio():
    # Confirmed live 2026-09-11: "Parttime Master of Science in Marketing" was
    # tagged "PhD" because its curriculum page names a lecturer's own "PhD
    # (2001) in Marketing" in a faculty bio -- and "phd" sorts before "msc"/
    # "master of science" in DEGREE_KEYWORDS, so the bio mention won even
    # though the program's own name clearly says "Master of Science".
    code, needs_review = guess_degree(
        "",
        "Parttime Master of Science in Marketing. Zet de volgende stap in je "
        "marketingcarriere! Hij heeft zowel een PhD (2001) in Marketing als "
        "een MSc in Food Science, beide behaald aan Wageningen University.",
    )
    assert code == "MSc"
    assert needs_review is True  # still a body-text guess -- see docstring


def test_guess_degree_body_text_match_is_always_flagged_for_review():
    # Confirmed live 2026-09-11: even after guarding against the two bugs above,
    # "Executive Master in Coaching" still came out wrong from its own coaches'
    # bios two different ways -- "...vele executives, (PhD) studenten en
    # klanten..." (PhD names a type of client she coaches, not a credential) and
    # "...in 2015 (MSc)..." (an accreditation the COACH holds, not what this
    # programme awards) -- neither phrased as a bio sentence the way the guard
    # above looks for. Rather than keep chasing every new phrasing, a body-text
    # match is always flagged for review, even when (as here) it happens to
    # come out wrong outright, or (as in the tests above) it happens to be
    # right -- only an explicit "Diploma"/"Titels" fact bullet is trusted
    # without review.
    code, needs_review = guess_degree(
        "",
        "Ze heeft als coach en mentor vele executives, (PhD) studenten en "
        "klanten kunnen helpen persoonlijke doelen te bereiken in hun werk "
        "of studie. Marjan is door Ashridge Hult geaccrediteerd als "
        "executive coach in 2015 (MSc).",
    )
    assert needs_review is True


def test_degree_and_cost_wired_into_generated_xml():
    """End-to-end regression for the 2026-09-10 feedback: a program whose only
    degree signal is a body-text keyword, and whose cost lives under a compound
    label, must come out right in the generated XML -- not silently defaulted."""
    p = ScrapedProgram(url="https://vu.nl/nl/onderwijs/professionals/cursussen-opleidingen/deeltijd-master-bedrijfskunde")
    p.title = "Deeltijd Master Bedrijfskunde (Business Administration)"
    p.heading = p.title
    p.content_language = "nl"
    p.facts = {
        "Start": "jaarlijks februari en september",
        "Duur": "2 jaar (deeltijd)",
        "Investering tweejarige master": "€ 23.000 bij start in academisch jaar 2026-2027",
        "Investering premaster": "€ 3.000 bij start in 2026",
        "Vorm": "op de VU Campus",
    }
    p.description_paragraphs = ["Een internationaal erkende Master of Science (MSc) programma."]

    element, review = build_program_xml(
        p, org_unit_id="vu", editor_email="edudex@vu.nl", generator_name="test", expires_in_days=21, override={},
    )
    reparsed = ET.fromstring(ET.tostring(element, encoding="utf-8"))
    ns = "{http://studieData.nl/schema/edudex/program}"
    degree = reparsed.find(f"{ns}programClassification/{ns}degree").text
    cost_amount = reparsed.find(f"{ns}programSchedule/{ns}genericProgramRun/{ns}cost/{ns}amount").text

    assert degree == "MSc"
    assert float(cost_amount) == 23000.0
    assert "degree" in review  # body-text match, always flagged -- see guess_degree's docstring
    assert "cost" not in review


def test_range_cost_flagged_and_raw_text_surfaced():
    """A range/itemized cost (e.g. a PhD programme's "between €X and €Y" tuition)
    must still emit a best-effort amount, but flag it for review and keep the raw
    'Dates and costs' text so nothing is silently lost."""
    p = ScrapedProgram(url="https://vu.nl/en/education/professionals/courses-programmes/part-time-phd-programme-in-finance")
    p.title = "Part-time PhD in Finance"
    p.heading = p.title
    p.content_language = "en"
    p.facts = {
        "Start date": "September 2027",
        "Duration": "4+ years (part-time)",
        "Tuition fees": "between € 32.000 and € 34.000 (depending on chosen trajectory)",
    }
    p.dates_costs_text = "Year 1 & 2: €12,000/year"

    element, review = build_program_xml(
        p, org_unit_id="vu", editor_email="edudex@vu.nl", generator_name="test", expires_in_days=21, override={},
    )
    reparsed = ET.fromstring(ET.tostring(element, encoding="utf-8"))
    ns = "{http://studieData.nl/schema/edudex/program}"
    degree = reparsed.find(f"{ns}programClassification/{ns}degree").text
    cost_amount = reparsed.find(f"{ns}programSchedule/{ns}genericProgramRun/{ns}cost/{ns}amount").text
    subjects = [s.find(f"{ns}subject").text for s in reparsed.findall(f"{ns}programDescriptions/{ns}subjectText")]

    assert degree == "PhD"
    assert float(cost_amount) == 32000.0
    assert "cost" in review
    assert "tuition fee" in subjects


def test_cost_multiplied_by_duration_when_stated_per_period():
    """Regression for Max's 2026-09-15 report: 'Kosten: € 9.750 per jaar' with
    'Duur: 2 jaar' must total to the full programme cost (19500), not the
    single-year amount -- confirmed live on Parttime MSc Marketing."""
    p = ScrapedProgram(url="https://vu.nl/nl/onderwijs/professionals/cursussen-opleidingen/parttime-master-of-science-in-marketing")
    p.title = "Parttime Master of Science in Marketing"
    p.heading = p.title
    p.content_language = "nl"
    p.facts = {
        "Startdatum": "september 2026",
        "Duur": "2 jaar (deeltijd)",
        "Kosten": "€ 9.750 per jaar",
        "Vorm": "klassikaal",
    }

    element, review = build_program_xml(
        p, org_unit_id="vu", editor_email="edudex@vu.nl", generator_name="test", expires_in_days=21, override={},
    )
    reparsed = ET.fromstring(ET.tostring(element, encoding="utf-8"))
    ns = "{http://studieData.nl/schema/edudex/program}"
    cost_amount = reparsed.find(f"{ns}programSchedule/{ns}genericProgramRun/{ns}cost/{ns}amount").text
    duration = reparsed.find(f"{ns}programClassification/{ns}programDuration")

    assert float(cost_amount) == 19500.0
    assert duration.text == "2" and duration.get("unit") == "year"
    assert "cost" not in review  # clean multiple -- nothing to flag


def test_cost_copied_as_is_when_no_per_period_wording():
    """Per Max (2026-09-15): a cost bullet with no 'per X' wording at all is
    already a one-off total and must be copied as-is, not multiplied."""
    p = ScrapedProgram(url="https://vu.nl/nl/onderwijs/professionals/cursussen-opleidingen/voorbeeld")
    p.title = "Voorbeeldprogramma"
    p.heading = p.title
    p.content_language = "nl"
    p.facts = {"Duur": "3 maanden", "Kosten": "€ 4.500"}

    element, review = build_program_xml(
        p, org_unit_id="vu", editor_email="edudex@vu.nl", generator_name="test", expires_in_days=21, override={},
    )
    reparsed = ET.fromstring(ET.tostring(element, encoding="utf-8"))
    ns = "{http://studieData.nl/schema/edudex/program}"
    cost_amount = reparsed.find(f"{ns}programSchedule/{ns}genericProgramRun/{ns}cost/{ns}amount").text

    assert float(cost_amount) == 4500.0
    assert "cost" not in review


def test_cost_per_unrecognized_period_is_flagged_not_guessed():
    """A cost stated 'per module' (or any period this feed can't total
    automatically, e.g. no module count is scraped) must not be silently
    multiplied or mistaken for a flat total -- it should come out flagged."""
    total, note = _apply_cost_period(3500.0, "Fee: € 3.500 per module", 6, "month")
    assert total == 3500.0
    assert note is not None and "per module" in note


def test_cost_per_period_flagged_when_duration_unknown():
    total, note = _apply_cost_period(12000.0, "Kosten: € 12.000 per jaar", None, "month")
    assert total == 12000.0
    assert note is not None and "no programme duration could be parsed" in note


def test_tuition_fee_override_is_not_multiplied():
    """An explicit tuitionFeeAmount override is already the final total the
    human confirmed -- it must be emitted as-is, never scaled by duration."""
    p = ScrapedProgram(url="https://vu.nl/nl/onderwijs/professionals/cursussen-opleidingen/voorbeeld")
    p.title = "Voorbeeldprogramma"
    p.heading = p.title
    p.content_language = "nl"
    p.facts = {"Duur": "2 jaar", "Kosten": "€ 9.750 per jaar"}

    element, review = build_program_xml(
        p, org_unit_id="vu", editor_email="edudex@vu.nl", generator_name="test", expires_in_days=21,
        override={"tuitionFeeAmount": 19500},
    )
    reparsed = ET.fromstring(ET.tostring(element, encoding="utf-8"))
    ns = "{http://studieData.nl/schema/edudex/program}"
    cost_amount = reparsed.find(f"{ns}programSchedule/{ns}genericProgramRun/{ns}cost/{ns}amount").text
    assert float(cost_amount) == 19500.0


def test_extract_duration_returns_none_on_failed_parse():
    """BUG FOUND 2026-09-15: this used to silently return (1, 'month') on a
    failed parse, an ordinary-looking value indistinguishable from a real
    1-month programme, which defeated the programDuration needs_review flag
    entirely. A failed parse must come back as None so it can be flagged and
    so cost x duration multiplication can tell 'unknown' from 'really 1 month'."""
    assert _extract_duration("afhankelijk van traject (deeltijd)", {}) == (None, "month")
    assert _extract_duration("2 jaar (deeltijd)", {}) == (2, "year")


def test_extract_duration_handles_dutch_weken_plural():
    """BUG FOUND 2026-09-17: the old regex looked for "week" + optional "en",
    i.e. "weeken", but the real Dutch plural is "weken" (single "e") -- Dutch
    spelling drops one letter of the doubled vowel once the syllable opens up
    in the plural ("week" -> "we-ken"). That silently defeated the regex on
    every programme whose duration is stated in weeks, the single most common
    Dutch phrasing -- confirmed live on the Certified Management Accountant
    (CMA) page ("Duur: 15 weken per deel (deeltijd)"), which fell back to
    "could not parse a duration" despite a perfectly well-formed fact bullet."""
    assert _extract_duration("15 weken per deel (deeltijd)", {}) == (15, "week")
    assert _extract_duration("6 weken", {}) == (6, "week")
    assert _extract_duration("1 week", {}) == (1, "week")
    assert _extract_duration("20 weeks", {}) == (20, "week")


def test_program_duration_flagged_and_defaulted_when_unparseable():
    p = ScrapedProgram(url="https://vu.nl/nl/onderwijs/professionals/cursussen-opleidingen/verandermanagement")
    p.title = "Verandermanagement"
    p.heading = p.title
    p.content_language = "nl"
    p.facts = {"Duur": "afhankelijk van traject (deeltijd)", "Kosten": "zie opleidingspagina's"}

    element, review = build_program_xml(
        p, org_unit_id="vu", editor_email="edudex@vu.nl", generator_name="test", expires_in_days=21, override={},
    )
    reparsed = ET.fromstring(ET.tostring(element, encoding="utf-8"))
    ns = "{http://studieData.nl/schema/edudex/program}"
    duration = reparsed.find(f"{ns}programClassification/{ns}programDuration")

    assert duration.text == "1" and duration.get("unit") == "month"
    assert "programDuration" in review


def test_program_location_defaults_to_vu_campus_amsterdam():
    """Per Max (2026-09-15): confirmed constant for every programme."""
    p = ScrapedProgram(url="https://vu.nl/nl/onderwijs/professionals/cursussen-opleidingen/voorbeeld")
    p.title = "Voorbeeldprogramma"
    p.heading = p.title
    p.content_language = "nl"

    element, review = build_program_xml(
        p, org_unit_id="vu", editor_email="edudex@vu.nl", generator_name="test", expires_in_days=21, override={},
    )
    reparsed = ET.fromstring(ET.tostring(element, encoding="utf-8"))
    ns = "{http://studieData.nl/schema/edudex/program}"
    location = reparsed.find(f"{ns}programClassification/{ns}programLocation").text
    assert location == "VU Campus Amsterdam"


# --- Round 6 (2026-09-22): USP bar, accordion template, cost-selection policy, ---------------
# --- location detection, and PhD-degree bio-cue fixes ----------------------------------------
# All confirmed live against real vu.nl pages while implementing Max's Sept 18 export feedback
# (18 threaded Excel comments across rows 2-20, plus his sign-off to generalise the recurring
# patterns to all 66 programmes -- see claude/edudex-feed.md's Round 6 section).

USP_BAR_HTML = """
<div data-widget="technical-study-details">
  <div class="grid-x">
    <div class="cell vuw-icon-block"><i class="fal fal fa-books vuw-text-primary-1"></i><div><span>Leergang / Opleiding</span></div></div>
    <div class="cell vuw-icon-block"><i class="fal fal fa-globe-africa vuw-text-primary-1"></i><div><span>Nederlands</span></div></div>
    <div class="cell vuw-icon-block"><i class="fal fal fa-calendar vuw-text-primary-1"></i><div><span>9 maanden (deeltijd, 7 dagen)</span></div></div>
  </div>
</div>
"""

ACCORDION_HTML = """
<ul>
<li class="accordion-item" data-accordion-item>
  <a href="#" class="accordion-title" aria-expanded="false"><i class="fal fa-arrow-right"></i><h3>Kosten</h3></a>
  <div class="accordion-content" aria-hidden="true"><div class="vuw-rich-text"><p>&euro; 2.900,- <em>(vrij van BTW).</em></p></div></div>
</li>
<li class="accordion-item" data-accordion-item>
  <a href="#" class="accordion-title" aria-expanded="false"><i class="fal fa-arrow-right"></i><h3>Locatie</h3></a>
  <div class="accordion-content" aria-hidden="true"><div class="vuw-rich-text"><p>NU-gebouw, De Boelelaan 1111, Amsterdam.</p></div></div>
</li>
<li class="accordion-item" data-accordion-item>
  <a href="#" class="accordion-title" aria-expanded="false"><i class="fal fa-arrow-right"></i><h3>Diploma</h3></a>
  <div class="accordion-content" aria-hidden="true"><div class="vuw-rich-text"><p>Je ontvangt na afloop van de opleiding een diploma.</p></div></div>
</li>
</ul>
"""


def test_parse_usp_bar_extracts_icon_blocks_as_facts():
    """Confirmed live 2026-09-22 on 'De strategische griffier' -- the USP bar
    below the hero image (Max: "often the USP bar contains key information")
    has no <li>"Label: value" bullet form at all, just an <i> icon class +
    <span> text pair per block, so it needs its own parser."""
    soup = BeautifulSoup(USP_BAR_HTML, "html.parser")
    p = ScrapedProgram(url="https://vu.nl/nl/onderwijs/professionals/cursussen-opleidingen/de-strategische-griffier")
    _parse_usp_bar(soup, p)
    assert p.facts["USP-Type"] == "Leergang / Opleiding"
    assert p.facts["USP-Taal"] == "Nederlands"
    assert p.facts["USP-Duur"] == "9 maanden (deeltijd, 7 dagen)"


def test_usp_bar_facts_do_not_override_a_real_fact_bullet():
    """The USP bar is a fallback, not an authority -- an explicit "Duur:"
    bullet from the "in het kort" list must still win over the USP bar's own
    duration line when both exist on the same page."""
    p = ScrapedProgram(url="https://vu.nl/nl/onderwijs/professionals/cursussen-opleidingen/voorbeeld")
    p.facts["Duur"] = "4 maanden"
    _parse_usp_bar(BeautifulSoup(USP_BAR_HTML, "html.parser"), p)
    assert _first_fact(p.facts, "Duur", "Duration") == "4 maanden"


def test_parse_accordion_facts_extracts_label_and_value():
    """Confirmed live 2026-09-22 on Besturen van Filantropische Fondsen's
    /data-en-kosten page -- a THIRD page-template variant whose "Kosten"/
    "Locatie"/"Diploma"/etc sections are each a collapsed accordion item
    (aria-hidden="true" in the browser, but present in the raw server-
    rendered HTML regardless) rather than a "<Label>: <value>" bullet."""
    soup = BeautifulSoup(ACCORDION_HTML, "html.parser")
    p = ScrapedProgram(url="https://vu.nl/nl/onderwijs/professionals/cursussen-opleidingen/besturen-van-filantropische-fondsen")
    _parse_accordion_facts(soup, p)
    assert p.facts["Kosten"] == "€ 2.900,- (vrij van BTW)."
    assert p.facts["Locatie"] == "NU-gebouw, De Boelelaan 1111, Amsterdam."
    assert p.facts["Diploma"] == "Je ontvangt na afloop van de opleiding een diploma."


def test_program_type_and_form_fall_back_to_usp_bar_when_no_fact_list_exists():
    """Confirmed live 2026-09-22 on Business Analytics for Industry, which
    has NO "in het kort" bullet list at all -- the USP bar is the only
    structured fact source on the whole page."""
    p = ScrapedProgram(url="https://vu.nl/nl/onderwijs/professionals/cursussen-opleidingen/business-analytics-for-industry")
    p.title = "Business Analytics for Industry"
    p.heading = p.title
    p.content_language = "en"
    p.facts = {"USP-Type": "Cursus / Training", "USP-Taal": "Engels", "USP-Duur": "8 full days"}

    element, review = build_program_xml(
        p, org_unit_id="vu", editor_email="edudex@vu.nl", generator_name="test", expires_in_days=21, override={},
    )
    reparsed = ET.fromstring(ET.tostring(element, encoding="utf-8"))
    ns = "{http://studieData.nl/schema/edudex/program}"
    pc = reparsed.find(f"{ns}programClassification")
    duration = pc.find(f"{ns}programDuration")

    assert duration.text == "8" and duration.get("unit") == "day"
    assert pc.find(f"{ns}programType").text == "regular"
    assert "programType" not in review  # USP-Type "Cursus / Training" matched outright


def test_program_type_prefers_usp_bar_over_a_title_with_no_type_keyword():
    """Confirmed live 2026-09-22: "De strategische griffier" has no type
    keyword in its title/heading at all, so it used to fall to the
    unverified 'regular' default -- but its USP bar says "Leergang /
    Opleiding" outright, VU's own classification stated in so many words."""
    p = ScrapedProgram(url="https://vu.nl/nl/onderwijs/professionals/cursussen-opleidingen/de-strategische-griffier")
    p.title = "De strategische griffier"
    p.heading = p.title
    p.content_language = "nl"
    p.facts = {"USP-Type": "Leergang / Opleiding", "USP-Taal": "Nederlands", "USP-Duur": "9 maanden (deeltijd, 7 dagen)"}

    element, review = build_program_xml(
        p, org_unit_id="vu", editor_email="edudex@vu.nl", generator_name="test", expires_in_days=21, override={},
    )
    reparsed = ET.fromstring(ET.tostring(element, encoding="utf-8"))
    ns = "{http://studieData.nl/schema/edudex/program}"
    pc = reparsed.find(f"{ns}programClassification")

    assert pc.find(f"{ns}programType").text == "regular"
    assert "programType" not in review
    # bonus: the USP-bar duration text also carries "deeltijd", so programForm
    # comes out matched (not defaulted+flagged) even with no "Vorm:" bullet.
    assert pc.find(f"{ns}programForm").text == "part-time"
    assert "programForm" not in review


def test_extract_duration_handles_a_trailing_plus_sign():
    """BUG FOUND 2026-09-22: "4+ years (part-time)" (confirmed live on the
    USP bar of Part-time PhD in Finance) didn't match at all -- \\s* can't
    skip over a literal "+" between the digit and the unit word."""
    assert _extract_duration("4+ years (part-time)", {}) == (4, "year")


def test_extract_duration_handles_an_adjective_between_number_and_unit():
    """BUG FOUND 2026-09-22: "8 full days" (confirmed live on the USP bar of
    Business Analytics for Industry, which has no other duration source on
    the whole page) didn't match either -- the unit word had to immediately
    follow the number with only whitespace in between."""
    assert _extract_duration("8 full days", {}) == (8, "day")
    assert _extract_duration("6 hele weken", {}) == (6, "week")


def test_select_cost_text_prefers_regular_price_over_early_bird_discount():
    """Confirmed live 2026-09-22 on Data- en AI-gedreven Sturing in de
    Publieke Sector, whose "in het kort" list states both as two SEPARATE
    bullets. Per Max (2026-09-22): the regular price is the one to feed the
    feed with, not whichever bullet happens to come first on the page."""
    facts = {
        "Startdatum": "eind maart 2027",
        "Duur": "kennismakingsochtend en 8 collegedagen",
        "Prijs": "vroegboekkorting vóór 1 januari 2027: € 4.950,-",
        "Reguliere prijs vanaf 2027": "€ 5.250,-",
        "Lesvorm": "klassikaal",
    }
    assert _select_cost_text(facts) == "€ 5.250,-"
    assert _extract_price(_select_cost_text(facts)) == 5250.0


def test_select_cost_text_recognises_prijs_and_price_labels():
    """BUG FOUND 2026-09-22: "Kosten"/"Costs"/"Investering"/"Tuition fee(s)"/
    "Investment" were the only recognised cost labels -- "Prijs" (confirmed
    live on multiple pages, e.g. Beleidscontrol, Actualiteitenlezingen
    Pensioenrecht) wasn't matched by any of them, so cost silently came out
    empty on every page that only ever says "Prijs"."""
    assert _select_cost_text({"Prijs": "€ 4.995 (vrijgesteld van btw)"}) == "€ 4.995 (vrijgesteld van btw)"
    assert _select_cost_text({"Price": "€ 1.000"}) == "€ 1.000"
    assert _select_cost_text({"Onderwerp": "niets relevants"}) == ""


def test_prefer_total_over_per_unit_amount_picks_the_series_total():
    """Confirmed live 2026-09-22 on Actualiteitenlezingen Pensioenrecht,
    whose single "Prijs" bullet states both a per-unit and a per-4-units
    price in the same string. Per Max (2026-09-22): prefer the stated total/
    series price over the stated per-unit price."""
    text = "per lezing: €325,- (geen btw). Prijs per 4 lezingen: €1.105,- (geen btw)."
    rewritten = _prefer_total_over_per_unit_amount(text)
    assert _extract_price(rewritten) == 1105.0


def test_prefer_total_over_per_unit_amount_leaves_flat_prices_unchanged():
    assert _prefer_total_over_per_unit_amount("€ 5.250,-") == "€ 5.250,-"
    assert _prefer_total_over_per_unit_amount("€ 9.750 per jaar") == "€ 9.750 per jaar"


def test_actualiteitenlezingen_pensioenrecht_end_to_end_cost():
    """End-to-end regression combining both cost-policy fixes: the "Prijs"
    label must be found at all, and the per-4-lezingen total (not the bare
    per-lezing figure, and not the stray "4" itself) must be what's emitted,
    with no spurious 'priced per lezing' review note now that the chosen
    text no longer contains any 'per X' wording of its own."""
    p = ScrapedProgram(url="https://vu.nl/nl/onderwijs/professionals/cursussen-opleidingen/actualiteitenlezingen-pensioenrecht")
    p.title = "Actualiteitenlezingen Pensioenrecht"
    p.heading = p.title
    p.content_language = "nl"
    p.facts = {
        "Prijs": "per lezing: €325,- (geen btw). Prijs per 4 lezingen: €1.105,- (geen btw).",
        "Locatie": "de lezingen vinden plaats in het NU.VU gebouw (nieuwe universiteitsgebouw) van de Vrije Universiteit.",
    }

    element, review = build_program_xml(
        p, org_unit_id="vu", editor_email="edudex@vu.nl", generator_name="test", expires_in_days=21, override={},
    )
    reparsed = ET.fromstring(ET.tostring(element, encoding="utf-8"))
    ns = "{http://studieData.nl/schema/edudex/program}"
    cost_amount = reparsed.find(f"{ns}programSchedule/{ns}genericProgramRun/{ns}cost/{ns}amount").text

    assert float(cost_amount) == 1105.0
    assert "cost" not in review


def test_detect_program_location_finds_confirmed_off_campus_exception():
    """Confirmed live 2026-09-22: Beleidscontrol runs "bij de Rijksacademie
    in Den Haag" -- Max: "I was surprised myself that we offered a course
    elsewhere." The venue text lives inside the *Duur* fact bullet on this
    page template, not a dedicated "Locatie" bullet."""
    facts = {"Duur": "6 dagen van 9.30 – 16.30 uur; bij de Rijksacademie in Den Haag"}
    location, needs_review = _detect_program_location(facts)
    assert location == "bij de Rijksacademie in Den Haag"
    assert needs_review is True


def test_detect_program_location_does_not_flag_the_default_amsterdam_venue():
    """A dedicated "Locatie" fact (from the accordion template) that just
    restates the default building must NOT be treated as an exception --
    confirmed live on Besturen van Filantropische Fondsen."""
    facts = {"Locatie": "NU-gebouw, De Boelelaan 1111, Amsterdam. De ervaring leert dat kennisoverdracht..."}
    location, needs_review = _detect_program_location(facts)
    assert location == "VU Campus Amsterdam"
    assert needs_review is False

    location, needs_review = _detect_program_location({})
    assert location == "VU Campus Amsterdam"
    assert needs_review is False


def test_program_location_override_still_wins_over_detection():
    """A human-confirmed override in overrides.yaml must still take priority
    over the heuristic detector -- e.g. Beleidscontrol's own confirmed,
    cleanly-worded override, once added, should no longer be flagged."""
    p = ScrapedProgram(url="https://vu.nl/nl/onderwijs/professionals/cursussen-opleidingen/beleidscontrol")
    p.title = "Beleidscontrol"
    p.heading = p.title
    p.content_language = "nl"
    p.facts = {"Duur": "6 dagen van 9.30 – 16.30 uur; bij de Rijksacademie in Den Haag"}

    element, review = build_program_xml(
        p, org_unit_id="vu", editor_email="edudex@vu.nl", generator_name="test", expires_in_days=21,
        override={"programLocation": "Rijksacademie, Den Haag"},
    )
    reparsed = ET.fromstring(ET.tostring(element, encoding="utf-8"))
    ns = "{http://studieData.nl/schema/edudex/program}"
    location = reparsed.find(f"{ns}programClassification/{ns}programLocation").text

    assert location == "Rijksacademie, Den Haag"
    assert "programLocation" not in review


def test_guess_degree_catches_informal_ze_pronoun_and_accreditation_cue():
    """BUG FOUND 2026-09-22 (Max, reconfirming the PhD false-positive with
    concrete evidence): "Ze" (informal Dutch "she"/"they") wasn't in the
    pronoun cue list at all (only "zij" was), and "Marjan is door Ashridge
    Hult geaccrediteerd als executive coach in 2015 (MSc)" names the person
    by her first name instead of any pronoun -- "geaccrediteerd" is the real
    tell there. Confirmed live on Executive Master in Coaching's own coach
    bios, both of which leaked through as this course's own awarded degree
    before this fix (PhD and then MSc, depending on which fix was applied)."""
    code, needs_review = guess_degree(
        "",
        "Ze heeft als coach en mentor vele executives, (PhD) studenten en "
        "klanten kunnen helpen persoonlijke doelen te bereiken in hun werk "
        "of studie. Marjan is door Ashridge Hult geaccrediteerd als "
        "executive coach in 2015 (MSc).",
    )
    assert code == "certificate of participation"
    assert needs_review is True


def test_guess_degree_merges_standalone_title_abbreviation_into_next_sentence():
    """BUG FOUND 2026-09-22: a standalone "Dr. Marijn Plomp" line (introducing
    a docent bio) gets cut apart from the sentence that follows it by the
    sentence-splitter (its period + a following capital letter looks exactly
    like a sentence boundary), so "Dr." was gone by the time the bio-cue
    filter checked the sentence that actually states his PhD. Confirmed live
    on Digital Innovation & Transformation's and Data- en AI-gedreven
    Sturing's /inhoud pages, which both reuse this same lecturer bio."""
    code, needs_review = guess_degree(
        "",
        "Digital Innovation & Transformation. Dr. Marijn Plomp Marijn heeft "
        "een PhD in Information Systems aan de Universiteit Utrecht, op "
        "basis van zijn proefschrift over digitale innovatieprocessen.",
    )
    assert code == "certificate of participation"
    assert needs_review is True


def test_guess_degree_recognises_generic_diploma_accordion_fact():
    """Confirmed live 2026-09-22 on Besturen van Filantropische Fondsen's
    "Diploma" accordion section (see scrape.py's _parse_accordion_facts) --
    a generic "you'll receive a diploma" statement with no MSc/MBA/etc
    qualifier, previously not recognised as a degree signal at all and so
    fell all the way to the certificate-of-participation default."""
    code, needs_review = guess_degree("Je ontvangt na afloop van de opleiding een diploma.", "")
    assert code == "diploma"
    assert needs_review is False


def test_contact_override_wins_over_a_scraped_contact():
    """BUG FOUND 2026-09-24: contactName/contactEmail overrides used to only
    take effect when the scraper found NO contact at all (`scraped.contact_name
    or override.get("contactName")`) -- unlike every other override key, where
    the override always wins. That silently made a contactName/contactEmail
    override dead code the moment a page had (or later gained) any scraped
    contact of its own. Uses the fixture, which has a real scraped contact
    (pdo.vm.sbe@vu.nl / Lilian Dekker), to confirm the override now wins."""
    p = load_fixture()
    assert p.contact_email  # sanity: fixture really does have a scraped contact
    element, review = build_program_xml(
        p, org_unit_id="vu", editor_email="edudex@vu.nl", generator_name="test", expires_in_days=21,
        override={"contactName": "Program Desk", "contactEmail": "programdesk@vu.nl"},
    )
    reparsed = ET.fromstring(ET.tostring(element, encoding="utf-8"))
    ns = "{http://studieData.nl/schema/edudex/program}"
    contact_data = reparsed.find(f"{ns}programContacts/{ns}contactData")
    assert contact_data.find(f"{ns}contactName").text == "Program Desk"
    assert contact_data.find(f"{ns}email").text == "programdesk@vu.nl"
    assert "programContacts" not in review


def test_contact_fallback_still_used_when_neither_scrape_nor_override_has_one():
    p = ScrapedProgram(url="https://vu.nl/nl/onderwijs/professionals/cursussen-opleidingen/no-contact-page")
    p.title = "No Contact Page"
    element, review = build_program_xml(
        p, org_unit_id="vu", editor_email="edudex@vu.nl", generator_name="test", expires_in_days=21,
        override={},
    )
    reparsed = ET.fromstring(ET.tostring(element, encoding="utf-8"))
    ns = "{http://studieData.nl/schema/edudex/program}"
    contact_data = reparsed.find(f"{ns}programContacts/{ns}contactData")
    from edudex_feed.mapping import FALLBACK_CONTACT_NAME, FALLBACK_CONTACT_EMAIL
    assert contact_data.find(f"{ns}contactName").text == FALLBACK_CONTACT_NAME
    assert contact_data.find(f"{ns}email").text == FALLBACK_CONTACT_EMAIL
    assert "programContacts" in review


if __name__ == "__main__":
    test_head_fields()
    test_facts_extracted()
    test_contact_extracted()
    test_description_paragraphs()
    test_heading_extracted()
    test_xml_generation_is_well_formed_and_has_mandatory_elements()
    test_extract_price_handles_english_and_dutch_thousands_separators()
    test_looks_like_range_or_itemized_ignores_unrelated_numbers()
    test_first_fact_matches_compound_labels_by_substring()
    test_first_fact_does_not_match_search_term_fused_onto_another_word()
    test_guess_degree_prefers_explicit_diploma_fact()
    test_guess_degree_falls_back_to_body_text_keyword()
    test_guess_degree_defaults_to_certificate_when_nothing_found()
    test_guess_degree_ignores_keyword_hiding_inside_an_unrelated_word()
    test_guess_degree_ignores_a_lecturers_own_credentials_in_a_bio()
    test_guess_degree_body_text_match_is_always_flagged_for_review()
    test_degree_and_cost_wired_into_generated_xml()
    test_range_cost_flagged_and_raw_text_surfaced()
    test_cost_multiplied_by_duration_when_stated_per_period()
    test_cost_copied_as_is_when_no_per_period_wording()
    test_cost_per_unrecognized_period_is_flagged_not_guessed()
    test_cost_per_period_flagged_when_duration_unknown()
    test_tuition_fee_override_is_not_multiplied()
    test_extract_duration_returns_none_on_failed_parse()
    test_extract_duration_handles_dutch_weken_plural()
    test_program_duration_flagged_and_defaulted_when_unparseable()
    test_program_location_defaults_to_vu_campus_amsterdam()
    test_parse_usp_bar_extracts_icon_blocks_as_facts()
    test_usp_bar_facts_do_not_override_a_real_fact_bullet()
    test_parse_accordion_facts_extracts_label_and_value()
    test_program_type_and_form_fall_back_to_usp_bar_when_no_fact_list_exists()
    test_program_type_prefers_usp_bar_over_a_title_with_no_type_keyword()
    test_extract_duration_handles_a_trailing_plus_sign()
    test_extract_duration_handles_an_adjective_between_number_and_unit()
    test_select_cost_text_prefers_regular_price_over_early_bird_discount()
    test_select_cost_text_recognises_prijs_and_price_labels()
    test_prefer_total_over_per_unit_amount_picks_the_series_total()
    test_prefer_total_over_per_unit_amount_leaves_flat_prices_unchanged()
    test_actualiteitenlezingen_pensioenrecht_end_to_end_cost()
    test_detect_program_location_finds_confirmed_off_campus_exception()
    test_detect_program_location_does_not_flag_the_default_amsterdam_venue()
    test_program_location_override_still_wins_over_detection()
    test_guess_degree_catches_informal_ze_pronoun_and_accreditation_cue()
    test_guess_degree_merges_standalone_title_abbreviation_into_next_sentence()
    test_guess_degree_recognises_generic_diploma_accordion_fact()
    test_contact_override_wins_over_a_scraped_contact()
    test_contact_fallback_still_used_when_neither_scrape_nor_override_has_one()
    print("all tests passed")

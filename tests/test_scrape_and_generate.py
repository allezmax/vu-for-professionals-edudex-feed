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
from edudex_feed.scrape import ScrapedProgram, _parse_head, _parse_main_body, _first_fact
from edudex_feed.xmlgen import (
    build_program_xml, _extract_price, _looks_like_range_or_itemized, _extract_duration, _apply_cost_period,
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
    test_program_duration_flagged_and_defaulted_when_unparseable()
    test_program_location_defaults_to_vu_campus_amsterdam()
    print("all tests passed")

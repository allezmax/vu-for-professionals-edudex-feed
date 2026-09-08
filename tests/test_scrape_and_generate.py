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
from edudex_feed.scrape import ScrapedProgram, _parse_head, _parse_main_body
from edudex_feed.xmlgen import build_program_xml

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
    assert "paymentDue" in review


if __name__ == "__main__":
    test_head_fields()
    test_facts_extracted()
    test_contact_extracted()
    test_description_paragraphs()
    test_heading_extracted()
    test_xml_generation_is_well_formed_and_has_mandatory_elements()
    print("all tests passed")

"""
Unit tests for changelog.py's diff/hashing logic.

This sandbox can't reach vu.nl or the live GitHub Pages site, so these tests
work entirely against synthetic ScrapedProgram / snapshot dicts rather than
running main.run() end to end -- the goal is to pin down exactly which
situations do and don't produce a finding, and that the approval-hash
carry-forward behaves as agreed with Max (2026-09-24): a brand-new or
re-issued approval bakes in that run's values as the baseline, and any later
drift from that baseline flips the program to "stale" with no edit to
approvals.yaml required.
"""
import sys
from pathlib import Path
from xml.etree import ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from edudex_feed.scrape import ScrapedProgram
from edudex_feed.xmlgen import build_program_xml
from edudex_feed import changelog


def make_scraped(**kwargs) -> ScrapedProgram:
    p = ScrapedProgram(url=kwargs.pop("url", "https://vu.nl/nl/onderwijs/professionals/cursussen-opleidingen/test-program"))
    p.title = kwargs.pop("title", "Test Program")
    p.heading = p.title
    p.content_language = "nl"
    p.facts = kwargs.pop("facts", {})
    for k, v in kwargs.items():
        setattr(p, k, v)
    return p


def build(p: ScrapedProgram, override: dict | None = None):
    element, review = build_program_xml(
        p, org_unit_id="vu", editor_email="edudex@vu.nl", generator_name="test", expires_in_days=21,
        override=override or {},
    )
    return element, review


def entry_for(p: ScrapedProgram, override: dict | None = None) -> dict:
    override = override or {}
    element, _ = build(p, override)
    return {
        "program_id": "test-program",
        "title": p.title,
        "url": p.url,
        "signals": changelog.derive_source_signals(p, override),
        "xml_fields": changelog.extract_xml_fields(element),
        "override_keys": sorted(override.keys()),
    }


# --- extract_xml_fields --------------------------------------------------------------------

def test_extract_xml_fields_reads_back_duration_with_unit():
    p = make_scraped(facts={"Duur": "6 maanden"})
    element, _ = build(p)
    fields = changelog.extract_xml_fields(element)
    assert fields["programDuration"] == "6 month"


def test_compute_hash_is_stable_and_order_independent():
    a = {"x": "1", "y": "2"}
    b = {"y": "2", "x": "1"}
    assert changelog.compute_hash(a) == changelog.compute_hash(b)


def test_compute_hash_changes_when_a_value_changes():
    a = {"x": "1"}
    b = {"x": "2"}
    assert changelog.compute_hash(a) != changelog.compute_hash(b)


# --- Trigger 1: "cannot find data anymore" --------------------------------------------------

def test_data_missing_flagged_when_duration_fact_disappears():
    prev = entry_for(make_scraped(facts={"Duur": "6 maanden"}))
    curr = entry_for(make_scraped(facts={}))
    findings = changelog.diff_program("test-program", "Test Program", "url", prev, curr, [])
    kinds = [f["kind"] for f in findings]
    assert "data_missing" in kinds


def test_no_finding_when_nothing_changed():
    scraped_kwargs = dict(facts={"Duur": "6 maanden", "Kosten": "€ 5.000"})
    prev = entry_for(make_scraped(**scraped_kwargs))
    curr = entry_for(make_scraped(**scraped_kwargs))
    findings = changelog.diff_program("test-program", "Test Program", "url", prev, curr, [])
    assert findings == []


def test_no_finding_without_a_previous_baseline():
    curr = entry_for(make_scraped(facts={"Duur": "6 maanden"}))
    findings = changelog.diff_program("test-program", "Test Program", "url", None, curr, [])
    assert findings == []


def test_data_missing_flagged_when_contact_email_disappears():
    prev = entry_for(make_scraped(contact_email="info@vu.nl"))
    curr = entry_for(make_scraped(contact_email=None))
    findings = changelog.diff_program("test-program", "Test Program", "url", prev, curr, [])
    assert any(f["kind"] == "data_missing" for f in findings)


def test_data_missing_flagged_when_new_scrape_errors_appear():
    prev = entry_for(make_scraped(errors=[]))
    curr = entry_for(make_scraped(errors=["sub-page toelating: HTTP 404"]))
    findings = changelog.diff_program("test-program", "Test Program", "url", prev, curr, [])
    assert any(f["kind"] == "data_missing" for f in findings)


# --- Trigger 2: semantic basis shifted, not just a number -----------------------------------

def test_cost_basis_change_flagged_when_period_word_appears():
    """Max's own example: a price stops being a flat total and starts being
    billed per module (or vice versa) -- that's a semantic shift worth a
    look, independent of whatever the actual number is."""
    prev = entry_for(make_scraped(facts={"Kosten": "€ 9.750"}))
    curr = entry_for(make_scraped(facts={"Kosten": "€ 9.750 per module"}))
    findings = changelog.diff_program("test-program", "Test Program", "url", prev, curr, [])
    assert any(f["kind"] == "cost_basis_changed" for f in findings)


def test_cost_basis_change_flagged_when_period_word_changes():
    prev = entry_for(make_scraped(facts={"Kosten": "€ 9.750 per jaar"}))
    curr = entry_for(make_scraped(facts={"Kosten": "€ 9.750 per module"}))
    findings = changelog.diff_program("test-program", "Test Program", "url", prev, curr, [])
    assert any(f["kind"] == "cost_basis_changed" for f in findings)


def test_no_cost_basis_finding_for_a_plain_number_change():
    """A price moving from 5000 to 5200 with the same phrasing is NOT a
    semantic-basis change and should not be flagged by this check (it may
    still show up in report.md via a fresh review flag if it becomes
    unparseable, but that's a different mechanism)."""
    prev = entry_for(make_scraped(facts={"Kosten": "€ 5.000"}))
    curr = entry_for(make_scraped(facts={"Kosten": "€ 5.200"}))
    findings = changelog.diff_program("test-program", "Test Program", "url", prev, curr, [])
    assert not any(f["kind"] == "cost_basis_changed" for f in findings)


def test_duration_unit_change_flagged():
    prev = entry_for(make_scraped(facts={"Duur": "12 weken"}))
    curr = entry_for(make_scraped(facts={"Duur": "3 maanden"}))
    findings = changelog.diff_program("test-program", "Test Program", "url", prev, curr, [])
    assert any(f["kind"] == "duration_unit_changed" for f in findings)


# --- Traceability: manual overrides that may have gone stale ---------------------------------

def test_override_flagged_stale_when_underlying_page_text_changes():
    prev = entry_for(make_scraped(facts={"Duur": "6 maanden"}), override={"programLocation": "x"})
    curr = entry_for(make_scraped(facts={"Duur": "9 maanden"}), override={"programLocation": "x"})
    findings = changelog.diff_program(
        "test-program", "Test Program", "url", prev, curr, override_keys=["programDuration"]
    )
    assert any(f["kind"] == "override_may_be_stale" for f in findings)


def test_override_not_flagged_stale_when_underlying_page_text_is_unchanged():
    scraped_kwargs = dict(facts={"Duur": "6 maanden"})
    prev = entry_for(make_scraped(**scraped_kwargs))
    curr = entry_for(make_scraped(**scraped_kwargs))
    findings = changelog.diff_program(
        "test-program", "Test Program", "url", prev, curr, override_keys=["programDuration"]
    )
    assert not any(f["kind"] == "override_may_be_stale" for f in findings)


# --- Approval hash carry-forward / auto-staleness --------------------------------------------

def test_new_approval_bakes_in_current_hash_as_baseline():
    entries = [entry_for(make_scraped(facts={"Duur": "6 maanden"}))]
    approvals_all = {"programs": {"test-program": {"approvedBy": "Jane", "approvedAt": "2026-09-24"}}}
    statuses = changelog.compute_approval_statuses(entries, approvals_all, prev_snapshot=None)
    assert statuses["test-program"]["status"] == "current"


def test_approval_stays_current_when_nothing_changed():
    entries = [entry_for(make_scraped(facts={"Duur": "6 maanden"}))]
    approvals_all = {"programs": {"test-program": {"approvedBy": "Jane", "approvedAt": "2026-09-24"}}}
    first = changelog.compute_approval_statuses(entries, approvals_all, prev_snapshot=None)
    prev_snapshot = {"programs": {"test-program": {"approval": first["test-program"]}}}
    second = changelog.compute_approval_statuses(entries, approvals_all, prev_snapshot=prev_snapshot)
    assert second["test-program"]["status"] == "current"
    assert second["test-program"]["approvedHash"] == first["test-program"]["approvedHash"]


def test_approval_auto_clears_to_stale_when_value_changes_after_signoff():
    """Confirmed with Max (2026-09-24): an approval only certifies the exact
    values it was given -- if those values move afterward, the program
    should automatically fall back to needing re-review, with no edit to
    approvals.yaml required."""
    approvals_all = {"programs": {"test-program": {"approvedBy": "Jane", "approvedAt": "2026-09-24"}}}
    entries_at_approval = [entry_for(make_scraped(facts={"Duur": "6 maanden"}))]
    first = changelog.compute_approval_statuses(entries_at_approval, approvals_all, prev_snapshot=None)
    assert first["test-program"]["status"] == "current"

    prev_snapshot = {"programs": {"test-program": {"approval": first["test-program"]}}}
    entries_after_change = [entry_for(make_scraped(facts={"Duur": "12 maanden"}))]
    second = changelog.compute_approval_statuses(entries_after_change, approvals_all, prev_snapshot=prev_snapshot)
    assert second["test-program"]["status"] == "stale"
    # the baseline hash is preserved from the actual approval moment, not silently re-baselined
    assert second["test-program"]["approvedHash"] == first["test-program"]["approvedHash"]


def test_re_approval_rebaselines_to_the_new_current_hash():
    approvals_v1 = {"programs": {"test-program": {"approvedBy": "Jane", "approvedAt": "2026-09-24"}}}
    entries_v1 = [entry_for(make_scraped(facts={"Duur": "6 maanden"}))]
    first = changelog.compute_approval_statuses(entries_v1, approvals_v1, prev_snapshot=None)
    prev_snapshot = {"programs": {"test-program": {"approval": first["test-program"]}}}

    # value changed, then a program manager re-approves with a new date
    entries_v2 = [entry_for(make_scraped(facts={"Duur": "12 maanden"}))]
    approvals_v2 = {"programs": {"test-program": {"approvedBy": "Jane", "approvedAt": "2026-10-01"}}}
    second = changelog.compute_approval_statuses(entries_v2, approvals_v2, prev_snapshot=prev_snapshot)
    assert second["test-program"]["status"] == "current"
    assert second["test-program"]["approvedHash"] != first["test-program"]["approvedHash"]


def test_program_with_no_approvals_entry_has_no_status():
    entries = [entry_for(make_scraped(facts={"Duur": "6 maanden"}))]
    statuses = changelog.compute_approval_statuses(entries, {"programs": {}}, prev_snapshot=None)
    assert statuses == {}


# --- changelog.md rendering -------------------------------------------------------------------

def test_update_changelog_text_is_a_no_op_without_findings():
    text = changelog.CHANGELOG_HEADER
    result = changelog.update_changelog_text(text, "2026-09-24", [])
    assert result == text


def test_update_changelog_text_inserts_newest_entry_right_after_the_marker():
    text = changelog.CHANGELOG_HEADER
    findings = [{"kind": "data_missing", "program_id": "p1", "title": "Program One", "url": "u", "detail": "gone"}]
    result = changelog.update_changelog_text(text, "2026-09-24", findings)
    assert changelog.CHANGELOG_MARKER in result
    assert "## 2026-09-24" in result
    assert "Program One" in result
    # newest entry appears before any older entries already in the file
    marker_pos = result.index(changelog.CHANGELOG_MARKER)
    entry_pos = result.index("## 2026-09-24")
    assert marker_pos < entry_pos


if __name__ == "__main__":
    test_extract_xml_fields_reads_back_duration_with_unit()
    test_compute_hash_is_stable_and_order_independent()
    test_compute_hash_changes_when_a_value_changes()
    test_data_missing_flagged_when_duration_fact_disappears()
    test_no_finding_when_nothing_changed()
    test_no_finding_without_a_previous_baseline()
    test_data_missing_flagged_when_contact_email_disappears()
    test_data_missing_flagged_when_new_scrape_errors_appear()
    test_cost_basis_change_flagged_when_period_word_appears()
    test_cost_basis_change_flagged_when_period_word_changes()
    test_no_cost_basis_finding_for_a_plain_number_change()
    test_duration_unit_change_flagged()
    test_override_flagged_stale_when_underlying_page_text_changes()
    test_override_not_flagged_stale_when_underlying_page_text_is_unchanged()
    test_new_approval_bakes_in_current_hash_as_baseline()
    test_approval_stays_current_when_nothing_changed()
    test_approval_auto_clears_to_stale_when_value_changes_after_signoff()
    test_re_approval_rebaselines_to_the_new_current_hash()
    test_program_with_no_approvals_entry_has_no_status()
    test_update_changelog_text_is_a_no_op_without_findings()
    test_update_changelog_text_inserts_newest_entry_right_after_the_marker()
    print("all tests passed")

"""
Change detection and program-manager sign-off tracking for the EDU-DEX feed.

Motivation (Max, 2026-09-24): once the feed is largely automated, the two
things that actually need a person's attention are (1) the scraper silently
losing its grip on a page ("you cannot find data anymore because the source
format of the page changed") and (2) a value's *semantic basis* shifting in
a way a plain number-diff wouldn't catch ("a price is not communicated by
module anymore but for an entire program"). Separately, Max wants to be able
to trace any field whose feed value came from a hand-typed entry in
``config/overrides.yaml`` rather than from the live crawl -- because a few
overridden values (price, contact) aren't published on vu.nl at all, so nothing
else would ever notice them going stale.

This module handles all of that by comparing each run's derived data against
a ``snapshot.json`` published alongside the feed on the previous run, and by
maintaining a running ``changelog.md`` -- both written into ``feed_dir``
(next to directory.xml/programs/*.xml/report.md) so they're served straight
off GitHub Pages with no git write-back needed. The GitHub Actions workflow
for this repo never commits anything back to the repo (see
.github/workflows/build-feed.yml -- it only builds and deploys to Pages), so
"the previous run's state" has to be fetched back over plain HTTP at the
start of the next run rather than read from git history.

Sign-off tracking (config/approvals.yaml) works the same way: a program
manager's approval is only ever recorded as ``approvedBy``/``approvedAt`` in
that file (no hash to fill in by hand). The moment a NEW approval shows up
there (or an existing one's approvedAt/approvedBy changes -- a re-approval),
this module bakes in a hash of that run's actual field values as the
baseline. Every later run recomputes the hash and compares it to that
baseline: if the values have since moved, the approval is automatically
treated as stale ("needs re-review") without anyone having to touch
approvals.yaml or overrides.yaml -- confirmed with Max (2026-09-24) as the
wanted behaviour, precisely so an approval can never silently keep covering
a value the program manager never actually saw.
"""
from __future__ import annotations

import hashlib
import json
import logging
from xml.etree import ElementTree as ET

import requests

from . import xmlgen

log = logging.getLogger(__name__)

NS_PROGRAM = xmlgen.NS["program"]

CHANGELOG_MARKER = "<!-- newest entries go directly below this line -->"

CHANGELOG_HEADER = f"""# EDU-DEX feed changelog

Automated notes on data changes this pipeline noticed between runs. This
file only grows when something is actually worth a look -- a run that finds
nothing new adds no entry. See `report.md` in this same folder for the
always-current list of fields still needing a human, and
`config/overrides.yaml` / `config/approvals.yaml` (in the repo) for the
manual-correction and sign-off records this file cross-references.

{CHANGELOG_MARKER}
"""

# Field names read back off the built <program> XML element for approval
# hashing -- i.e. the actual value the feed ships, after overrides have
# already won. Two programs whose feed output is identical hash the same,
# regardless of whether a value came from the live crawl or an override.
_APPROVAL_XML_FIELDS = [
    ("degree", "programClassification/degree"),
    ("programForm", "programClassification/programForm"),
    ("programLevel", "programClassification/programLevel"),
    ("programLocation", "programClassification/programLocation"),
    ("programType", "programClassification/programType"),
    ("contactName", "programContacts/contactData/contactName"),
    ("contactEmail", "programContacts/contactData/email"),
    ("cost", "programSchedule/genericProgramRun/cost/amount"),
    ("startText", "programSchedule/genericProgramRun/genericProgramRunFree"),
]


def _qualify(path: str) -> str:
    return "/".join(f"{{{NS_PROGRAM}}}{part}" for part in path.split("/"))


def extract_xml_fields(element: ET.Element) -> dict:
    """Pull the fields that matter for approval sign-off back out of an
    already-built <program> element, plus programDuration (which carries its
    unit as an attribute rather than a separate element).

    build_program_xml() sets its root's namespace via a literal "xmlns"
    attribute rather than through ElementTree's own namespace machinery, so
    the in-memory element's tags are NOT actually namespace-qualified --
    only a real XML parser reading the serialized form applies that. Every
    other place in this codebase that needs to query a built element
    (xmlgen's own tests) works around this the same way: round-trip it
    through tostring/fromstring first.
    """
    element = ET.fromstring(ET.tostring(element, encoding="utf-8"))
    fields: dict[str, str] = {}
    for name, path in _APPROVAL_XML_FIELDS:
        found = element.find(_qualify(path))
        fields[name] = (found.text or "") if found is not None else ""
    dur = element.find(_qualify("programClassification/programDuration"))
    if dur is not None:
        fields["programDuration"] = f"{dur.text} {dur.get('unit')}"
    else:
        fields["programDuration"] = ""
    return fields


def compute_hash(fields: dict) -> str:
    canonical = json.dumps(fields, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def derive_source_signals(scraped, override: dict) -> dict:
    """Snapshot of the raw, pre-override facts a program's XML was derived
    from -- mirrors the exact lookups build_program_xml() itself makes (same
    functions, not reimplemented), so a page-template change or a semantic
    shift in the underlying text is caught the same way xmlgen would notice
    it, before any override has a chance to paper over it.
    """
    duration_fact_text = xmlgen._first_fact(scraped.facts, "Duur", "Duration") or ""
    # Duration unit derived from the page's own words alone (empty override),
    # regardless of whether an actual override is masking it in the XML --
    # we want "did the page's own stated unit change", not "did the emitted
    # unit change" (an active override would hide that entirely).
    natural_value, natural_unit = xmlgen._extract_duration(duration_fact_text, {})

    cost_fact_text = xmlgen._prefer_total_over_per_unit_amount(xmlgen._select_cost_text(scraped.facts)) or ""
    cost_period_word = xmlgen._cost_period_word(cost_fact_text) if cost_fact_text else None

    location_text, location_flagged = xmlgen._detect_program_location(scraped.facts)

    degree_fact_text = xmlgen._first_fact(scraped.facts, "Diploma", "Degree", "Titels", "Titles") or ""

    return {
        "duration_fact_text": duration_fact_text,
        "natural_duration_value": natural_value,
        "natural_duration_unit": natural_unit if natural_value is not None else None,
        "cost_fact_text": cost_fact_text,
        "cost_period_word": cost_period_word,
        "location_off_campus_detected": location_flagged,
        "location_text": location_text if location_flagged else "",
        "degree_fact_text": degree_fact_text,
        "contact_name_present": bool(scraped.contact_name),
        "contact_email_present": bool(scraped.contact_email),
        "contact_email": scraped.contact_email or "",
        "scrape_error_count": len(scraped.errors or []),
    }


def _override_keys(override: dict) -> list[str]:
    return sorted(override.keys()) if override else []


def diff_program(program_id: str, title: str, url: str, prev: dict, curr: dict, override_keys: list[str]) -> list[dict]:
    """Compare one program's previous vs current source signals. Returns a
    list of finding dicts: {kind, program_id, title, url, detail}."""
    findings = []

    def add(kind: str, detail: str):
        findings.append({"kind": kind, "program_id": program_id, "title": title, "url": url, "detail": detail})

    prev_sig = prev.get("signals", {}) if prev else {}
    curr_sig = curr.get("signals", {})
    if not prev:
        return findings  # no baseline yet -- nothing to diff against

    # --- Trigger 1 (Max): "cannot find data anymore" -----------------------------------
    if prev_sig.get("duration_fact_text") and not curr_sig.get("duration_fact_text"):
        add("data_missing", "could previously read a 'Duur'/'Duration' bullet off this page; can no longer find one -- the page's format may have changed")
    if prev_sig.get("cost_fact_text") and not curr_sig.get("cost_fact_text"):
        add("data_missing", "could previously read a cost/price bullet off this page; can no longer find one -- the page's format may have changed")
    if prev_sig.get("degree_fact_text") and not curr_sig.get("degree_fact_text"):
        add("data_missing", "could previously read a 'Diploma'/'Titels' bullet off this page; can no longer find one")
    if prev_sig.get("contact_email_present") and not curr_sig.get("contact_email_present"):
        add("data_missing", "a contact email was previously scraped off this page; none found this run")
    if not prev_sig.get("scrape_error_count") and curr_sig.get("scrape_error_count"):
        add("data_missing", f"{curr_sig['scrape_error_count']} scrape error(s) appeared this run where there were none before -- see data/scraped.json for detail")

    # --- Trigger 2 (Max): semantic basis shifted, not just a number ------------------------
    if prev_sig.get("cost_fact_text") and curr_sig.get("cost_fact_text"):
        prev_period = prev_sig.get("cost_period_word")
        curr_period = curr_sig.get("cost_period_word")
        if prev_period != curr_period:
            was = f"per {prev_period}" if prev_period else "a flat one-off total"
            now = f"per {curr_period}" if curr_period else "a flat one-off total"
            add("cost_basis_changed", f"cost used to be priced {was}, now reads as {now} -- please re-check the tuition amount (and any 'tuitionFeeAmount' override still fits)")

    if prev_sig.get("natural_duration_unit") and curr_sig.get("natural_duration_unit"):
        if prev_sig["natural_duration_unit"] != curr_sig["natural_duration_unit"]:
            add(
                "duration_unit_changed",
                f"duration's own unit changed from '{prev_sig['natural_duration_unit']}' to "
                f"'{curr_sig['natural_duration_unit']}' -- please re-check programDuration"
                + (" (and any 'programDuration' override still fits)" if "programDuration" in override_keys else ""),
            )

    if prev_sig.get("location_off_campus_detected") != curr_sig.get("location_off_campus_detected"):
        if curr_sig.get("location_off_campus_detected"):
            add("location_detection_changed", f"page text now mentions an off-campus venue ('{curr_sig.get('location_text')}') that wasn't there before -- please confirm programLocation")
        else:
            add("location_detection_changed", "page text no longer mentions the off-campus venue it previously did -- please confirm programLocation is still correct")

    # --- Traceability (Max): a manual override may now be stale -----------------------------
    if override_keys:
        if "programDuration" in override_keys and prev_sig.get("duration_fact_text") != curr_sig.get("duration_fact_text"):
            add("override_may_be_stale", "programDuration is manually overridden, but the page's own 'Duur' text has changed since -- worth confirming the override still matches reality")
        if "tuitionFeeAmount" in override_keys and prev_sig.get("cost_fact_text") != curr_sig.get("cost_fact_text"):
            add("override_may_be_stale", "tuitionFeeAmount is manually overridden, but the page's own cost text has changed since -- worth confirming the override still matches reality")
        if "degree" in override_keys and prev_sig.get("degree_fact_text") != curr_sig.get("degree_fact_text"):
            add("override_may_be_stale", "degree is manually overridden, but the page's own 'Diploma'/'Titels' text has changed since -- worth confirming the override still matches reality")
        if ("contactName" in override_keys or "contactEmail" in override_keys) and prev_sig.get("contact_email") != curr_sig.get("contact_email"):
            add("override_may_be_stale", "contact details are manually overridden, but the page's own scraped contact has changed since -- worth confirming the override still matches reality")

    return findings


def fetch_previous_snapshot(base_url: str) -> dict | None:
    url = f"{base_url.rstrip('/')}/snapshot.json"
    try:
        resp = requests.get(url, timeout=15)
    except requests.RequestException as exc:
        log.warning("could not fetch previous snapshot.json (%s): %s -- treating as first run", url, exc)
        return None
    if resp.status_code != 200:
        log.info("no previous snapshot.json at %s (status %s) -- treating as first run", url, resp.status_code)
        return None
    try:
        return resp.json()
    except ValueError:
        log.warning("previous snapshot.json at %s was not valid JSON -- treating as first run", url)
        return None


def fetch_previous_changelog(base_url: str) -> str:
    url = f"{base_url.rstrip('/')}/changelog.md"
    try:
        resp = requests.get(url, timeout=15)
    except requests.RequestException:
        return CHANGELOG_HEADER
    if resp.status_code != 200 or CHANGELOG_MARKER not in resp.text:
        return CHANGELOG_HEADER
    return resp.text


def compute_approval_statuses(entries: list[dict], approvals_all: dict, prev_snapshot: dict | None) -> dict:
    """entries: [{"program_id", "xml_fields", ...}, ...] for THIS run.
    Returns {program_id: {"approvedBy", "approvedAt", "approvedHash", "status"}}
    for every program that has an entry in config/approvals.yaml.
    """
    approvals_cfg = (approvals_all.get("programs") or {}) if approvals_all else {}
    prev_programs = (prev_snapshot or {}).get("programs", {})
    statuses = {}
    for e in entries:
        pid = e["program_id"]
        cfg = approvals_cfg.get(pid)
        if not cfg:
            continue
        current_hash = compute_hash(e["xml_fields"])
        prev_approval = (prev_programs.get(pid, {}) or {}).get("approval") or {}
        is_same_signoff = (
            prev_approval.get("approvedAt") == cfg.get("approvedAt")
            and prev_approval.get("approvedBy") == cfg.get("approvedBy")
            and prev_approval.get("approvedHash")
        )
        baseline_hash = prev_approval["approvedHash"] if is_same_signoff else current_hash
        statuses[pid] = {
            "approvedBy": cfg.get("approvedBy"),
            "approvedAt": cfg.get("approvedAt"),
            "approvedHash": baseline_hash,
            "status": "current" if current_hash == baseline_hash else "stale",
        }
    return statuses


def render_changelog_entry(run_date: str, findings: list[dict]) -> str:
    lines = [f"## {run_date}", ""]
    by_program: dict[str, list[dict]] = {}
    for f in findings:
        by_program.setdefault(f["program_id"], []).append(f)
    for pid, items in by_program.items():
        title = items[0]["title"] or pid
        lines.append(f"**{title}** (`{pid}`)")
        for f in items:
            lines.append(f"- {f['detail']}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def update_changelog_text(previous_text: str, run_date: str, findings: list[dict]) -> str:
    if not findings:
        return previous_text
    entry = render_changelog_entry(run_date, findings)
    marker = CHANGELOG_MARKER
    idx = previous_text.find(marker)
    if idx == -1:
        previous_text = CHANGELOG_HEADER
        idx = previous_text.find(marker)
    insert_at = idx + len(marker)
    before, after = previous_text[:insert_at], previous_text[insert_at:]
    after_tail = after.lstrip("\n")
    return f"{before}\n\n{entry}\n{after_tail}" if after_tail.strip() else f"{before}\n\n{entry}"


def run_change_detection(
    *,
    base_url: str,
    feed_dir,
    run_date: str,
    entries: list[dict],
    approvals_all: dict,
) -> tuple[list[dict], dict]:
    """entries: one dict per program this run, each with:
        program_id, title, url, signals (derive_source_signals output),
        xml_fields (extract_xml_fields output), override_keys (list[str])

    Writes snapshot.json + changelog.md into feed_dir. Returns
    (findings_this_run, approval_statuses) for main.py to fold into report.md.
    """
    prev_snapshot = fetch_previous_snapshot(base_url)
    prev_programs = (prev_snapshot or {}).get("programs", {})

    findings: list[dict] = []
    curr_programs: dict[str, dict] = {}

    seen_ids = {e["program_id"] for e in entries}
    for pid, prev_entry in prev_programs.items():
        if pid not in seen_ids:
            findings.append({
                "kind": "program_removed",
                "program_id": pid,
                "title": prev_entry.get("title") or pid,
                "url": prev_entry.get("url") or "",
                "detail": "no longer appears in the discovered catalog -- discontinued, or did discovery miss it?",
            })

    for e in entries:
        pid = e["program_id"]
        prev_entry = prev_programs.get(pid)
        curr_entry = {
            "title": e["title"],
            "url": e["url"],
            "signals": e["signals"],
            "override_keys": e["override_keys"],
        }
        if prev_entry is None:
            findings.append({
                "kind": "new_program",
                "program_id": pid,
                "title": e["title"],
                "url": e["url"],
                "detail": "newly appeared in the discovered catalog",
            })
        else:
            findings.extend(diff_program(pid, e["title"], e["url"], prev_entry, curr_entry, e["override_keys"]))
        curr_programs[pid] = curr_entry

    approval_statuses = compute_approval_statuses(entries, approvals_all, prev_snapshot)
    for pid, status in approval_statuses.items():
        if pid in curr_programs:
            curr_programs[pid]["approval"] = status

    snapshot = {"generated_at": run_date, "programs": curr_programs}
    (feed_dir / "snapshot.json").write_text(json.dumps(snapshot, indent=2, ensure_ascii=False), encoding="utf-8")

    previous_changelog = fetch_previous_changelog(base_url)
    new_changelog = update_changelog_text(previous_changelog, run_date, findings)
    (feed_dir / "changelog.md").write_text(new_changelog, encoding="utf-8")

    return findings, approval_statuses

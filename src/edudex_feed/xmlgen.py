"""
Turn scraped + configured program data into EDU-DEX-compliant XML.

Produces, under ``feed/``:
  - institute.xml         (one file, describing VU / the org unit)
  - programs/<programId>.xml   (one file per program)
  - directory.xml         (the address book EDU-DEX actually polls)

XML namespaces and root-element headers below are taken verbatim from
EDU-DEX's own technical manual (https://edudex.nl/edudox/ -> "meer
documentatie" -> technical infrastructure chapter, section 5.16 "XML
headers"). Element names, cardinalities and enumerations for the ``program``
file come from EDU-DEX's own reference tool
(https://edudex.nl/edudox/ -> "program" tab), captured in mapping.py.

The ``directory.xml`` field list is comparatively lightly documented, so
validate.py double-checks every generated file against the live XSD at
http://studieData.nl/schema/edudex/*.xsd on every run -- treat that as the
final authority, not this file.
"""
from __future__ import annotations

import datetime as dt
from xml.etree import ElementTree as ET
from xml.dom import minidom

from .mapping import normalize_enum, guess_program_level, guess_degree, VU_FORM_TEXT_TO_CODE, VU_TYPE_TEXT_TO_CODE, \
    DEFAULT_PROGRAM_FORM, DEFAULT_PROGRAM_TYPE, DEFAULT_APPLICATION_TYPE, \
    DEFAULT_PAYMENT_DUE, DEFAULT_START_DATE_DETERMINATION, FALLBACK_CONTACT_NAME, FALLBACK_CONTACT_EMAIL
from .scrape import ScrapedProgram, _first_fact

NS = {
    "directory": "http://studieData.nl/schema/edudex/directory",
    "program": "http://studieData.nl/schema/edudex/program",
    "institute": "http://studieData.nl/schema/edudex/institute",
    "xsi": "http://www.w3.org/2001/XMLSchema-instance",
}


def _pretty(elem: ET.Element) -> bytes:
    rough = ET.tostring(elem, encoding="utf-8")
    reparsed = minidom.parseString(rough)
    # Drop blank lines toprettyxml tends to leave between text-only elements.
    pretty = reparsed.toprettyxml(indent="  ", encoding="utf-8")
    lines = [line for line in pretty.decode("utf-8").splitlines() if line.strip()]
    return ("\n".join(lines) + "\n").encode("utf-8")


def _sub(parent: ET.Element, tag: str, text: str | None = None, **attrs) -> ET.Element:
    el = ET.SubElement(parent, tag, attrs)
    if text is not None:
        el.text = text
    return el


def slugify_program_id(scraped: ScrapedProgram, fallback_index: int) -> str:
    if scraped.vu_id:
        return scraped.vu_id
    # last path segment of the URL, e.g. "basisopleiding-verandermanagement"
    parts = [p for p in scraped.url.rstrip("/").split("/") if p]
    return parts[-1] if parts else f"program-{fallback_index}"


def build_program_xml(
    scraped: ScrapedProgram,
    *,
    org_unit_id: str,
    editor_email: str,
    generator_name: str,
    expires_in_days: int,
    override: dict | None = None,
) -> tuple[ET.Element, dict]:
    """Build one <program> element.

    Returns (element, review_notes) -- review_notes lists every field this
    function had to guess at, so it can be surfaced in the run summary.
    """
    override = override or {}
    review: dict[str, str] = {}

    root = ET.Element("program", {
        "xmlns": NS["program"],
        "xmlns:xsi": NS["xsi"],
        "xsi:schemaLocation": f"{NS['program']} {NS['program']}.xsd",
    })

    _sub(root, "editor", editor_email)
    expires = (dt.date.today() + dt.timedelta(days=expires_in_days)).isoformat()
    _sub(root, "expires", expires)
    _sub(root, "format", "EDU-DEX 1.0")
    _sub(root, "generator", generator_name)
    last_edited = scraped.last_modified or dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")
    _sub(root, "lastEdited", _to_iso_datetime(last_edited))

    # ---- programAdmission ----------------------------------------------------------------
    # NOTE: emitted before programClassification to match the element order shown in
    # EDU-DEX's own reference tool (https://edudex.nl/edudox/ -> "program" tab). Their
    # documentation doesn't say outright whether the schema uses xs:sequence (order-strict)
    # or xs:all (order-free) for the program's top-level children, so we play it safe and
    # match their own ordering; validate.py's live-XSD check will catch it either way if
    # this guess is wrong.
    pa = _sub(root, "programAdmission")
    _sub(pa, "applicationOpen", "true")

    app_type_code = override.get("applicationType", DEFAULT_APPLICATION_TYPE)
    _sub(pa, "applicationType", app_type_code)

    payment_due_code = override.get("paymentDue", DEFAULT_PAYMENT_DUE)
    _sub(pa, "paymentDue", payment_due_code)
    if "paymentDue" not in override:
        review["paymentDue"] = f"defaulted to '{payment_due_code}' -- not stated on the page, confirm with finance/PDO"

    start_date_code = override.get("startDateDetermination", DEFAULT_START_DATE_DETERMINATION)
    _sub(pa, "startDateDetermination", start_date_code)

    # ---- programClassification ---------------------------------------------------------
    # NOTE: programClassification's children MUST appear in exactly this order --
    # confirmed against the live XSD (http://studieData.nl/schema/edudex/program.xsd),
    # which declares them inside an xs:sequence (order-strict, not xs:all):
    #   degree, orgUnitId, programDuration, programForm, programId, programLevel,
    #   programLocation, programType (other siblings are optional and omitted here).
    pc = _sub(root, "programClassification")
    program_id = override.get("programId") or slugify_program_id(scraped, 0)

    if "degree" in override:
        degree_code = override["degree"]
    else:
        # Prefer an explicit "Diploma"/"Titels" ("Degree"/"Titles") fact bullet when the
        # page states one (e.g. "Diploma: MSc") -- that's a real statement, not a guess.
        # Falls back to a keyword scan of title/heading/description (catches "PhD in
        # Business Administration", "... Master of Science ..." in the program name
        # itself), then to the "certificate of participation" default. Per Max
        # (2026-09-10): PhDs obviously finish with a PhD and VU runs a number of MSc
        # programs -- defaulting every program to a certificate was wrong for those.
        degree_fact = _first_fact(scraped.facts, "Diploma", "Degree", "Titels", "Titles")
        # Unlike programLevel's title/heading/meta_description-only text, the degree
        # keyword (e.g. "Master of Science (MSc)") often only appears in body copy --
        # confirmed live 2026-09-10 on the Deeltijd Master Bedrijfskunde page, where
        # it's a bullet under "Wat levert de Master Bedrijfskunde je op?", not in the
        # title/heading/meta description at all -- so the body paragraphs are searched
        # too.
        degree_text = " ".join(filter(None, [
            scraped.title, scraped.heading, scraped.meta_description,
            " ".join(scraped.description_paragraphs), scraped.curriculum_text, scraped.admission_text,
        ]))
        degree_code, degree_needs_review = guess_degree(degree_fact, degree_text)
        if degree_needs_review:
            review["degree"] = (
                f"defaulted to '{degree_code}' -- no 'Diploma'/'Titels' fact bullet and no "
                f"PhD/MSc/MBA/DBA/LLM keyword found in title/heading/description; confirm "
                f"what VU actually issues on completion"
            )
    _sub(pc, "degree", degree_code)

    _sub(pc, "orgUnitId", org_unit_id)

    duration_value, duration_unit = _extract_duration(_first_fact(scraped.facts, "Duur", "Duration"), override)
    dur_el = _sub(pc, "programDuration", str(duration_value))
    dur_el.set("unit", duration_unit)
    if duration_value is None:
        review["programDuration"] = "could not parse a duration from the page; defaulted to 1 month"

    form_text = override.get("programForm") or _first_fact(scraped.facts, "Vorm", "Form")
    form_code, matched = normalize_enum(form_text, VU_FORM_TEXT_TO_CODE, DEFAULT_PROGRAM_FORM)
    _sub(pc, "programForm", form_code)
    if not matched:
        review["programForm"] = f"guessed '{form_code}' from '{form_text}' -- verify"

    _sub(pc, "programId", program_id)

    if "programLevel" in override:
        level_code = override["programLevel"]
    else:
        level_text = " ".join(filter(None, [scraped.title, scraped.heading, scraped.meta_description]))
        level_code, level_needs_review = guess_program_level(level_text)
        if level_needs_review:
            review["programLevel"] = (
                f"guessed '{level_code}' from title/heading/description text -- please "
                f"confirm and add a 'programLevel' override in overrides.yaml if wrong"
            )
    _sub(pc, "programLevel", level_code)

    location = override.get("programLocation") or "Amsterdam"
    _sub(pc, "programLocation", location)

    type_text = override.get("programType") or (scraped.title or "")
    type_code, matched = normalize_enum(type_text, VU_TYPE_TEXT_TO_CODE, DEFAULT_PROGRAM_TYPE)
    _sub(pc, "programType", type_code)
    if not matched:
        review["programType"] = f"guessed '{type_code}' -- verify against VU's own classification"

    # ---- programContacts -------------------------------------------------------------------
    # NOTE: the feed editor (editor_email, m.merz@vu.nl) builds/maintains the feed but is
    # never a contact person for students or programs -- per VU (2026-09-08), when a page
    # has no scraped contact this MUST fall back to a named contact, not the editor address.
    contacts = _sub(root, "programContacts")
    contact_data = _sub(contacts, "contactData")
    _sub(contact_data, "contactName", scraped.contact_name or override.get("contactName") or FALLBACK_CONTACT_NAME)
    _sub(contact_data, "email", scraped.contact_email or override.get("contactEmail") or FALLBACK_CONTACT_EMAIL)
    _sub(contact_data, "role", scraped.contact_role or "informatie")
    if scraped.contact_phone:
        _sub(contact_data, "telephone", scraped.contact_phone)
    if not scraped.contact_email:
        review["programContacts"] = (
            f"no contact email found on the page; used the fallback contact "
            f"({FALLBACK_CONTACT_NAME} / {FALLBACK_CONTACT_EMAIL})"
        )

    # ---- programCurriculum -------------------------------------------------------------------
    # Mandatory element, but every child (instructionMode, studyLoad, teacher...) is optional,
    # so an empty <programCurriculum/> is valid when we have nothing more specific to say.
    # The free-text curriculum description itself is carried in programDescriptions>subjectText
    # below (subject=curriculum), since that's where EDU-DEX documents it should live.
    _sub(root, "programCurriculum")

    # ---- programDescriptions -----------------------------------------------------------------
    # xml:lang reflects whichever language the actual scraped content came from
    # (scraped.content_language) rather than being hardcoded -- a program whose Dutch
    # page was a stub and got scraped from its English alternate must be tagged "en",
    # not mislabeled as Dutch text. See scrape.py's stub-page fallback.
    lang = scraped.content_language or "nl"
    desc = _sub(root, "programDescriptions")
    display_name = scraped.heading or scraped.title or program_id
    name_el = _sub(desc, "programName", display_name[:200])
    name_el.set("xml:lang", lang)

    summary = (scraped.meta_description or (scraped.description_paragraphs[0] if scraped.description_paragraphs else "") or scraped.title or "")[:200]
    summary_el = _sub(desc, "programSummaryText", summary)
    summary_el.set("xml:lang", lang)

    long_desc = " ".join(scraped.description_paragraphs)[:1200] or summary
    desc_el = _sub(desc, "programDescriptionText", long_desc)
    desc_el.set("xml:lang", lang)

    if scraped.curriculum_text:
        subj = _sub(desc, "subjectText")
        _sub(subj, "subject", "curriculum")
        st = _sub(subj, "summaryText", scraped.curriculum_text[:500])
        st.set("xml:lang", lang)

    if scraped.admission_text:
        subj = _sub(desc, "subjectText")
        _sub(subj, "subject", "admission")
        st = _sub(subj, "summaryText", scraped.admission_text[:500])
        st.set("xml:lang", lang)

    # NOTE: newer-template pages have a dedicated "Dates and costs"/"Data en kosten"
    # page (see scrape.py's SUBPAGES_BY_LANG). Its prose often carries itemized/tiered
    # per-year pricing or a range (e.g. "Year 1 & 2: €12,000/year", "between €32.000
    # and €34.000") that can't be safely collapsed into the single <cost><amount>
    # below without guessing which figure is "the" price -- confirmed live
    # 2026-09-10. Surface the raw text here so it isn't silently lost even when the
    # single-amount parse below only captures part of the picture (e.g. the low end
    # of a range). "tuition fee" is a real EDU-DEX subject enum value (confirmed
    # against the live program.xsd).
    if scraped.dates_costs_text:
        subj = _sub(desc, "subjectText")
        _sub(subj, "subject", "tuition fee")
        st = _sub(subj, "summaryText", scraped.dates_costs_text[:500])
        st.set("xml:lang", lang)

    # ---- programSchedule ----------------------------------------------------------------------
    schedule = _sub(root, "programSchedule")
    generic_run = _sub(schedule, "genericProgramRun")
    # NOTE (2026-09-10): label list expanded beyond "Kosten"/"Costs"/"Cost" -- the
    # newer page template uses "Investering"/"Tuition fee(s)"/"Investment" instead
    # (confirmed live on the Deeltijd Master Bedrijfskunde and EMFC/PhD-in-Finance
    # pages). _first_fact now matches by substring, so a compound label like
    # "Investering tweejarige master" is found too, not just an exact "Investering".
    cost_fact_text = _first_fact(
        scraped.facts, "Kosten", "Costs", "Cost", "Investering", "Tuition fee", "Tuition fees", "Investment"
    )
    price = override.get("tuitionFeeAmount") or _extract_price(cost_fact_text)
    if price is not None:
        # NOTE: costData's children are order-strict per the live XSD:
        # amount, amountIsFinal, costType, currency, isRequiredCost (others optional/omitted).
        cost = _sub(generic_run, "cost")
        _sub(cost, "amount", str(price))
        _sub(cost, "amountIsFinal", "true")
        _sub(cost, "costType", "tuition fee")
        _sub(cost, "currency", "eur")
        _sub(cost, "isRequiredCost", "true")
        if _looks_like_range_or_itemized(cost_fact_text):
            review["cost"] = (
                f"'{cost_fact_text}' looks like a range or itemized/tiered price -- "
                f"emitted {price} eur (the first amount found), but please confirm "
                f"against the programme's own 'Dates and costs' page"
            )
    else:
        review["cost"] = (
            "could not parse a tuition-fee amount from any Kosten/Costs/Investering/"
            "Tuition fee bullet; no <cost> emitted"
            + (" -- see the 'tuition fee' subjectText for the page's raw cost text" if scraped.dates_costs_text else "")
        )

    # NOTE: genericProgramRun has no <summaryText> child in the live XSD (its only
    # free-text outlet is the untyped <genericProgramRunFree>) -- start-date hints
    # that don't parse into a real date go there instead of being dropped silently.
    start_text = override.get("startText") or _first_fact(scraped.facts, "Startdatum", "Start date", "Startdate", "Start")
    if start_text:
        _sub(generic_run, "genericProgramRunFree", start_text[:200])

    return root, review


def _extract_duration(text: str, override: dict) -> tuple[int | None, str]:
    if "programDuration" in override:
        return override["programDuration"].get("value", 1), override["programDuration"].get("unit", "month")
    import re
    # Dutch and English unit words, singular/plural, both mapping to the same
    # EDU-DEX unit codes -- course pages can be scraped in either language
    # (see scrape.py's stub-page/hreflang fallback).
    m = re.search(
        r"(\d+)\s*(dag(?:en)?|week(?:en)?|maand(?:en)?|jaar|jaren|day(?:s)?|week(?:s)?|month(?:s)?|year(?:s)?)",
        text.lower(),
    )
    if not m:
        return 1, "month"
    value = int(m.group(1))
    unit_word = m.group(2)
    if unit_word.startswith("dag") or unit_word.startswith("day"):
        unit = "day"
    elif unit_word.startswith("week"):
        unit = "week"
    elif unit_word.startswith("maand") or unit_word.startswith("month"):
        unit = "month"
    else:  # jaar/jaren/year/years
        unit = "year"
    return value, unit


def _extract_price(text: str) -> float | None:
    """Parse the first money amount out of a cost-bullet string.

    BUG FOUND 2026-09-10: the previous version (``r"([\\d.]+),?-?"``) only ever
    treated "." as a valid separator inside the number, so on an English page
    using comma as the thousands separator -- e.g. "Cost: €5,975" (confirmed
    live on the "Enterprise Risk & Compliance Management" course page) -- the
    regex stopped at the comma and returned just "5" (5.0 EUR instead of
    5975.0). Dutch pages use the opposite convention ("€ 27.500,-" = 27500,
    period as thousands separator, trailing ",-" meaning no cents), so any fix
    has to handle both.

    Approach: grab the first digit run (allowing embedded "." and ","), then
    decide which trailing separator (if any) is a real decimal point rather
    than a thousands separator by its digit count -- a separator followed by
    exactly 1-2 digits at the very end is a decimal amount (".56", ",50");
    followed by 3 digits it's a thousands grouping ("5,975", "7.250") and
    every other "." or "," in the number is always a thousands separator.
    """
    import re
    cleaned = text.replace("€", "").replace("&euro;", "").strip()
    m = re.search(r"\d[\d.,]*\d|\d", cleaned)
    if not m:
        return None
    raw = m.group(0)
    decimal_match = re.search(r"[.,](\d{1,2})$", raw)
    if decimal_match:
        integer_part = re.sub(r"[.,]", "", raw[: decimal_match.start()])
        normalized = f"{integer_part}.{decimal_match.group(1)}"
    else:
        normalized = re.sub(r"[.,]", "", raw)
    try:
        return float(normalized)
    except ValueError:
        return None


def _looks_like_range_or_itemized(text: str) -> bool:
    """True if a cost-bullet string contains more than one distinct money amount
    (a range like "between €32.000 and €34.000", or itemized figures like
    "€6000 / €4000") -- a single <cost><amount> can only carry one number, so
    these need a human to confirm which figure (if any single one) is right.

    Counts occurrences of the currency symbol itself rather than all digit runs
    in the text -- a cost bullet can legitimately contain other numbers that
    aren't part of the price at all, e.g. "€ 23.000 bij start in academisch
    jaar 2026-2027" contains the years 2026/2027 alongside a single, perfectly
    unambiguous amount. Only flag when more than one "€" actually appears.
    """
    return text.count("€") > 1


def _to_iso_datetime(value: str) -> str:
    """Best-effort conversion of an HTTP-date (RFC 1123) or ISO date to
    xs:dateTime. Falls back to 'now' if unparseable."""
    for fmt in ("%a, %d %b %Y %H:%M:%S %Z", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            parsed = dt.datetime.strptime(value, fmt)
            return parsed.strftime("%Y-%m-%dT%H:%M:%S")
        except ValueError:
            continue
    return dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")


def build_institute_xml(config: dict) -> ET.Element:
    # NOTE: instituteData's children are order-strict per the live XSD
    # (http://studieData.nl/schema/edudex/institute.xsd): editor, expires(opt),
    # format, generator, orgUnitId(opt), includeInCatalog(opt), lastEdited
    # (REQUIRED -- easy to miss), accreditation(opt), contactData(opt),
    # instituteDescriptionText(opt), instituteFoundingDate(opt), instituteKvK(opt),
    # instituteLocation(opt), instituteName (REQUIRED, needs xml:lang),
    # instituteSummaryText(opt), media(opt), webLink(opt), instituteDataFree(opt).
    # Also: there is no "website" or "location" element in this schema -- the
    # real names are "webLink" (plain anyURI text) and "instituteLocation"
    # (structured address), used below.
    root = ET.Element("instituteData", {
        "xmlns": NS["institute"],
        "xmlns:xsi": NS["xsi"],
        "xsi:schemaLocation": f"{NS['institute']} {NS['institute']}.xsd",
    })
    _sub(root, "editor", config["editor_email"])
    _sub(root, "format", "EDU-DEX 1.0")
    _sub(root, "generator", config["generator_name"])
    _sub(root, "orgUnitId", config["org_unit_id"])
    _sub(root, "lastEdited", dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S"))

    if config.get("city"):
        # institute.xsd's <address> complexType is order-strict:
        # geoCode(opt), addressType, city, country, house_number, street, zipcode.
        loc = _sub(root, "instituteLocation")
        _sub(loc, "id", "main")
        addr = _sub(loc, "address")
        street, house_number = _split_street_and_number(config.get("address", ""))
        _sub(addr, "addressType", "visitation")
        _sub(addr, "city", config["city"])
        _sub(addr, "country", "nl")
        _sub(addr, "house_number", house_number or "")
        _sub(addr, "street", street or config.get("address", ""))
        _sub(addr, "zipcode", config.get("zipcode", ""))

    name_el = _sub(root, "instituteName", config["institute_name"])
    name_el.set("xml:lang", "nl")

    if config.get("website"):
        web_el = _sub(root, "webLink", config["website"])
        web_el.set("xml:lang", "nl")

    return root


def _split_street_and_number(address: str) -> tuple[str, str]:
    """Split a Dutch-style 'Straatnaam 123' address into (street, house_number)."""
    import re
    m = re.match(r"^(.*?)\s+(\d+\w*)\s*$", address.strip())
    if m:
        return m.group(1), m.group(2)
    return address.strip(), ""


def build_directory_xml(
    config: dict,
    institute_url: str,
    programs: list[tuple[str, str]],
) -> ET.Element:
    """``programs`` is a list of (program_id, program_url) pairs.

    NOTE: edudexDirectory's children are order-strict per the live XSD
    (http://studieData.nl/schema/edudex/directory.xsd): editor, generator,
    version (REQUIRED -- NOT "format", which doesn't exist in this schema),
    lastEdited(opt), instituteDataResource(opt), orgUnitId, subDirectory*(opt),
    clientDiscountResource*(opt), programResource*(opt). Each programResource
    is itself a complex element with children clientId(opt), lastEdited(opt),
    programId (REQUIRED), resourceUrl (REQUIRED) -- it is NOT plain text.
    """
    root = ET.Element("edudexDirectory", {
        "xmlns": NS["directory"],
        "xmlns:xsi": NS["xsi"],
        "xsi:schemaLocation": f"{NS['directory']} {NS['directory']}.xsd",
    })
    _sub(root, "editor", config["editor_email"])
    _sub(root, "generator", config["generator_name"])
    _sub(root, "version", "1.0")
    _sub(root, "instituteDataResource", institute_url)
    _sub(root, "orgUnitId", config["org_unit_id"])
    for program_id, url in programs:
        pr = _sub(root, "programResource")
        _sub(pr, "programId", program_id)
        _sub(pr, "resourceUrl", url)
    return root


def write_pretty(elem: ET.Element, path: str) -> None:
    with open(path, "wb") as f:
        f.write(_pretty(elem))

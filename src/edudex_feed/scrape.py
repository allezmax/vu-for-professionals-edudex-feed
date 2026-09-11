"""
Scrape program detail pages on vu.nl.

vu.nl's "VU for Professionals" course pages are server-side rendered (verified
by inspecting the raw HTTP response, not just the post-JS DOM) EXCEPT for the
overview/filter listing page, which fetches its results client-side from
``POST https://vu.nl/api/search``. So:

  - discover.py drives a real browser (Playwright) against the listing page,
    because that's the only reliable way to trigger + read that search call.
  - this module (scrape.py) uses plain ``requests`` against individual
    program pages, which is faster/lighter and doesn't need a browser.

Each program is spread across up to four URLs, in one of two page templates VU
uses (per Max, 2026-09-10: the newer template is being rolled out "step by
step", so both are live at once and neither can be assumed):

  - the overview page itself                              (always exists)
  - older template, Dutch slugs (most programs today):
      <slug>/inhoud      (curriculum / content)
      <slug>/toelating   (admission / cost / practical)
  - newer template, adds a dedicated dates-and-costs page and uses different
    sub-page slugs per language (confirmed live 2026-09-10 against
    vu.nl/nl/.../controllersopleiding-executive-master-of-finance-control and
    vu.nl/en/.../part-time-phd-programme-in-finance -- both show the same four
    tabs: Overview/Overzicht, Curriculum/Inhoud, Admissions/Toelating,
    "Dates and costs"/"Data en kosten"):
      nl: <slug>/inhoud, <slug>/toelating, <slug>/data-en-kosten
      en: <slug>/curriculum, <slug>/admissions, <slug>/dates-and-costs

Some programs use different sub-page naming entirely; missing sub-pages are
skipped without failing the whole run. Which slug set to try is picked from
the scraped page's own content language (``content_language``, "nl" or "en")
since that's already the language whose sub-pages actually exist -- not from
the original request URL, which may itself have been the stub-page hreflang
fallback (see ``_is_stub_page``).
"""
from __future__ import annotations

import re
import time
import logging
from dataclasses import dataclass, field
from typing import Optional

import requests
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (compatible; VU-EduDexFeedBot/1.0; "
    "+https://vu.nl/nl/onderwijs/professionals)"
)

# (slug, category) pairs, keyed by content language. "category" is a stable
# internal name so downstream code can bucket text/facts by meaning rather
# than matching on the literal (language-specific) URL slug -- the same
# category exists in both languages even though the slug differs.
SUBPAGES_BY_LANG: dict[str, list[tuple[str, str]]] = {
    "nl": [("inhoud", "curriculum"), ("toelating", "admission"), ("data-en-kosten", "dates_costs")],
    "en": [("curriculum", "curriculum"), ("admissions", "admission"), ("dates-and-costs", "dates_costs")],
}

# Matches "<Label>: <value>" bullets inside the rich-text "in het kort" list,
# e.g. "Startdatum: 2 x per jaar in maart & in september", "Kosten: €7.250,-"
FACT_LINE_RE = re.compile(r"^\s*([A-Za-zëïüö/ ]{2,30}):\s*(.+)$")


@dataclass
class ScrapedProgram:
    url: str
    vu_id: Optional[str] = None
    title: Optional[str] = None
    meta_description: Optional[str] = None
    last_modified: Optional[str] = None
    canonical_url: Optional[str] = None
    english_url: Optional[str] = None
    dutch_url: Optional[str] = None
    content_language: str = "nl"
    content_source_url: Optional[str] = None
    heading: Optional[str] = None
    intro_text: Optional[str] = None
    description_paragraphs: list[str] = field(default_factory=list)
    facts: dict[str, str] = field(default_factory=dict)  # "Startdatum" -> "2 x per jaar in maart & september"
    contact_name: Optional[str] = None
    contact_role: Optional[str] = None
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    address_lines: list[str] = field(default_factory=list)
    admission_text: Optional[str] = None
    curriculum_text: Optional[str] = None
    dates_costs_text: Optional[str] = None
    sub_pages_fetched: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def _get(session: requests.Session, url: str, timeout: int = 20) -> Optional[BeautifulSoup]:
    try:
        resp = session.get(url, timeout=timeout, headers={"User-Agent": USER_AGENT, "Accept-Language": "nl"})
    except requests.RequestException as exc:
        log.warning("request failed for %s: %s", url, exc)
        return None
    if resp.status_code != 200:
        log.info("non-200 (%s) for %s", resp.status_code, url)
        return None
    resp.encoding = resp.encoding or "utf-8"
    return BeautifulSoup(resp.text, "html.parser")


def _parse_head(soup: BeautifulSoup, program: ScrapedProgram) -> None:
    if soup.title and soup.title.string:
        program.title = soup.title.string.strip()

    meta_desc = soup.find("meta", attrs={"name": "description"})
    if meta_desc and meta_desc.get("content"):
        program.meta_description = meta_desc["content"].strip()

    last_mod = soup.find("meta", attrs={"http-equiv": re.compile("last-modified", re.I)})
    if last_mod and last_mod.get("content"):
        program.last_modified = last_mod["content"].strip()

    vu_id = soup.find("meta", attrs={"property": "vu:id"})
    if vu_id and vu_id.get("content"):
        program.vu_id = vu_id["content"].strip()

    canonical = soup.find("link", rel="canonical")
    if canonical and canonical.get("href"):
        program.canonical_url = canonical["href"].strip()

    alt_en = soup.find("link", rel="alternate", hreflang="en")
    if alt_en and alt_en.get("href"):
        program.english_url = alt_en["href"].strip()

    alt_nl = soup.find("link", rel="alternate", hreflang="nl")
    if alt_nl and alt_nl.get("href"):
        program.dutch_url = alt_nl["href"].strip()


def _is_link_only(p_tag) -> bool:
    """True if a <p> is just a call-to-action link like "View the Course in
    English" / "Bekijk de cursus in het Nederlands" with no other text --
    these are navigation, not content, and every VU program page (stub or
    full) carries one to its other-language sibling, so they can't be
    treated as description text."""
    text = p_tag.get_text(" ", strip=True)
    links = p_tag.find_all("a", recursive=False)
    link_text = " ".join(a.get_text(" ", strip=True) for a in links)
    return bool(links) and link_text == text


def _is_bare_header(p_tag) -> bool:
    """True if a <p> is just a bold lead-in like "<strong>Kosten:</strong>"
    with no other text -- these precede a fact list and add nothing to a
    standalone description once that list has been parsed out separately."""
    text = p_tag.get_text(" ", strip=True)
    strong_children = p_tag.find_all(["strong", "b"], recursive=False)
    strong_text = " ".join(s.get_text(" ", strip=True) for s in strong_children)
    return bool(strong_children) and strong_text == text


def _real_content_text_len(soup: BeautifulSoup) -> int:
    """Total length of the page's substantive rich-text content, excluding
    the site-wide cookie-consent boilerplate (data-widget="cookie-wizard",
    which duplicates onto every page) and language-switch CTA paragraphs/
    bullets (see _is_link_only) and fact-list labels."""
    total = 0
    for rich in soup.select(".vuw-rich-text"):
        if rich.find_parent(attrs={"data-widget": "cookie-wizard"}):
            continue
        for p in rich.find_all("p", recursive=False):
            if _is_bare_header(p) or _is_link_only(p):
                continue
            total += len(p.get_text(" ", strip=True))
        for li in rich.find_all("li"):
            text = li.get_text(" ", strip=True)
            if not FACT_LINE_RE.match(text):
                total += len(text)
    return total


STUB_CONTENT_THRESHOLD = 80


def _is_stub_page(soup: BeautifulSoup) -> bool:
    """True if this page's own real content is too thin to trust as this
    course's description -- just the title, a facts sidebar, and a "View in
    English/Dutch" link to the language that does.

    NOTE (2026-09-08, first pass): an earlier version of this check looked
    for a `[data-widget="notification"]` banner, on the assumption it only
    appears on stub pages. Verified live against
    vu.nl/nl/.../course-compliance-regulatory-impact-organisational-reponse
    (a real stub) and vu.nl/nl/.../compliance-integriteit-management/overzicht
    (a real full page): that notification element is actually a shared,
    CSS-hidden UI partial present on EVERY course page regardless of
    content, so it can't tell stub from full.

    NOTE (2026-09-08, second pass): that version then gated on
    `[data-widget="contact"]` being absent, on the assumption a real content
    page always names a contact person. Also wrong: verified live against
    vu.nl/nl/.../course-compliance-enterprise-risk-compliance-management,
    whose Dutch page HAS a contact widget (apparently a shared block
    rendered for the whole course family) but whose own rich-text content is
    nothing but the "View the course in English" CTA -- no real description
    at all, while its English alternate has a full page (33 rich-text items
    vs. this page's 0 real ones). So contact-widget presence doesn't imply
    real content either. The one signal that has held up across every case
    checked so far is real body-text length once cookie-consent boilerplate
    and the language-switch CTA are excluded -- so that's now the whole
    check.
    """
    return _real_content_text_len(soup) < STUB_CONTENT_THRESHOLD


def _first_fact(facts: dict[str, str], *labels: str) -> str:
    """Look up a fact bullet by any of several label spellings (Dutch and English
    course pages use different labels for the same field, e.g. "Kosten"/"Costs").

    Matches by substring (case-insensitive), not exact equality: the newer VU
    page template uses compound labels like "Investering tweejarige master" /
    "Investering premaster" instead of a plain "Kosten"/"Investering" bullet
    (confirmed live 2026-09-10 on the Deeltijd Master Bedrijfskunde page), so
    an exact match would silently find nothing on those pages. Facts are
    stored in the order they appear on the page (dict insertion order), so
    when several bullets match the same search label (e.g. both a full-track
    and a pre-master cost line) this returns whichever came first -- on every
    real page checked so far that's the standard/full-track figure, since the
    pre-master or discount line is always listed second.
    """
    for label in labels:
        needle = label.lower()
        for key, value in facts.items():
            if needle in key.lower():
                return value
    return ""


def _parse_main_body(soup: BeautifulSoup, program: ScrapedProgram) -> None:
    title_bar = soup.select_one('[data-widget="title-bar"]')
    if title_bar:
        program.intro_text = title_bar.get_text(strip=True)

    h1 = soup.select_one(".vuw-sub-navigation-bar h1") or soup.select_one("h1")
    if h1:
        program.heading = h1.get_text(strip=True)

    for rich in soup.select(".vuw-rich-text"):
        if rich.find_parent(attrs={"data-widget": "cookie-wizard"}):
            continue  # site-wide cookie-consent boilerplate, not program content
        for p in rich.find_all("p", recursive=False):
            text = p.get_text(" ", strip=True)
            if text and len(text) > 3 and not _is_bare_header(p) and not _is_link_only(p):
                program.description_paragraphs.append(text)

        for li in rich.find_all("li"):
            text = li.get_text(" ", strip=True)
            m = FACT_LINE_RE.match(text)
            if m:
                label, value = m.group(1).strip(), m.group(2).strip()
                program.facts[label] = value

    contact_widget = soup.select_one('[data-widget="contact"]')
    if contact_widget:
        mail = contact_widget.select_one('a[href^="mailto:"]')
        if mail:
            program.contact_email = mail.get("data-email-address") or mail.get_text(strip=True)

        profile = contact_widget.select_one(".vuw-profile-block")
        if profile:
            items = [li.get_text(strip=True) for li in profile.select("ul > li")]
            if items:
                program.contact_name = items[0] if len(items) > 0 else None
                program.contact_role = items[1] if len(items) > 1 else None
            tel = profile.select_one('a[href^="tel:"]')
            if tel:
                program.contact_phone = tel.get_text(strip=True)

        addr_block = contact_widget.select_one(".fa-map")
        if addr_block:
            addr_container = addr_block.find_parent(class_="vuw-icon-block")
            if addr_container:
                lines = [d.get_text(strip=True) for d in addr_container.select("div > div > div")]
                program.address_lines = [l for l in lines if l]


def scrape_program(session: requests.Session, base_url: str, slow_down: float = 0.5) -> ScrapedProgram:
    """Fetch the overview page plus its curriculum/admission/dates-and-costs
    sub-pages (see ``SUBPAGES_BY_LANG`` for the current slug sets -- VU runs
    two page templates side by side).

    Some VU courses only have real content in one language: the locale vu.nl
    serves at ``base_url`` can render a near-empty "stub" -- title and a facts
    sidebar only, no contact person and next to no body text (see
    ``_is_stub_page``). When that happens, follow the page's own hreflang
    alternate link to whichever language does have real content and scrape
    that instead, recording which one was used in
    ``content_language``/``content_source_url`` so xmlgen.py can tag the
    generated text with the right xml:lang.
    """
    program = ScrapedProgram(url=base_url)

    soup = _get(session, base_url)
    if soup is None:
        program.errors.append(f"failed to fetch overview page {base_url}")
        return program

    _parse_head(soup, program)
    content_url = base_url
    program.content_language = "nl"

    if _is_stub_page(soup):
        fallback_url = program.english_url or program.dutch_url
        fallback_lang = "en" if fallback_url and fallback_url == program.english_url else "nl"
        if fallback_url and fallback_url.rstrip("/") != base_url.rstrip("/"):
            fallback_soup = _get(session, fallback_url)
            if fallback_soup is not None and not _is_stub_page(fallback_soup):
                program.errors.append(
                    f"'{base_url}' has no real content in its own locale; used the "
                    f"{fallback_lang} version at '{fallback_url}' instead"
                )
                soup = fallback_soup
                content_url = fallback_url
                program.content_language = fallback_lang
                _parse_head(soup, program)
            else:
                program.errors.append(
                    f"'{base_url}' looks like a stub page and its alternate-language "
                    f"version also had no usable content -- please check manually"
                )
        else:
            program.errors.append(
                f"'{base_url}' looks like a stub page with no alternate-language link "
                f"to fall back to -- please check manually"
            )

    program.content_source_url = content_url
    _parse_main_body(soup, program)

    base_url_stripped = content_url.rstrip("/")
    subpages = SUBPAGES_BY_LANG.get(program.content_language, SUBPAGES_BY_LANG["nl"])
    for sub, category in subpages:
        time.sleep(slow_down)
        sub_url = f"{base_url_stripped}/{sub}"
        sub_soup = _get(session, sub_url)
        if sub_soup is None:
            continue
        program.sub_pages_fetched.append(sub)

        # Merge additional facts/paragraphs found on the sub-page.
        for rich in sub_soup.select(".vuw-rich-text"):
            if rich.find_parent(attrs={"data-widget": "cookie-wizard"}):
                continue  # site-wide cookie-consent boilerplate, not program content
            for p in rich.find_all("p", recursive=False):
                text = p.get_text(" ", strip=True)
                if text and len(text) > 3 and not _is_bare_header(p) and not _is_link_only(p):
                    if category == "admission":
                        program.admission_text = (
                            (program.admission_text + "\n\n" + text) if program.admission_text else text
                        )
                    elif category == "curriculum":
                        program.curriculum_text = (
                            (program.curriculum_text + "\n\n" + text) if program.curriculum_text else text
                        )
                    elif category == "dates_costs":
                        # NOTE: the "Dates and costs" page often carries itemized/
                        # tiered pricing as prose (e.g. per-year amounts) rather than
                        # a single clean "Kosten: €X" bullet -- confirmed live
                        # 2026-09-10 on vu.nl/en/.../part-time-phd-programme-in-finance,
                        # whose costs page reads "Year 1 & 2: €12,000/year", "Year 3:
                        # €6000 / €4000...", etc. That can't be safely collapsed into
                        # one <cost><amount> without guessing which figure is "the"
                        # price, so this raw text is kept and surfaced separately
                        # (see xmlgen.py's "tuition fee" subjectText) rather than fed
                        # into the single-amount cost parser.
                        program.dates_costs_text = (
                            (program.dates_costs_text + "\n\n" + text) if program.dates_costs_text else text
                        )
            for li in rich.find_all("li"):
                text = li.get_text(" ", strip=True)
                m = FACT_LINE_RE.match(text)
                if m:
                    label, value = m.group(1).strip(), m.group(2).strip()
                    program.facts.setdefault(label, value)

        # A /toelating page often repeats/extends contact info; only fill gaps.
        if program.contact_email is None:
            contact_widget = sub_soup.select_one('[data-widget="contact"]')
            if contact_widget:
                mail = contact_widget.select_one('a[href^="mailto:"]')
                if mail:
                    program.contact_email = mail.get("data-email-address") or mail.get_text(strip=True)

    return program

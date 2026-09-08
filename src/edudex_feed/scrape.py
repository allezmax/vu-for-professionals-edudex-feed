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

Each program is spread across up to three URLs:
  - the overview page itself                      (always exists)
  - <slug>/inhoud    (curriculum / content)         (usually exists)
  - <slug>/toelating (admission / cost / practical) (usually exists)

Some programs use a different sub-page naming; missing sub-pages are skipped
without failing the whole run.
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

SUBPAGES = ["inhoud", "toelating"]

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


def _is_bare_header(p_tag) -> bool:
    """True if a <p> is just a bold lead-in like "<strong>Kosten:</strong>"
    with no other text -- these precede a fact list and add nothing to a
    standalone description once that list has been parsed out separately."""
    text = p_tag.get_text(" ", strip=True)
    strong_children = p_tag.find_all(["strong", "b"], recursive=False)
    strong_text = " ".join(s.get_text(" ", strip=True) for s in strong_children)
    return bool(strong_children) and strong_text == text


def _parse_main_body(soup: BeautifulSoup, program: ScrapedProgram) -> None:
    title_bar = soup.select_one('[data-widget="title-bar"]')
    if title_bar:
        program.intro_text = title_bar.get_text(strip=True)

    h1 = soup.select_one(".vuw-sub-navigation-bar h1") or soup.select_one("h1")
    if h1:
        program.heading = h1.get_text(strip=True)

    for rich in soup.select(".vuw-rich-text"):
        for p in rich.find_all("p", recursive=False):
            text = p.get_text(" ", strip=True)
            if text and len(text) > 3 and not _is_bare_header(p):
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
    """Fetch the overview page plus /inhoud and /toelating sub-pages."""
    program = ScrapedProgram(url=base_url)

    soup = _get(session, base_url)
    if soup is None:
        program.errors.append(f"failed to fetch overview page {base_url}")
        return program

    _parse_head(soup, program)
    _parse_main_body(soup, program)

    base_url_stripped = base_url.rstrip("/")
    for sub in SUBPAGES:
        time.sleep(slow_down)
        sub_url = f"{base_url_stripped}/{sub}"
        sub_soup = _get(session, sub_url)
        if sub_soup is None:
            continue
        program.sub_pages_fetched.append(sub)

        # Merge additional facts/paragraphs found on the sub-page.
        for rich in sub_soup.select(".vuw-rich-text"):
            for p in rich.find_all("p", recursive=False):
                text = p.get_text(" ", strip=True)
                if text and len(text) > 3:
                    if sub == "toelating":
                        program.admission_text = (
                            (program.admission_text + "\n\n" + text) if program.admission_text else text
                        )
                    elif sub == "inhoud":
                        program.curriculum_text = (
                            (program.curriculum_text + "\n\n" + text) if program.curriculum_text else text
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

"""
Discover every program URL under a vu.nl course-listing filter.

The listing page at
  https://vu.nl/nl/onderwijs/professionals/cursussen-opleidingen?filters=...
renders its results client-side: the page's JS calls
``POST https://vu.nl/api/search`` and injects the cards into the DOM. A plain
HTTP GET (requests/urllib) never sees that data, so this module drives a real
(headless) browser with Playwright, and reads the JSON straight out of the
network response -- which is both more robust and much richer (stable ids,
canonical URLs, category tags) than scraping the rendered card HTML.

If vu.nl ever changes the listing page to be server-rendered, this is the
only file that would need to change (scrape.py already works against plain
HTML for the actual program pages).
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from playwright.sync_api import sync_playwright

log = logging.getLogger(__name__)

DEFAULT_LISTING_URL = (
    "https://vu.nl/nl/onderwijs/professionals/cursussen-opleidingen"
    "?filters=Aanbieder:School+of+Business+and+Economics+for+Professionals"
)


@dataclass
class DiscoveredProgram:
    vu_id: str
    title: str
    url: str  # absolute URL
    language: str


def discover_programs(listing_url: str = DEFAULT_LISTING_URL, timeout_ms: int = 45000) -> list[DiscoveredProgram]:
    """Load the listing page in a headless browser and capture the /api/search
    response(s) it triggers, returning every program found.

    Handles the case where the site paginates search results by watching
    every matching response and de-duplicating by id.
    """
    results: dict[str, DiscoveredProgram] = {}
    expected_count: int | None = None

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()

        def on_response(response):
            nonlocal expected_count
            if "/api/search" not in response.url or response.request.method != "POST":
                return
            try:
                data = response.json()
            except Exception:
                return
            if expected_count is None and "@odata.count" in data:
                expected_count = data["@odata.count"]
            for item in data.get("value", []):
                vu_id = item.get("Id", "")
                url = item.get("Url", "")
                if not url:
                    continue
                full_url = url if url.startswith("http") else f"https://vu.nl{url}"
                results[vu_id or full_url] = DiscoveredProgram(
                    vu_id=vu_id,
                    title=item.get("Title", ""),
                    url=full_url,
                    language=item.get("Language", "nl"),
                )

        page.on("response", on_response)
        page.goto(listing_url, wait_until="networkidle", timeout=timeout_ms)
        page.wait_for_timeout(1500)

        # If the site paginates ("toon meer" / infinite scroll) and we haven't
        # seen everything yet, scroll and click a "load more" button a bounded
        # number of times.
        attempts = 0
        while expected_count is not None and len(results) < expected_count and attempts < 20:
            attempts += 1
            clicked = False
            for text in ["Toon meer", "Meer tonen", "Laad meer", "Load more"]:
                locator = page.get_by_text(text, exact=False)
                if locator.count() > 0:
                    try:
                        locator.first.click(timeout=2000)
                        clicked = True
                        break
                    except Exception:
                        pass
            if not clicked:
                page.mouse.wheel(0, 3000)
            page.wait_for_timeout(1200)

        browser.close()

    if expected_count is not None and len(results) < expected_count:
        log.warning(
            "discovered %d programs but the site reported %d -- pagination may be incomplete",
            len(results),
            expected_count,
        )

    return sorted(results.values(), key=lambda d: d.title)


def main():
    logging.basicConfig(level=logging.INFO)
    programs = discover_programs()
    print(json.dumps([p.__dict__ for p in programs], indent=2, ensure_ascii=False))
    print(f"\n{len(programs)} programs discovered", flush=True)


if __name__ == "__main__":
    main()

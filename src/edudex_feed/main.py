"""
Orchestrates the whole pipeline:

  1. discover every program URL under the configured vu.nl listing filter
  2. scrape each program's overview + inhoud + toelating pages
  3. apply config/overrides.yaml (manual corrections/confirmations per program)
  4. generate feed/institute.xml, feed/programs/<id>.xml, feed/directory.xml
  5. validate everything against the live EDU-DEX XSDs
  6. write a human-readable run report (data/report.md) listing every field
     that was guessed rather than confidently scraped, so someone can review
     new/changed programs before trusting the feed blindly.

Usage:
    python -m edudex_feed.main --config config/institute.yaml \\
                                --overrides config/overrides.yaml \\
                                --feed-dir feed \\
                                --report-dir data
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import requests
import yaml

from . import discover, scrape, xmlgen, validate

log = logging.getLogger(__name__)


def load_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def run(config_path: Path, overrides_path: Path, feed_dir: Path, report_dir: Path, base_url: str) -> int:
    config = load_yaml(config_path)
    required = ["org_unit_id", "editor_email", "generator_name", "institute_name"]
    missing = [k for k in required if not config.get(k)]
    if missing:
        log.error(
            "config/institute.yaml is missing required key(s): %s -- copy "
            "config/institute.example.yaml and fill them in.",
            ", ".join(missing),
        )
        return 2

    overrides_all = load_yaml(overrides_path)

    log.info("discovering programs...")
    discovered = discover.discover_programs()
    log.info("found %d programs", len(discovered))

    feed_dir.mkdir(parents=True, exist_ok=True)
    programs_dir = feed_dir / "programs"
    programs_dir.mkdir(parents=True, exist_ok=True)
    report_dir.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    program_urls: list[str] = []
    program_ids: list[str] = []
    all_reviews: dict[str, dict] = {}
    scraped_cache = []

    for i, d in enumerate(discovered):
        log.info("[%d/%d] scraping %s", i + 1, len(discovered), d.url)
        scraped = scrape.scrape_program(session, d.url)
        scraped.vu_id = scraped.vu_id or d.vu_id
        scraped_cache.append(scraped.__dict__)

        program_id = xmlgen.slugify_program_id(scraped, i)
        override = (overrides_all.get("programs") or {}).get(program_id, {})

        element, review = xmlgen.build_program_xml(
            scraped,
            org_unit_id=config["org_unit_id"],
            editor_email=config["editor_email"],
            generator_name=config["generator_name"],
            expires_in_days=int(config.get("expires_in_days", 21)),
            override=override,
        )
        out_path = programs_dir / f"{program_id}.xml"
        xmlgen.write_pretty(element, str(out_path))

        program_url = f"{base_url.rstrip('/')}/programs/{program_id}.xml"
        program_urls.append(program_url)
        program_ids.append(program_id)

        if review:
            all_reviews[program_id] = {"title": scraped.title, "url": scraped.url, "fields": review}
            if scraped.errors:
                all_reviews[program_id]["errors"] = scraped.errors

    institute_element = xmlgen.build_institute_xml(config)
    institute_path = feed_dir / "institute.xml"
    xmlgen.write_pretty(institute_element, str(institute_path))
    institute_url = f"{base_url.rstrip('/')}/institute.xml"

    directory_element = xmlgen.build_directory_xml(config, institute_url, list(zip(program_ids, program_urls)))
    xmlgen.write_pretty(directory_element, str(feed_dir / "directory.xml"))

    (report_dir / "scraped.json").write_text(
        json.dumps(scraped_cache, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    write_report(report_dir / "report.md", discovered, all_reviews)

    log.info("validating feed against live EDU-DEX XSDs...")
    problems = validate.validate_feed_dir(feed_dir)
    if problems:
        log.error("XSD validation failed for %d file(s) -- see data/report.md", len(problems))
        with open(report_dir / "report.md", "a", encoding="utf-8") as f:
            f.write("\n\n## XSD validation errors\n\n")
            for path, errs in problems.items():
                f.write(f"### {path}\n\n")
                for e in errs:
                    f.write(f"- {e}\n")
        return 1

    log.info("done: %d programs, %d needing manual review", len(discovered), len(all_reviews))
    return 0


def write_report(path: Path, discovered: list, reviews: dict) -> None:
    lines = ["# EDU-DEX feed build report", ""]
    lines.append(f"- Programs discovered: {len(discovered)}")
    lines.append(f"- Programs with at least one guessed/defaulted field: {len(reviews)}")
    lines.append("")
    if reviews:
        lines.append("## Fields that need a human to confirm")
        lines.append("")
        lines.append(
            "Add a correct value under that program's id in `config/overrides.yaml` "
            "to silence a line here permanently."
        )
        lines.append("")
        for program_id, info in reviews.items():
            lines.append(f"### {info.get('title') or program_id}")
            lines.append(f"`{program_id}` -- {info['url']}")
            lines.append("")
            for field, note in info["fields"].items():
                lines.append(f"- **{field}**: {note}")
            for err in info.get("errors", []):
                lines.append(f"- ERROR: {err}")
            lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def cli():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("config/institute.yaml"))
    parser.add_argument("--overrides", type=Path, default=Path("config/overrides.yaml"))
    parser.add_argument("--feed-dir", type=Path, default=Path("feed"))
    parser.add_argument("--report-dir", type=Path, default=Path("data"))
    parser.add_argument(
        "--base-url",
        default="https://REPLACE-ME.github.io/REPLACE-ME-REPO",
        help="Public base URL the feed will be hosted at (GitHub Pages URL). "
             "Program/institute resource URLs in directory.xml are built from this.",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    return run(args.config, args.overrides, args.feed_dir, args.report_dir, args.base_url)


if __name__ == "__main__":
    sys.exit(cli())

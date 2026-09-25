"""
Orchestrates the whole pipeline:

  1. discover every program URL under the configured vu.nl listing filter
  2. scrape each program's overview + inhoud + toelating pages
  3. apply config/overrides.yaml (manual corrections/confirmations per program)
  4. generate feed/institute.xml, feed/programs/<id>.xml, feed/directory.xml
  5. validate everything against the live EDU-DEX XSDs
  6. compare this run's data against the previous run's published snapshot
     (feed/snapshot.json) and update feed/changelog.md with anything worth a
     look -- see changelog.py for exactly what counts
  7. write a human-readable run report (data/report.md) listing every field
     that was guessed rather than confidently scraped, every field that's
     manually overridden (and therefore traceable back to config/overrides.yaml
     rather than the live crawl), and every program's sign-off status from
     config/approvals.yaml, so someone can review new/changed programs before
     trusting the feed blindly.

Usage:
    python -m edudex_feed.main --config config/institute.yaml \\
                                --overrides config/overrides.yaml \\
                                --approvals config/approvals.yaml \\
                                --feed-dir feed \\
                                --report-dir data
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import sys
from pathlib import Path

import requests
import yaml

from . import discover, scrape, xmlgen, validate, changelog

log = logging.getLogger(__name__)


def load_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def run(
    config_path: Path,
    overrides_path: Path,
    feed_dir: Path,
    report_dir: Path,
    base_url: str,
    approvals_path: Path | None = None,
) -> int:
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
    approvals_all = load_yaml(approvals_path) if approvals_path else {}

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
    all_overrides: dict[str, dict] = {}  # program_id -> {"title", "url", "keys": [...]}
    scraped_cache = []
    changelog_entries: list[dict] = []

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

        override_keys = sorted(override.keys()) if override else []
        if override_keys:
            all_overrides[program_id] = {"title": scraped.title, "url": scraped.url, "keys": override_keys}

        changelog_entries.append({
            "program_id": program_id,
            "title": scraped.title or program_id,
            "url": scraped.url,
            "signals": changelog.derive_source_signals(scraped, override),
            "xml_fields": changelog.extract_xml_fields(element),
            "override_keys": override_keys,
        })

    institute_element = xmlgen.build_institute_xml(config)
    institute_path = feed_dir / "institute.xml"
    xmlgen.write_pretty(institute_element, str(institute_path))
    institute_url = f"{base_url.rstrip('/')}/institute.xml"

    directory_element = xmlgen.build_directory_xml(config, institute_url, list(zip(program_ids, program_urls)))
    xmlgen.write_pretty(directory_element, str(feed_dir / "directory.xml"))

    (report_dir / "scraped.json").write_text(
        json.dumps(scraped_cache, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    run_date = dt.date.today().isoformat()
    log.info("comparing against previous snapshot for change detection...")
    try:
        findings, approval_statuses = changelog.run_change_detection(
            base_url=base_url,
            feed_dir=feed_dir,
            run_date=run_date,
            entries=changelog_entries,
            approvals_all=approvals_all,
        )
    except Exception as exc:  # change detection must never break the actual feed build
        log.warning("change detection failed (%s) -- feed build continues without it", exc)
        findings, approval_statuses = [], {}

    write_report(
        report_dir / "report.md", discovered, all_reviews, all_overrides, approval_statuses, findings
    )
    # Also publish the same report next to the feed itself (Max, 2026-09-15),
    # so it's visible at a stable, no-login-required URL
    # (.../feed/report.md on GitHub Pages) instead of only as a GitHub
    # Actions run artifact, which needs repo access to open.
    write_report(
        feed_dir / "report.md", discovered, all_reviews, all_overrides, approval_statuses, findings
    )

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

    log.info(
        "done: %d programs, %d needing manual review, %d change(s) flagged",
        len(discovered), len(all_reviews), len(findings),
    )
    return 0


def write_report(
    path: Path,
    discovered: list,
    reviews: dict,
    overrides: dict | None = None,
    approval_statuses: dict | None = None,
    findings: list | None = None,
) -> None:
    overrides = overrides or {}
    approval_statuses = approval_statuses or {}
    findings = findings or []

    lines = ["# EDU-DEX feed build report", ""]
    lines.append(f"- Programs discovered: {len(discovered)}")
    lines.append(f"- Programs with at least one guessed/defaulted field: {len(reviews)}")
    lines.append(f"- Programs with a manual override in effect: {len(overrides)}")
    approved = sum(1 for s in approval_statuses.values() if s.get("status") == "current")
    stale = sum(1 for s in approval_statuses.values() if s.get("status") == "stale")
    lines.append(f"- Programs approved by a program manager: {approved} (plus {stale} needing re-review)")
    if findings:
        lines.append(f"- New items in changelog.md this run: {len(findings)}")
    lines.append("")

    if findings:
        lines.append("## Changes detected this run -- see changelog.md")
        lines.append("")
        lines.append(
            "Full detail (and the running history) is in `changelog.md` next to this report. "
            "Summary of what's new:"
        )
        lines.append("")
        for f in findings:
            lines.append(f"- **{f['title']}** (`{f['program_id']}`) -- [{f['kind']}] {f['detail']}")
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

    if overrides:
        lines.append("## Manual overrides in effect")
        lines.append("")
        lines.append(
            "These fields do NOT come from the live crawl -- their value in the feed was typed "
            "by hand into `config/overrides.yaml` and always wins over whatever (if anything) is "
            "scraped. Some of these (price, contact) aren't published on the page at all, so "
            "nothing else would ever notice them going stale -- that's exactly what "
            "`changelog.md`'s \"override may be stale\" notes are for."
        )
        lines.append("")
        for program_id, info in overrides.items():
            keys = ", ".join(f"`{k}`" for k in info["keys"])
            lines.append(f"- **{info.get('title') or program_id}** (`{program_id}`): {keys}")
        lines.append("")

    if approval_statuses:
        lines.append("## Review / sign-off status")
        lines.append("")
        lines.append(
            "Recorded in `config/approvals.yaml`. An approval only certifies the exact field "
            "values it was given for -- if any of them change afterward (live scrape or an "
            "override edit), the program automatically drops back to \"needs re-review\" here."
        )
        lines.append("")
        need_review = {pid: s for pid, s in approval_statuses.items() if s["status"] != "current"}
        current = {pid: s for pid, s in approval_statuses.items() if s["status"] == "current"}
        if need_review:
            lines.append("**Needs re-review** (values changed since the last sign-off):")
            for pid, s in need_review.items():
                lines.append(f"- `{pid}` -- last approved by {s['approvedBy']} on {s['approvedAt']}")
            lines.append("")
        if current:
            lines.append("**Currently approved:**")
            for pid, s in current.items():
                lines.append(f"- `{pid}` -- approved by {s['approvedBy']} on {s['approvedAt']}")
            lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")


def cli():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("config/institute.yaml"))
    parser.add_argument("--overrides", type=Path, default=Path("config/overrides.yaml"))
    parser.add_argument("--approvals", type=Path, default=Path("config/approvals.yaml"))
    parser.add_argument("--feed-dir", type=Path, default=Path("feed"))
    parser.add_argument("--report-dir", type=Path, default=Path("data"))
    parser.add_argument(
        "--base-url",
        default="https://REPLACE-ME.github.io/REPLACE-ME-REPO",
        help="Public base URL the feed will be hosted at (GitHub Pages URL). "
             "Program/institute resource URLs in directory.xml are built from this, and "
             "the previous run's snapshot.json/changelog.md are fetched back from here too.",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    return run(args.config, args.overrides, args.feed_dir, args.report_dir, args.base_url, args.approvals)


if __name__ == "__main__":
    sys.exit(cli())

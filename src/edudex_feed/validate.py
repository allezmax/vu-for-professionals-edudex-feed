"""
Validate generated feed files against the REAL, currently-published EDU-DEX
XSDs -- fetched fresh on every run rather than bundled, because EDU-DEX can
and does change the standard over time (see the changelog tab at
https://edudex.nl/edudox/), and a stale bundled copy would give false
confidence.

This is the safety net for every hand-typed enumeration/structure choice
made in mapping.py and xmlgen.py: if EDU-DEX's schema disagrees with this
code, this step fails loudly with the real error instead of silently
shipping a feed EDU-DEX's nightly import will reject.
"""
from __future__ import annotations

import logging
from pathlib import Path

import requests
import xmlschema

log = logging.getLogger(__name__)

XSD_URLS = {
    "program": "http://studieData.nl/schema/edudex/program.xsd",
    "directory": "http://studieData.nl/schema/edudex/directory.xsd",
    "institute": "http://studieData.nl/schema/edudex/institute.xsd",
}


def _fetch_xsd(kind: str, cache_dir: Path) -> Path:
    cache_dir.mkdir(parents=True, exist_ok=True)
    dest = cache_dir / f"{kind}.xsd"
    url = XSD_URLS[kind]
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    dest.write_bytes(resp.content)
    return dest


def validate_file(xml_path: Path, kind: str, cache_dir: Path) -> list[str]:
    """Returns a list of human-readable error strings; empty means valid."""
    try:
        xsd_path = _fetch_xsd(kind, cache_dir)
    except requests.RequestException as exc:
        return [f"could not download {kind}.xsd from {XSD_URLS[kind]}: {exc}"]

    try:
        schema = xmlschema.XMLSchema(str(xsd_path))
    except Exception as exc:  # xmlschema raises its own exception hierarchy
        return [f"{kind}.xsd itself failed to parse ({XSD_URLS[kind]}): {exc}"]

    errors = []
    for error in schema.iter_errors(str(xml_path)):
        errors.append(str(error).splitlines()[0])
    return errors


def validate_feed_dir(feed_dir: Path) -> dict[str, list[str]]:
    """Validate directory.xml, institute.xml and every programs/*.xml file.

    Returns {relative_path: [errors]} for files with at least one error.
    """
    cache_dir = feed_dir / ".xsd-cache"
    problems: dict[str, list[str]] = {}

    directory_xml = feed_dir / "directory.xml"
    if directory_xml.exists():
        errs = validate_file(directory_xml, "directory", cache_dir)
        if errs:
            problems["directory.xml"] = errs

    institute_xml = feed_dir / "institute.xml"
    if institute_xml.exists():
        errs = validate_file(institute_xml, "institute", cache_dir)
        if errs:
            problems["institute.xml"] = errs

    programs_dir = feed_dir / "programs"
    if programs_dir.exists():
        for program_xml in sorted(programs_dir.glob("*.xml")):
            errs = validate_file(program_xml, "program", cache_dir)
            if errs:
                problems[f"programs/{program_xml.name}"] = errs

    return problems


def main():
    import sys
    logging.basicConfig(level=logging.INFO)
    feed_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("feed")
    problems = validate_feed_dir(feed_dir)
    if not problems:
        print(f"All files in {feed_dir} validate against the live EDU-DEX XSDs.")
        return 0
    print(f"VALIDATION FAILED for {len(problems)} file(s):\n")
    for path, errs in problems.items():
        print(f"  {path}:")
        for e in errs[:5]:
            print(f"    - {e}")
        if len(errs) > 5:
            print(f"    ... and {len(errs) - 5} more")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

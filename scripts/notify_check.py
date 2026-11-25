#!/usr/bin/env python3
"""
Reads data/notify.json (written by edudex_feed.main.run(), see
write_notify_signal() in src/edudex_feed/main.py) and prints lines in
GITHUB_OUTPUT format, so .github/workflows/build-feed.yml can decide whether
to post a Teams notification -- without embedding multi-line Python logic
directly inside the workflow YAML (fragile to indent/escape correctly).

Added 2026-11-24 per Max: the team needs an active alert -- not just a
report.md file sitting on GitHub Pages that nobody's told to go read --
whenever the feed build breaks, or the pipeline's own change-detection
flags something worth a look (a program the scraper can no longer read
correctly, an overridden value that no longer matches what's live on
vu.nl, a program appearing/disappearing from the catalog). A plain price
tick with the same wording/basis is deliberately NOT flagged here -- see
changelog.py's own docstring and tests (test_no_cost_basis_finding_for_a_
plain_number_change) -- so this does not fire on every routine, correctly-
handled auto-update. Only on the things a human actually needs to look at.

Usage: python3 scripts/notify_check.py [path/to/notify.json]
"""
import json
import sys
import uuid
from pathlib import Path

path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/notify.json")

if path.exists():
    data = json.loads(path.read_text(encoding="utf-8"))
    should_notify = bool(data.get("should_notify"))
    build_failed = bool(data.get("build_failed"))
    summary = "\n".join(data.get("summary") or []) or "(no details recorded)"
else:
    # notify.json itself missing means the build crashed before even
    # reaching feed generation -- treat that as worth flagging too, rather
    # than staying silent just because the usual signal never got written.
    should_notify = True
    build_failed = True
    summary = (
        "data/notify.json was never written this run -- the build likely crashed "
        "before reaching feed generation. Check this run's Actions log for the real error."
    )

# A random delimiter avoids any (astronomically unlikely, since summary text
# includes freeform scraped page titles) collision with GITHUB_OUTPUT's
# multiline-value marker syntax.
delimiter = f"EOF_{uuid.uuid4().hex}"
print(f"should_notify={'true' if should_notify else 'false'}")
print(f"build_failed={'true' if build_failed else 'false'}")
print(f"summary<<{delimiter}")
print(summary)
print(delimiter)

"""SimplifyJobs-format repos, e.g. github.com/SimplifyJobs/New-Grad-Positions.

These repos keep every listing in .github/scripts/listings.json (the README
is generated from it), with direct links to the employer's application page.
Forks of Simplify's format (e.g. vanshb03/New-Grad-*) work the same way.
"""

import re
from datetime import datetime, timezone

from ..geo import countries_for_all, is_remote
from ..http import get_json, github_raw
from ..models import Job
from ..workauth import CITIZEN_ONLY, NO_SPONSORSHIP, SPONSORS

SPONSORSHIP = {
    "U.S. Citizenship is Required": CITIZEN_ONLY,
    "Offers Sponsorship": SPONSORS,
    "Does Not Offer Sponsorship": NO_SPONSORSHIP,
}


def fetch(cfg: dict) -> list[Job]:
    url = github_raw(cfg["repo"], cfg.get("branch", "dev"), cfg.get("path", ".github/scripts/listings.json"))
    categories = {c.lower() for c in cfg.get("categories", [])}
    # Optional {category: regex}: within that category, keep only matching titles.
    title_patterns = {c.lower(): re.compile(p, re.I) for c, p in cfg.get("category_title_patterns", {}).items()}

    jobs = []
    for raw in get_json(url):
        if not raw.get("active") or not raw.get("is_visible", True):
            continue  # closed or hidden listings
        category = (raw.get("category") or "").lower()
        if categories and category not in categories:
            continue
        if category in title_patterns and not title_patterns[category].search(raw.get("title") or ""):
            continue

        locations = raw.get("locations") or []
        countries = countries_for_all(locations)
        jobs.append(
            Job(
                id=f"simplify:{raw['id']}",
                source=cfg.get("name", cfg["repo"]),
                company=raw.get("company_name") or "",
                title=raw.get("title") or "",
                location=_location(locations),
                country=",".join(sorted(countries)) or None,
                remote=any(is_remote(loc) for loc in locations),
                posted_on=_date(raw.get("date_posted")),
                url=raw.get("url") or "",
                work_auth=SPONSORSHIP.get(raw.get("sponsorship")),
            )
        )
    return jobs


def _location(locations: list[str]) -> str:
    if len(locations) <= 3:
        return "; ".join(locations)
    return "; ".join(locations[:3]) + f" (+{len(locations) - 3} more)"


def _date(ts) -> str | None:
    return datetime.fromtimestamp(ts, timezone.utc).date().isoformat() if ts else None

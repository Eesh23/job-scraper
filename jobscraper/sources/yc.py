"""Y Combinator startup jobs (www.ycombinator.com/jobs).

Each /jobs/role/<role>[/<city>] page embeds ~40-50 postings as JSON in a
`data-page` attribute. The plain role page only shows a sample, so we also
read each city page and merge by job id. City pages mix in every kind of job
(sales, ops, ...), so we keep only the YC `role` codes in config.

Entry level = YC's own "minimum experience" field, which employers set to
"Any (new grads ok)" when they'll take new grads. Note that applying needs a
free YC "Work at a Startup" account.
"""

import html
import json
import re
import time
from datetime import date, timedelta

from ..geo import is_remote, resolve
from ..http import get_text
from ..models import Job
from ..workauth import NO_SPONSORSHIP, SPONSORS

# YC's per-job "visa" field. "US citizen/visa only" means you must already be
# allowed to work in the US - they won't sponsor, but it's not citizens-only.
VISA = {
    "Will sponsor": SPONSORS,
    "US citizenship/visa not required": SPONSORS,
    "US citizen/visa only": NO_SPONSORSHIP,
}

BASE = "https://www.ycombinator.com"
DATA_PAGE = re.compile(r'data-page="([^"]+)"')
AGE = re.compile(r"(\d+)\s+(minute|hour|day|week|month|year)")
UNIT_DAYS = {"minute": 0, "hour": 0, "day": 1, "week": 7, "month": 30, "year": 365}


def fetch(cfg: dict) -> list[Job]:
    roles = set(cfg.get("roles", ["eng", "product"]))
    experience = set(cfg.get("experience", ["Any (new grads ok)"]))

    postings = {}
    for page in cfg.get("pages", ["software-engineer", "product-manager"]):
        for city in ["", *cfg.get("cities", [])]:
            path = f"/jobs/role/{page}" + (f"/{city}" if city else "")
            for p in _postings(path):
                postings[p["id"]] = p
            time.sleep(0.5)  # be polite

    jobs = []
    for p in postings.values():
        if p.get("role") not in roles or p.get("minExperience") not in experience:
            continue
        locations = [loc.strip() for loc in (p.get("location") or "").split(" / ")]
        jobs.append(Job(
            id=f"yc:{p['id']}",
            source=cfg.get("name", "YC Jobs"),
            company=f"{p.get('companyName', '')} (YC {p.get('companyBatchName', '')})".replace(" (YC )", ""),
            title=p.get("title") or "",
            location="; ".join(locations),
            country=resolve(locations),
            remote=any(is_remote(loc) for loc in locations),
            posted_on=_posted(p.get("createdAt") or ""),
            url=BASE + p["url"],
            work_auth=VISA.get(p.get("visa")),
        ))
    return jobs


def _postings(path: str) -> list[dict]:
    match = DATA_PAGE.search(get_text(BASE + path))
    return json.loads(html.unescape(match.group(1)))["props"].get("jobPostings", []) if match else []


def _posted(age: str) -> str | None:
    """'about 2 months' / '20 days' / '1 day' -> approximate date."""
    match = AGE.search(age)
    if not match:
        return date.today().isoformat() if "minute" in age or "hour" in age else None
    days = int(match.group(1)) * UNIT_DAYS[match.group(2)]
    return (date.today() - timedelta(days=days)).isoformat()

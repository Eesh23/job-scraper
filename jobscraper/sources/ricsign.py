"""ricsign-format repos, e.g. github.com/ricsign/Ricsign-New-Grads-Jobs-2027.

The boards/*.md files are generated from data/v1/jobs.json, which has every
job with a `track` (new-grad-swe, internship, quant, ai-research) and a
direct apply link.
"""

from ..geo import is_remote, resolve
from ..http import get_json, github_raw
from ..models import Job
from ..workauth import CITIZEN_ONLY, CLEARANCE, NO_SPONSORSHIP, SPONSORS

SPONSORSHIP = {
    "citizenship-required": CITIZEN_ONLY,
    "security-clearance": CLEARANCE,
    "sponsors": SPONSORS,
    "no-sponsorship": NO_SPONSORSHIP,
}


def fetch(cfg: dict) -> list[Job]:
    data = get_json(github_raw(cfg["repo"], cfg.get("branch", "main"), cfg.get("path", "data/v1/jobs.json")))
    tracks = set(cfg.get("tracks", ["new-grad-swe"]))

    jobs = []
    for raw in data.get("jobs", []):
        if not raw.get("active", True) or raw.get("closed_at") or raw.get("track") not in tracks:
            continue
        locations = raw.get("locations") or []
        jobs.append(Job(
            id=f"ricsign:{raw['uid']}",
            source=cfg.get("name", cfg["repo"]),
            company=raw.get("company_name") or "",
            title=raw.get("title") or "",
            location="; ".join(locations),
            country=resolve(locations, cfg.get("default_country")),
            remote=any(is_remote(loc) for loc in locations),
            posted_on=raw.get("posted_at") or raw.get("first_seen"),
            url=raw.get("apply_url") or "",
            work_auth=SPONSORSHIP.get(raw.get("sponsorship")),
        ))
    return jobs

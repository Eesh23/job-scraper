"""ApplyGuy lists, e.g. github.com/ApplyGuy/2027-New-Grad-Jobs.

The README is generated from data/new-grad-jobs.json. Each job has an
applyguy.ai page (`url`) and the employer's own posting (`listingUrl`); we
use the employer link.
"""

from ..geo import is_remote, resolve
from ..http import get_json, github_raw
from ..models import Job


def fetch(cfg: dict) -> list[Job]:
    data = get_json(github_raw(cfg["repo"], cfg.get("branch", "main"), cfg.get("path", "data/new-grad-jobs.json")))

    jobs = []
    for raw in data.get("jobs", []):
        location = raw.get("location") or ""
        jobs.append(Job(
            id=f"applyguy:{raw['id']}",
            source=cfg.get("name", cfg["repo"]),
            company=raw.get("company") or "",
            title=raw.get("title") or "",
            location=location,
            country=resolve([location], cfg.get("default_country")),
            remote=is_remote(location),
            posted_on=raw.get("posted"),
            url=raw.get("listingUrl") or raw.get("url") or "",
        ))
    return jobs

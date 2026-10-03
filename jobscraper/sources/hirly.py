"""Hirly job lists (github.com/Hirly-Me/*).

Each GitHub repo's README is rendered daily from a public JSON feed at
https://hirly.me/api/job-lists/<slug>.json, so we read that feed directly
instead of parsing the markdown table. The feed holds the newest 250 jobs.
"""

from urllib.parse import urlsplit, urlunsplit

from ..http import get_json
from ..models import Job

FEED_URL = "https://hirly.me/api/job-lists/{slug}.json"


def fetch(cfg: dict) -> list[Job]:
    data = get_json(FEED_URL.format(slug=cfg["slug"]))

    jobs = []
    for raw in data.get("jobs", []):
        link = _strip_query(raw["url"])
        jobs.append(
            Job(
                # Job pages end in a UUID, e.g. /jobs/software-engineer-at-acme-<uuid>
                id="hirly:" + link.rstrip("/").rsplit("/", 1)[-1],
                source=cfg.get("name", cfg["slug"]),
                company=raw.get("company") or "",
                title=raw.get("title") or "",
                location=_location(raw),
                country=raw.get("country"),
                remote=raw.get("work_mode") == "remote",
                posted_on=raw.get("posted_on"),
                url=link,
            )
        )
    return jobs


def _location(raw: dict) -> str:
    loc = raw.get("location") or raw.get("country") or ""
    extra = raw.get("more_locations") or 0
    return f"{loc} (+{extra} more)" if extra else loc


def _strip_query(url: str) -> str:
    """Drop utm_* tracking params."""
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))

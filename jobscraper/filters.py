import re
from datetime import date, timedelta

from .models import Job

# Location text that marks a country-less remote job as outside North America.
NON_NA_REGIONS = (
    "europe", "emea", "apac", "asia", "latam", "latin america", "africa",
    "india", "uk", "united kingdom", "australia", "germany", "poland",
)


def matches(job: Job, cfg: dict) -> bool:
    allowed = {c.upper() for c in cfg.get("countries", [])}
    title = job.title.lower()

    if job.countries:
        if allowed and not (job.countries & allowed):
            return False
    elif not (job.remote and cfg.get("include_remote_without_country", True)):
        return False
    elif any(region in job.location.lower() for region in NON_NA_REGIONS):
        return False

    max_age = cfg.get("max_age_days", 0)
    if max_age and job.posted_on and job.posted_on < (date.today() - timedelta(days=max_age)).isoformat():
        return False

    # A title that explicitly says it's entry level ("Junior to Senior Engineer")
    # is kept even if it also contains an excluded word.
    explicitly_entry = any(_has_word(title, kw) for kw in cfg.get("entry_title_keywords", []))
    if not explicitly_entry and any(_has_word(title, kw) for kw in cfg.get("exclude_title_keywords", [])):
        return False

    # Must look like a tech / product role. Substring match on purpose, so
    # "develop" covers developer/development and "scien" covers scientist.
    roles = cfg.get("role_keywords", [])
    if roles and not any(_has_stem(title, kw) for kw in roles):
        return False

    include = cfg.get("include_title_keywords", [])
    if include and not any(_has_word(title, kw) for kw in include):
        return False

    return True


def _has_word(title: str, keyword: str) -> bool:
    """Whole-word, case-insensitive: "intern" matches "Intern" but not "Internal"."""
    return re.search(rf"(?<!\w){re.escape(keyword.lower())}(?!\w)", title) is not None


def _has_stem(title: str, stem: str) -> bool:
    """Word-start, case-insensitive: "develop" matches "Developer"; "ai" needs to be its own word."""
    end = r"(?!\w)" if len(stem) <= 3 else ""
    return re.search(rf"(?<!\w){re.escape(stem.lower())}{end}", title) is not None

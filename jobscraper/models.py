from dataclasses import dataclass


@dataclass
class Job:
    """One job posting, normalized across sources."""

    id: str  # stable unique id: "<source type>:<source's own id>"
    source: str  # human-readable source name from config
    company: str
    title: str
    location: str
    country: str | None  # comma-separated ISO codes, e.g. "US" or "CA,US"; "OTHER" = outside NA
    remote: bool
    posted_on: str | None  # YYYY-MM-DD
    url: str
    # What the posting says about work authorization (see workauth.py):
    # "citizen_only", "clearance", "sponsors", "no_sponsorship", or None.
    work_auth: str | None = None

    @property
    def countries(self) -> set[str]:
        return set(self.country.split(",")) if self.country else set()

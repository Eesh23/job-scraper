"""Job sources. Each source type is a function: (source_config) -> list[Job]."""

from . import applyguy, hackernews, hirly, jobradar, ricsign, simplify, speedyapply, yc

SOURCE_TYPES = {
    "hirly": hirly.fetch,
    "simplify": simplify.fetch,
    "speedyapply": speedyapply.fetch,
    "ricsign": ricsign.fetch,
    "applyguy": applyguy.fetch,
    "jobradar": jobradar.fetch,
    "yc": yc.fetch,
    "hackernews": hackernews.fetch,
}


def fetch_source(source_cfg: dict):
    kind = source_cfg.get("type")
    if kind not in SOURCE_TYPES:
        raise ValueError(f"Unknown source type {kind!r}; known: {sorted(SOURCE_TYPES)}")
    return SOURCE_TYPES[kind](source_cfg)

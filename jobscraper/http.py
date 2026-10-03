import json
import ssl
import urllib.request

import certifi

# python.org builds of Python ship without system CA certs; use certifi's.
_SSL = ssl.create_default_context(cafile=certifi.where())
_HEADERS = {"User-Agent": "job-scraper (personal use)"}


def get_text(url: str) -> str:
    req = urllib.request.Request(url, headers=_HEADERS)
    with urllib.request.urlopen(req, timeout=60, context=_SSL) as resp:
        return resp.read().decode("utf-8")


def get_json(url: str):
    return json.loads(get_text(url))


def github_raw(repo: str, branch: str, path: str) -> str:
    return f"https://raw.githubusercontent.com/{repo}/{branch}/{path}"

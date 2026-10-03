"""Check Claude's tailored resume against the master resume and undo anything
it can't back up. Runs on every tailored resume before it's written.

- Bullets must name a real source bullet from the same entry.
- A rewritten bullet may not introduce numbers that aren't in its source
  bullet, or technology-looking terms / proper nouns that appear nowhere in
  the master resume. Violations are reverted to the original wording.
- Skills must exist in the master. Every experience entry stays on the page.
"""

import re

from . import master as master_mod

NUMBER = re.compile(r"\d[\d,.]*\s*[%x+kKmMbB]?")
# Terms that look like a technology or proper noun: has a digit or symbol
# (C++, Node.js, S3), internal capitals (PyTorch), all caps (AWS), or a
# capitalized word that isn't the first word of the bullet.
TERM = re.compile(r"\w[\w.+#-]*")  # whole tokens, so "2M" stays one term
STOPWORDS_CAPITALIZED = {"I", "A", "An", "The", "And", "Of", "For", "To", "In", "On", "With"}
# A supporting role in the original must not become ownership in the rewrite.
SUPPORTING = re.compile(r"\b(helped|assisted|contributed|supported|participated|collaborated)\b", re.I)
OWNING = re.compile(r"\b(led|owned|spearheaded|managed|headed|directed|drove|architected)\b", re.I)


def check(master: dict, tailored: dict, limits: dict) -> tuple[dict, list[str]]:
    """Return (cleaned tailored dict, list of human-readable fixes made)."""
    fixes = []
    bullets = master_mod.bullet_index(master)
    master_text = master_mod.all_text(master).lower()
    entries_by_id = {e["id"]: (section, e) for section in master_mod.SECTIONS_WITH_BULLETS
                     for e in master.get(section) or []}

    cleaned_entries, seen = [], set()
    for entry in tailored.get("entries", []):
        if entry["id"] not in entries_by_id:
            fixes.append(f"Dropped unknown entry {entry['id']!r}")
            continue
        if entry["id"] in seen:
            continue
        seen.add(entry["id"])
        section, master_entry = entries_by_id[entry["id"]]
        cap = limits["max_bullets_per_role"] if section == "experience" else limits["max_bullets_per_project"]

        kept, used_sources = [], set()
        for b in entry.get("bullets", []):
            source = bullets.get(b.get("source", ""))
            if not source or not b["source"].startswith(entry["id"] + "."):
                fixes.append(f"Dropped a bullet in {entry['id']} that didn't point to one of its own original bullets")
                continue
            if b["source"] in used_sources:
                continue
            used_sources.add(b["source"])
            problem = _unsupported(b["text"], source["text"], master_text)
            if problem:
                fixes.append(f"Reverted {b['source']} to your original wording (rewrite added {problem})")
                b = {"source": b["source"], "text": source["text"]}
            kept.append(b)
        if len(kept) > cap:
            kept = kept[:cap]
        if not kept:  # never show an entry with no bullets
            kept = [{"source": x["id"], "text": x["text"]} for x in master_entry["bullets"][:cap]]
        cleaned_entries.append({"id": entry["id"], "bullets": kept})

    # Jobs are always shown in the master's (date) order; say so if Claude reordered them.
    exp_order = [e["id"] for e in master.get("experience") or []]
    suggested = [e["id"] for e in cleaned_entries if e["id"] in exp_order]
    if suggested != [i for i in exp_order if i in suggested]:
        first = entries_by_id[suggested[0]][1]
        fixes.append(f"Kept experience in date order (Claude suggested putting {first.get('title')} at "
                     f"{first.get('company')} first; move it in master_resume.yaml if you prefer)")

    # Every job stays on the resume, even if Claude left it out.
    for e in master.get("experience") or []:
        if e["id"] not in seen:
            fixes.append(f"Restored {e.get('title')} at {e.get('company')} (experience is never hidden)")
            cleaned_entries.append({"id": e["id"], "bullets": [
                {"source": x["id"], "text": x["text"]} for x in e["bullets"][:limits["max_bullets_per_role"]]]})

    for section, cap in (("projects", limits["max_projects"]), ("leadership", limits["max_leadership"])):
        ids = [e["id"] for e in cleaned_entries if entries_by_id[e["id"]][0] == section]
        for extra in ids[cap:]:
            cleaned_entries = [e for e in cleaned_entries if e["id"] != extra]

    master_skills = {s.lower() for group in master.get("skills") or [] for s in group.get("items", [])}
    cleaned_skills = []
    for group in tailored.get("skills", []):
        items = []
        for item in group.get("items", []):
            if item.lower() in master_skills or _mentions(master_text, item):
                items.append(item)
            else:
                fixes.append(f"Removed skill {item!r} (not in your master resume)")
        if items:
            cleaned_skills.append({"category": group.get("category", ""), "items": items})

    headline = tailored.get("headline") or ""
    if headline:
        problem = _unsupported(headline, master.get("headline") or "", master_text, numbers_from_master=True)
        if problem:
            fixes.append(f"Dropped the summary line (it added {problem})")
            headline = ""

    return {**tailored, "headline": headline, "entries": cleaned_entries,
            "skills": cleaned_skills or master.get("skills") or []}, fixes


def _unsupported(new: str, source: str, master_text: str, numbers_from_master=False) -> str | None:
    """Describe the first unsupported number or term in `new`, or None."""
    allowed_numbers = master_text if numbers_from_master else source.lower()
    for n in NUMBER.findall(new):
        digits = re.sub(r"[^\d.]", "", n).strip(".")
        if digits and digits not in re.sub(r"[^\d.\s]", " ", allowed_numbers):
            return f"the number {n.strip()!r}"

    if SUPPORTING.search(source) and OWNING.search(new) and not OWNING.search(source):
        return f"ownership language ({OWNING.search(new).group(0)!r}) to a bullet where you helped"

    words = TERM.findall(new)
    for i, word in enumerate(words):
        word = word.rstrip(".,;:/-")
        if not word or word in STOPWORDS_CAPITALIZED or word.replace(",", "").replace(".", "").isdigit():
            continue
        techy = (any(c.isdigit() for c in word) or any(c in word for c in "+#./")
                 or (len(word) > 1 and word.isupper())
                 or any(c.isupper() for c in word[1:])
                 or (i > 0 and word[0].isupper()))
        if techy and not _mentions(master_text, word):
            return f"{word!r}"
    return None


def _mentions(text: str, term: str) -> bool:
    """Whole-word, case-insensitive: "Go" isn't found inside "logistic"."""
    return re.search(rf"(?<![\w]){re.escape(term.lower())}(?![\w])", text) is not None

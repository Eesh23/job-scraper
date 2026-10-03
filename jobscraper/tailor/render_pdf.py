"""Write a resume as a PDF and make it fit on one page.

Same layout as render.py's .docx. fit_one_page() lays the resume out, counts
the pages, and if it runs over: first tightens spacing and font size (down to
a readable minimum), then drops the least relevant bullets until it fits.
Within each entry Claude lists bullets most-relevant first, so trimming
always removes from the end.
"""

import io
from dataclasses import dataclass
from xml.sax.saxutils import escape

from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import HRFlowable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .render import SECTION_TITLES, _chosen

FONT, BOLD, ITALIC = "Helvetica", "Helvetica-Bold", "Helvetica-Oblique"


@dataclass(frozen=True)
class Layout:
    font_size: float = 10.5
    margin: float = 0.5        # inches, all sides
    leading: float = 1.22      # line height as a multiple of font size
    section_gap: float = 6     # points before each section heading


# Tried in order until the resume fits; then bullets get trimmed.
LAYOUTS = [
    Layout(),
    Layout(font_size=10.25, leading=1.18, section_gap=5),
    Layout(font_size=10, margin=0.45, leading=1.16, section_gap=4),
    Layout(font_size=9.75, margin=0.4, leading=1.14, section_gap=3),
    Layout(font_size=9.5, margin=0.4, leading=1.12, section_gap=3),
]


def fit_one_page(master: dict, tailored: dict) -> tuple[dict, Layout, list[str], int]:
    """Return (tailored with any bullets trimmed, layout that fits, notes, pages)."""
    for layout in LAYOUTS:
        if page_count(master, tailored, layout) <= 1:
            note = [] if layout == LAYOUTS[0] else [
                f"Tightened spacing and used {layout.font_size}pt text to fit one page"]
            return tailored, layout, note, 1

    layout = LAYOUTS[-1]
    tailored = _copy(tailored)
    notes = [f"Used {layout.font_size}pt text, the smallest allowed"]
    while page_count(master, tailored, layout) > 1:
        dropped = _drop_one_bullet(master, tailored)
        if not dropped:
            break  # nothing left that's safe to drop
        notes.append(f"Dropped to fit one page: \"{dropped}\"")
    return tailored, layout, notes, page_count(master, tailored, layout)


def write(master: dict, path, tailored: dict | None = None, layout: Layout = Layout()):
    with open(path, "wb") as f:
        f.write(_build(master, tailored, layout)[0])


def page_count(master, tailored, layout) -> int:
    return _build(master, tailored, layout)[1]


# ---------------------------------------------------------------- trimming

def _drop_one_bullet(master, tailored) -> str | None:
    """Remove the last (least relevant) bullet from the lowest-priority place:
    leadership, then projects, then the experience entry with the most bullets.
    Entries keep at least one bullet; experience keeps at least two."""
    section_of = {e["id"]: s for s in ("experience", "projects", "leadership") for e in master.get(s) or []}
    entries = tailored["entries"]

    def candidates(section, keep):
        found = [e for e in entries if section_of[e["id"]] == section and len(e["bullets"]) > keep]
        return sorted(found, key=lambda e: len(e["bullets"]), reverse=True)

    for section, keep in (("leadership", 1), ("projects", 1), ("experience", 2)):
        pool = candidates(section, keep)
        if pool:
            return pool[0]["bullets"].pop()["text"]

    # Every entry is at its minimum: drop the last whole project/leadership entry.
    for section in ("leadership", "projects"):
        removable = [e for e in entries if section_of[e["id"]] == section]
        if removable:
            entries.remove(removable[-1])
            return f"(whole entry) {removable[-1]['bullets'][0]['text']}"
    return None


def _copy(tailored):
    return {**tailored, "entries": [{**e, "bullets": list(e["bullets"])} for e in tailored["entries"]]}


# ---------------------------------------------------------------- layout

def _build(master, tailored, layout: Layout) -> tuple[bytes, int]:
    buf = io.BytesIO()
    m = layout.margin * inch
    doc = SimpleDocTemplate(buf, pagesize=LETTER, leftMargin=m, rightMargin=m, topMargin=m, bottomMargin=m,
                            title=f"{master['name']} - Resume", author=master["name"])
    width = LETTER[0] - 2 * m
    st = _styles(layout)
    story = []

    story.append(Paragraph(_x(master["name"]), st["name"]))
    contact = master.get("contact") or {}
    line = " | ".join(x for x in [contact.get("email"), contact.get("phone"), contact.get("location"),
                                  *(contact.get("links") or [])] if x)
    story.append(Paragraph(_x(line), st["contact"]))

    headline = tailored.get("headline") if tailored else master.get("headline")
    if headline:
        story.append(Paragraph(_x(headline), st["headline"]))

    if master.get("education"):
        _heading(story, SECTION_TITLES["education"], st, layout)
        for e in master["education"]:
            _entry_header(story, e.get("school", ""), e.get("location", ""), e.get("degree", ""),
                          e.get("dates", ""), st, width)
            for d in e.get("details") or []:
                story.append(Paragraph(_x(d), st["bullet"], bulletText="•"))

    chosen = _chosen(master, tailored)
    for section in ("experience", "projects", "leadership"):
        if not chosen[section]:
            continue
        _heading(story, SECTION_TITLES[section], st, layout)
        for entry, bullets in chosen[section]:
            if section == "experience":
                args = (entry.get("company", ""), entry.get("location", ""), entry.get("title", ""), entry.get("dates", ""))
            elif section == "projects":
                name = entry.get("name", "") + (f" | {entry['tech']}" if entry.get("tech") else "")
                args = (name, entry.get("dates", ""), entry.get("link", ""), "")
            else:
                args = (entry.get("org", ""), entry.get("location", ""), entry.get("title", ""), entry.get("dates", ""))
            _entry_header(story, *args, st, width)
            for text in bullets:
                story.append(Paragraph(_x(text), st["bullet"], bulletText="•"))

    skills = tailored.get("skills") if tailored else master.get("skills")
    other = master.get("other") or []
    if skills or other:
        _heading(story, "Skills" + (" & Other" if other else ""), st, layout)
        for group in skills or []:
            story.append(Paragraph(f"<b>{_x(group['category'])}:</b> {_x(', '.join(group['items']))}", st["body"]))
        for line in other:
            story.append(Paragraph(_x(line), st["body"]))

    doc.build(story)
    return buf.getvalue(), doc.page


def _styles(layout: Layout) -> dict:
    size, lead = layout.font_size, layout.font_size * layout.leading
    body = ParagraphStyle("body", fontName=FONT, fontSize=size, leading=lead)
    return {
        "body": body,
        "name": ParagraphStyle("name", parent=body, fontName=BOLD, fontSize=size + 7.5, leading=size + 10,
                               alignment=TA_CENTER),
        "contact": ParagraphStyle("contact", parent=body, fontSize=size - 1, leading=(size - 1) * 1.3,
                                  alignment=TA_CENTER, spaceAfter=2),
        "headline": ParagraphStyle("headline", parent=body, fontName=ITALIC, alignment=TA_CENTER, spaceAfter=2),
        "heading": ParagraphStyle("heading", parent=body, fontName=BOLD, fontSize=size + 0.5, leading=(size + 0.5) * 1.2),
        "left": ParagraphStyle("left", parent=body, fontName=BOLD),
        "right": ParagraphStyle("right", parent=body, alignment=TA_RIGHT),
        "left_i": ParagraphStyle("left_i", parent=body, fontName=ITALIC),
        "right_i": ParagraphStyle("right_i", parent=body, fontName=ITALIC, alignment=TA_RIGHT),
        "bullet": ParagraphStyle("bullet", parent=body, leftIndent=14, bulletIndent=4, bulletFontName=FONT),
    }


def _heading(story, title, st, layout):
    story.append(Spacer(1, layout.section_gap))
    story.append(Paragraph(_x(title.upper()), st["heading"]))
    story.append(HRFlowable(width="100%", thickness=0.6, color="black", spaceBefore=0.5, spaceAfter=2))


def _entry_header(story, left1, right1, left2, right2, st, width):
    rows = []
    for left, right, ls, rs in ((left1, right1, "left", "right"), (left2, right2, "left_i", "right_i")):
        left, right = str(left or ""), str(right or "")  # YAML reads "dates: 2025" as a number
        if left or right:
            rows.append([Paragraph(_x(left), st[ls]), Paragraph(_x(right), st[rs])])
    if not rows:
        return
    table = Table(rows, colWidths=[width * 0.68, width * 0.32])
    table.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                               ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
                               ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story.append(table)


def _x(text) -> str:
    return escape(str(text))

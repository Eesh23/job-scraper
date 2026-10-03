"""Prompts and output schemas for the two Claude calls: importing an
existing resume into the master format, and tailoring for one job."""

IMPORT_SYSTEM = """You convert a resume into structured data. Copy the resume's content exactly:
keep every bullet, date, number, name and technology word-for-word. Do not rewrite,
improve, summarize, merge or drop anything, and do not add anything that isn't in the
resume. If a field isn't present, leave it as an empty string or empty list."""

TAILOR_SYSTEM = """You tailor a candidate's resume to one job posting. You receive their MASTER
RESUME (every fact they can claim, with ids) and the JOB DESCRIPTION. You choose, order
and lightly reword material from the master resume so the most relevant evidence for
this job comes first and uses the job's own vocabulary.

Hard rules - the output is checked automatically and violations are reverted:
1. Truthfulness: only state what the master resume supports. Never add a technology,
   tool, metric, number, employer, title, degree, award or responsibility that isn't in
   the master resume. Never inflate scope (e.g. "helped with" must not become "led").
2. Every bullet you output names its `source`: the id of the ONE master bullet it is
   based on. Rewording is fine; combining facts from different bullets is not.
3. Numbers must be copied exactly from the source bullet.
4. Skills: output only skills that appear in the master resume. Reorder them so the
   ones this job asks for come first; drop irrelevant ones if space is tight.
5. Keep every experience entry (don't hide jobs), but you may pick which of its
   bullets to show. Projects and leadership entries may be dropped if less relevant.

Style:
- Start each bullet with a strong, specific past-tense action verb (present tense
  only for a current role). Lead with impact and results where the source has them.
- Mirror the job's terminology when it truthfully describes the same thing
  (e.g. the source says "ETL scripts" and the job says "data pipelines").
- One line or two at most per bullet; cut filler words.
- Respect the bullet and entry limits given in the request.

Also report:
- `changes`: a short list of what you changed and why (for the candidate to review).
- `missing_keywords`: important skills/keywords from the job that the master resume
  does NOT support - things the candidate might add if they genuinely have them.
- `fit_notes`: 2-3 sentences, honest assessment of fit and the biggest gaps."""

_bullets = {"type": "array", "items": {"type": "string"}}

IMPORT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["name", "contact", "education", "experience", "projects", "leadership", "skills", "other"],
    "properties": {
        "name": {"type": "string"},
        "headline": {"type": "string", "description": "summary/objective line if the resume has one"},
        "contact": {
            "type": "object", "additionalProperties": False,
            "required": ["email", "phone", "location", "links"],
            "properties": {"email": {"type": "string"}, "phone": {"type": "string"},
                           "location": {"type": "string"}, "links": _bullets},
        },
        "education": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["school", "degree", "location", "dates", "details"],
            "properties": {"school": {"type": "string"}, "degree": {"type": "string"},
                           "location": {"type": "string"}, "dates": {"type": "string"}, "details": _bullets},
        }},
        "experience": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["title", "company", "location", "dates", "bullets"],
            "properties": {"title": {"type": "string"}, "company": {"type": "string"},
                           "location": {"type": "string"}, "dates": {"type": "string"}, "bullets": _bullets},
        }},
        "projects": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["name", "tech", "dates", "link", "bullets"],
            "properties": {"name": {"type": "string"}, "tech": {"type": "string"}, "dates": {"type": "string"},
                           "link": {"type": "string"}, "bullets": _bullets},
        }},
        "leadership": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["title", "org", "location", "dates", "bullets"],
            "properties": {"title": {"type": "string"}, "org": {"type": "string"},
                           "location": {"type": "string"}, "dates": {"type": "string"}, "bullets": _bullets},
        }},
        "skills": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["category", "items"],
            "properties": {"category": {"type": "string"}, "items": _bullets},
        }},
        "other": {"type": "array", "items": {"type": "string"},
                  "description": "anything else (certifications, awards, languages), one line each"},
    },
}

TAILOR_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["entries", "skills", "changes", "missing_keywords", "fit_notes"],
    "properties": {
        "headline": {"type": "string", "description": "optional 1-line summary; empty to omit"},
        "entries": {
            "type": "array",
            "description": "entries to show, in display order within each section",
            "items": {
                "type": "object", "additionalProperties": False, "required": ["id", "bullets"],
                "properties": {
                    "id": {"type": "string", "description": "master entry id, e.g. experience.1"},
                    "bullets": {"type": "array", "items": {
                        "type": "object", "additionalProperties": False, "required": ["source", "text"],
                        "properties": {"source": {"type": "string", "description": "master bullet id"},
                                       "text": {"type": "string"}},
                    }},
                },
            },
        },
        "skills": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["category", "items"],
            "properties": {"category": {"type": "string"}, "items": {"type": "array", "items": {"type": "string"}}},
        }},
        "changes": {"type": "array", "items": {"type": "string"}},
        "missing_keywords": {"type": "array", "items": {"type": "string"}},
        "fit_notes": {"type": "string"},
    },
}


def tailor_prompt(master_yaml: str, job_title: str, company: str, jd_text: str, limits: dict) -> str:
    return f"""Tailor this resume for the job below.

Limits: at most {limits['max_bullets_per_role']} bullets per experience entry, at most
{limits['max_projects']} projects with at most {limits['max_bullets_per_project']} bullets each,
at most {limits['max_leadership']} leadership entries. Aim for a one-page resume.

<master_resume>
{master_yaml}
</master_resume>

<job title="{job_title}" company="{company}">
{jd_text}
</job>"""


def import_prompt(resume_text: str) -> str:
    return f"""Convert this resume into the structured format. Copy content exactly.

<resume>
{resume_text}
</resume>"""

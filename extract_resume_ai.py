import json
import sys
from pathlib import Path
from openai import OpenAI

from config import RESUME_EXTRACT_MODEL
from ai_costs import track_openai_response
from database import save_profile

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "candidate_title": {"type": ["string", "null"]},
        "years_experience": {"type": ["number", "null"]},
        "primary_roles": {"type": "array", "items": {"type": "string"}},
        "technical_skills": {"type": "array", "items": {"type": "string"}},
        "strongest_skills": {"type": "array", "items": {"type": "string"}},
        "domains": {"type": "array", "items": {"type": "string"}},
        "cloud_infrastructure": {"type": "array", "items": {"type": "string"}},
        "programming_languages": {"type": "array", "items": {"type": "string"}},
        "tools": {"type": "array", "items": {"type": "string"}},
        "projects": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "name": {"type": "string"},
                    "summary": {"type": "string"},
                    "technologies": {"type": "array", "items": {"type": "string"}}
                },
                "required": ["name", "summary", "technologies"]
            }
        },
        "work_experience": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "company": {"type": "string"},
                    "title": {"type": "string"},
                    "start": {"type": ["string", "null"]},
                    "end": {"type": ["string", "null"]},
                    "summary": {"type": "string"},
                    "highlights": {"type": "array", "items": {"type": "string"}}
                },
                "required": ["company", "title", "start", "end", "summary", "highlights"]
            }
        },
        "education": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "degree": {"type": ["string", "null"]},
                    "school": {"type": ["string", "null"]},
                    "field": {"type": ["string", "null"]}
                },
                "required": ["degree", "school", "field"]
            }
        },
        "summary": {"type": "string"},
        "short_summary": {"type": "string"}
    },
    "required": [
        "candidate_title",
        "years_experience",
        "primary_roles",
        "technical_skills",
        "strongest_skills",
        "domains",
        "cloud_infrastructure",
        "programming_languages",
        "tools",
        "projects",
        "work_experience",
        "education",
        "summary",
        "short_summary"
    ]
}

def extract_resume(
    client: OpenAI,
    resume_text: str,
    *,
    profile_name: str | None = None,
) -> dict:
    response = client.responses.create(
        model=RESUME_EXTRACT_MODEL,
        input=[
            {
                "role": "system",
                "content": (
                    "Extract a structured candidate profile from this resume. "
                    "Focus on evidence useful for matching the candidate against software engineering jobs. "
                    "Do not include personal contact information. "
                    "Use only facts from the resume. Do not invent missing details."
                ),
            },
            {"role": "user", "content": resume_text},
        ],
        text={
            "format": {
                "type": "json_schema",
                "name": "resume_profile",
                "schema": SCHEMA,
                "strict": True,
            }
        },
    )
    if getattr(response, "usage", None) is not None:
        track_openai_response(
            response, "resume_extract", profile_name=profile_name
        )
    return json.loads(response.output_text)


def main() -> None:
    if len(sys.argv) != 3:
        print("Usage: python extract_resume_ai.py <profile-name> <resume-file>")
        raise SystemExit(1)

    profile_name = sys.argv[1].strip()
    input_file = Path(sys.argv[2])
    if not input_file.exists():
        print(f"Resume file not found: {input_file}")
        raise SystemExit(1)

    resume_text = input_file.read_text(encoding="utf-8")
    profile = extract_resume(
        OpenAI(), resume_text, profile_name=profile_name
    )
    saved = save_profile(profile_name, resume_text, profile)
    print(f"Saved profile {saved['profile_name']} to SQLite")
    print(f"Profile hash: {saved['profile_hash']}")


if __name__ == "__main__":
    main()

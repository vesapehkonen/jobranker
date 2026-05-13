import json
import sys
from pathlib import Path
from openai import OpenAI

from config import OPENAI_MODEL

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

def main() -> None:
    if len(sys.argv) != 3:
        print("Usage: python extract_resume_ai.py <profile-name> <resume-file>")
        sys.exit(1)

    profile_name = sys.argv[1]
    input_file = Path(sys.argv[2])

    if not input_file.exists():
        print(f"Resume file not found: {input_file}")
        sys.exit(1)

    profile_dir = Path("data/profile") / profile_name
    profile_dir.mkdir(parents=True, exist_ok=True)

    output_file = profile_dir / "profile.json"
    resume_copy_file = profile_dir / "resume.txt"

    resume_text = input_file.read_text(encoding="utf-8")

    client = OpenAI()

    response = client.responses.create(
        model=OPENAI_MODEL,
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
            {
                "role": "user",
                "content": resume_text,
            },
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

    profile = json.loads(response.output_text)

    resume_copy_file.write_text(resume_text, encoding="utf-8")

    output_file.write_text(
        json.dumps(profile, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print(f"Saved {output_file}")
    print(f"Saved {resume_copy_file}")

if __name__ == "__main__":
    main()

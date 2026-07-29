import json
import sys
from pathlib import Path
from openai import OpenAI

from config import JOB_EXTRACT_MODEL
from ai_costs import track_openai_response
from database import initialize_database

DEFAULT_PROMPT_FILE = Path(__file__).with_name("job_extract_prompt.txt")

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "job_id": {"type": ["string", "null"]},
        "job_source": {"type": ["string", "null"]},
        "job_url": {"type": ["string", "null"]},
        "company": {"type": ["string", "null"]},
        "title": {"type": ["string", "null"]},
        "location": {"type": ["string", "null"]},
        "workplace_type": {
            "type": ["string", "null"],
            "enum": ["Remote", "Hybrid", "On-site", "Not specified", None],
        },
        "employment_type": {
            "type": ["string", "null"],
            "enum": [
                "Full-time",
                "Part-time",
                "Contract",
                "Temporary",
                "Internship",
                "Volunteer",
                "Not specified",
                None,
            ],
        },
        "salary_range": {"type": ["string", "null"]},
        "main_skill": {"type": ["string", "null"]},

        "technologies": {
            "type": "array",
            "maxItems": 20,
            "items": {"type": "string", "maxLength": 50},
        },
        "requirements": {
            "type": "array",
            "maxItems": 8,
            "items": {"type": "string", "maxLength": 180},
        },
        "preferred_requirements": {
            "type": "array",
            "maxItems": 8,
            "items": {"type": "string", "maxLength": 180},
        },
        "benefits": {
            "type": "array",
            "maxItems": 10,
            "items": {"type": "string", "maxLength": 120},
        },
        "summary": {"type": ["string", "null"], "maxLength": 800},
        "short_summary": {"type": ["string", "null"], "maxLength": 220},
        "education_requirement": {
            "type": ["string", "null"],
            "enum": [
                "high school",
                "bachelor",
                "master",
                "phd",
                "n/a",
                "not specified",
                None,
            ],
        },
        "domain": {
            "type": ["string", "null"],
            "maxLength": 160,
        },
        "responsibilities": {
            "type": "array",
            "maxItems": 8,
            "items": {"type": "string", "maxLength": 180},
        },
        "technical_areas": {
            "type": "array",
            "maxItems": 12,
            "items": {"type": "string", "maxLength": 80},
        },
        "must_have_constraints": {
            "type": "array",
            "maxItems": 6,
            "items": {"type": "string", "maxLength": 160},
        },
        "seniority_signals": {
            "type": "array",
            "maxItems": 6,
            "items": {"type": "string", "maxLength": 160},
        },
        "nice_to_have_signals": {
            "type": "array",
            "maxItems": 8,
            "items": {"type": "string", "maxLength": 160},
        },
    },
    "required": [
        "job_id",
        "job_source",
        "job_url",
        "company",
        "title",
        "location",
        "workplace_type",
        "employment_type",
        "salary_range",
        "main_skill",
        "technologies",
        "requirements",
        "preferred_requirements",
        "education_requirement",
        "benefits",
        "summary",
        "short_summary",
        "domain",
        "responsibilities",
        "technical_areas",
        "must_have_constraints",
        "seniority_signals",
        "nice_to_have_signals",
    ],
}


def build_output_path(input_file: Path, output_dir: Path) -> Path:
    name = input_file.name

    if name.endswith(".cleaned.json"):
        name = name.replace(".cleaned.json", ".structured.json")
    else:
        name = input_file.stem + ".structured.json"

    return output_dir / name


def read_cleaned_input(input_file: Path) -> dict:
    data = json.loads(input_file.read_text(encoding="utf-8"))

    return {
        "url": data.get("url") or data.get("source_url"),
        "page_title": data.get("page_title"),
        "header_text": data.get("header_text", ""),
        "description_text": data.get("description_text", ""),
    }


def read_prompt(prompt_file: Path) -> str:
    if not prompt_file.exists():
        raise FileNotFoundError(f"Prompt file not found: {prompt_file}")

    prompt = prompt_file.read_text(encoding="utf-8").strip()

    if not prompt:
        raise ValueError(f"Prompt file is empty: {prompt_file}")

    return prompt


def extract_job(
    client: OpenAI,
    cleaned: dict,
    system_prompt: str,
    *,
    job_uid: str | None = None,
) -> dict:
    response = client.responses.create(
        model=JOB_EXTRACT_MODEL,
        input=[
            {
                "role": "system",
                "content": system_prompt,
            },
            {
                "role": "user",
                "content": json.dumps(cleaned, ensure_ascii=False),
            },
        ],
        text={
            "format": {
                "type": "json_schema",
                "name": "job_posting",
                "schema": SCHEMA,
                "strict": True,
            }
        },
    )
    if getattr(response, "usage", None) is not None:
        track_openai_response(response, "job_extract", job_uid=job_uid)

    return json.loads(response.output_text)


def main() -> None:
    if len(sys.argv) not in (3, 4):
        print(
            "Usage: python extract_job_ai_refactored.py "
            "data/cleaned/example.cleaned.json data/structured [prompt_file]"
        )
        sys.exit(1)

    initialize_database()
    input_file = Path(sys.argv[1])
    output_dir = Path(sys.argv[2])
    prompt_file = Path(sys.argv[3]) if len(sys.argv) == 4 else DEFAULT_PROMPT_FILE

    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = build_output_path(input_file, output_dir)

    cleaned = read_cleaned_input(input_file)
    system_prompt = read_prompt(prompt_file)

    client = OpenAI()
    structured = extract_job(client, cleaned, system_prompt)

    output_file.write_text(
        json.dumps(structured, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print(f"Saved {output_file}")


if __name__ == "__main__":
    main()

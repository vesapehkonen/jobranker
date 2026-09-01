import json
import sys
from pathlib import Path
from typing import Any

START_MARKERS = [
    "About the job", "Job description", "Job Description", "About this job",
    "Description", "Role overview", "The role",
]
END_MARKERS = [
    "Set alert for similar jobs", "Similar jobs", "More jobs", "About the company",
    "Recommended jobs", "People also viewed", "Looking for talent?",
    "Explore other jobs", "Report job", "Hiring Lab", "Capturing job",
]
HEADER_LOOKBACK_LINES = 40


def clean_lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def find_first_marker(text: str, markers: list[str]) -> tuple[int, str | None]:
    matches = [(text.find(marker), marker) for marker in markers if text.find(marker) != -1]
    return min(matches, default=(-1, None), key=lambda match: match[0])


def extract_description(text: str) -> dict[str, Any]:
    start_index, start_marker = find_first_marker(text, START_MARKERS)
    if start_index == -1:
        start_index = 0
    before_description = text[:start_index]
    description_part = text[start_index:]
    header_lines = clean_lines(before_description)[-HEADER_LOOKBACK_LINES:]
    end_index, end_marker = find_first_marker(description_part, END_MARKERS)
    if end_index != -1:
        description_part = description_part[:end_index]
    return {
        "start_marker": start_marker,
        "end_marker": end_marker,
        "header_text": "\n".join(header_lines),
        "description_text": "\n".join(clean_lines(description_part)),
    }


def parse_job(raw: dict[str, Any]) -> dict[str, Any]:
    text = raw.get("text") or raw.get("raw_text") or ""
    if not text:
        raise ValueError("No text or raw_text found in input")
    return {
        "url": raw.get("url"),
        "page_title": raw.get("title"),
        **extract_description(text),
    }


def main() -> None:
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} input.json outdir")
        raise SystemExit(1)
    input_file = Path(sys.argv[1])
    output_dir = Path(sys.argv[2])
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / input_file.name.replace(".raw.json", ".cleaned.json")
    result = parse_job(json.loads(input_file.read_text(encoding="utf-8")))
    output_file.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Saved {output_file}")


if __name__ == "__main__":
    main()

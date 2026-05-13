import json
from pathlib import Path
import sys

if len(sys.argv) < 3:
    print("Usage: sys.argv[0] input.json outdir")
    exit(1)
    
INPUT_FILE = Path(sys.argv[1])
OUTPUT_DIR = Path(sys.argv[2])
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_FILE = OUTPUT_DIR / INPUT_FILE.name.replace(".raw.json", ".cleaned.json")

START_MARKERS = [
    "About the job",
    "Job description",
    "Job Description",
    "About this job",
    "Description",
    "Role overview",
    "The role",
]

END_MARKERS = [
    "Set alert for similar jobs",
    "Similar jobs",
    "More jobs",
    "About the company",
    "Recommended jobs",
    "People also viewed",
    "Looking for talent?",
]

HEADER_LOOKBACK_LINES = 40


def clean_lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def find_first_marker(text: str, markers: list[str]) -> tuple[int, str | None]:
    best_index = -1
    best_marker = None

    for marker in markers:
        index = text.find(marker)
        if index != -1 and (best_index == -1 or index < best_index):
            best_index = index
            best_marker = marker

    return best_index, best_marker


def extract_job(text: str) -> dict:
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


def main() -> None:
    data = json.loads(INPUT_FILE.read_text(encoding="utf-8"))

    text = data.get("text") or data.get("raw_text") or ""

    if not text:
        raise ValueError("No text or raw_text found in input file")

    result = {
        "url": data.get("url"),
        "page_title": data.get("title"),
        **extract_job(text),
    }

    OUTPUT_FILE.write_text(
        json.dumps(result, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print(f"Saved {OUTPUT_FILE}")


if __name__ == "__main__":
    main()

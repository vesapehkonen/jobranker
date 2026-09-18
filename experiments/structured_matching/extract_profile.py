from __future__ import annotations

import argparse
import json
import re
from datetime import date
from pathlib import Path
from typing import Any

from experiments.local_matching.data import connect_read_only

from .capabilities import extract_capabilities
from .qualifications import EDUCATION_RANK, extract_education
from .technologies import extract_technologies


DEFAULT_DATABASE = Path("data/jobranker.db")
DEFAULT_OUTPUT_DIRECTORY = Path("/tmp/jobranker-structured-matching/profiles")
EXTRACTOR_VERSION = 2

MONTHS = {
    name.casefold(): number
    for number, names in enumerate(
        (
            ("january", "jan"), ("february", "feb"), ("march", "mar"),
            ("april", "apr"), ("may",), ("june", "jun"),
            ("july", "jul"), ("august", "aug"),
            ("september", "sep", "sept"), ("october", "oct"),
            ("november", "nov"), ("december", "dec"),
        ),
        start=1,
    )
    for name in names
}
DATE_TOKEN = (
    r"(?:\d{1,2}/\d{4}|"
    r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
    r"Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|"
    r"Nov(?:ember)?|Dec(?:ember)?)\s+\d{4}|\d{4})"
)
DATE_RANGE = re.compile(
    rf"(?P<start>{DATE_TOKEN})\s*(?:-|–|—|to)\s*"
    rf"(?P<end>{DATE_TOKEN}|present|current|now)\b",
    re.I,
)
SECTION_HEADING = re.compile(r"^[A-Z][A-Z &/]+$")


def load_resume(database: Path | str, profile_name: str) -> str:
    with connect_read_only(database) as db:
        row = db.execute(
            "SELECT resume_text FROM profiles WHERE profile_name = ?",
            (profile_name,),
        ).fetchone()
    if row is None:
        raise ValueError(f"Profile not found: {profile_name}")
    resume = str(row["resume_text"] or "").strip()
    if not resume:
        raise ValueError(f"Profile has no resume text: {profile_name}")
    return resume


def _experience_text(resume: str) -> str:
    lines = resume.splitlines()
    start = next(
        (
            index + 1 for index, line in enumerate(lines)
            if line.strip().casefold() in {"experience", "work experience", "employment"}
        ),
        None,
    )
    if start is None:
        return resume
    end = next(
        (
            index for index in range(start, len(lines))
            if SECTION_HEADING.fullmatch(lines[index].strip())
        ),
        len(lines),
    )
    return "\n".join(lines[start:end])


def _month_index(value: str, as_of: tuple[int, int]) -> int:
    normalized = value.strip().casefold()
    if normalized in {"present", "current", "now"}:
        year, month = as_of
    elif "/" in normalized:
        month_text, year_text = normalized.split("/", 1)
        year, month = int(year_text), int(month_text)
    elif " " in normalized:
        month_text, year_text = normalized.rsplit(maxsplit=1)
        year, month = int(year_text), MONTHS[month_text.rstrip(".")]
    else:
        year, month = int(normalized), 1
    if not 1 <= month <= 12:
        raise ValueError(f"Invalid month in resume date: {value}")
    return year * 12 + month - 1


def _month_label(index: int) -> str:
    year, month_index = divmod(index, 12)
    return f"{year:04d}-{month_index + 1:02d}"


def extract_experience(resume: str, *, as_of: tuple[int, int]) -> dict[str, Any]:
    periods = []
    intervals = []
    for match in DATE_RANGE.finditer(_experience_text(resume)):
        start = _month_index(match.group("start"), as_of)
        end = _month_index(match.group("end"), as_of)
        if end < start:
            continue
        # Include both named boundary months by representing the interval as half-open.
        end_exclusive = end + 1
        intervals.append((start, end_exclusive))
        periods.append({
            "start": _month_label(start),
            "end": _month_label(end),
            "matched_text": match.group(0),
        })

    merged: list[list[int]] = []
    for start, end in sorted(intervals):
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    total_months = sum(end - start for start, end in merged)
    return {
        "total_months": total_months,
        "total_years": round(total_months / 12, 2),
        "periods": periods,
        "merged_periods": [
            {"start": _month_label(start), "end": _month_label(end - 1)}
            for start, end in merged
        ],
    }


def build_local_profile(
    profile_name: str,
    resume: str,
    *,
    as_of: tuple[int, int],
) -> dict[str, Any]:
    technologies = [item["name"] for item in extract_technologies(resume)]
    capabilities = [item["name"] for item in extract_capabilities(resume)]
    education = extract_education(resume)
    levels = education["levels_found"]
    highest_level = max(levels, key=EDUCATION_RANK.get) if levels else None
    education_mentions = [
        {
            "level": mention["level"],
            "matched_text": mention["matched_text"],
            "context": mention["context"],
        }
        for mention in education["mentions"]
    ]
    return {
        "schema_version": 2,
        "extractor_version": EXTRACTOR_VERSION,
        "profile_name": profile_name,
        "source": "profiles.resume_text",
        "as_of": f"{as_of[0]:04d}-{as_of[1]:02d}",
        "technologies": technologies,
        "capabilities": capabilities,
        "education": {
            "highest_level": highest_level,
            "levels_found": levels,
            "mentions": education_mentions,
        },
        "experience": extract_experience(resume, as_of=as_of),
    }


def _as_of(value: str) -> tuple[int, int]:
    match = re.fullmatch(r"(\d{4})-(\d{2})", value)
    if not match:
        raise argparse.ArgumentTypeError("expected YYYY-MM")
    result = int(match.group(1)), int(match.group(2))
    if not 1 <= result[1] <= 12:
        raise argparse.ArgumentTypeError("month must be between 01 and 12")
    return result


def main() -> None:
    today = date.today()
    parser = argparse.ArgumentParser(
        description="Create a deterministic local matching profile from resume text"
    )
    parser.add_argument("--profile", default="backend")
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--as-of", type=_as_of, default=(today.year, today.month))
    args = parser.parse_args()

    resume = load_resume(args.database, args.profile)
    profile = build_local_profile(args.profile, resume, as_of=args.as_of)
    output = args.output or DEFAULT_OUTPUT_DIRECTORY / f"{args.profile}.local.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(profile, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(profile, indent=2, ensure_ascii=False))
    print(f"Saved {output}")


if __name__ == "__main__":
    main()

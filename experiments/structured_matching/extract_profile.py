from __future__ import annotations

import argparse
import json
import re
from datetime import date
from pathlib import Path

from experiments.local_matching.data import connect_read_only

from job_matching.profile import EXTRACTOR_VERSION, build_local_profile, extract_experience


DEFAULT_DATABASE = Path("data/jobranker.db")
DEFAULT_OUTPUT_DIRECTORY = Path("/tmp/jobranker-structured-matching/profiles")


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

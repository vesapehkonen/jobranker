from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from job_matching.comparison import compare


DEFAULT_OUTPUT_DIRECTORY = Path("/tmp/jobranker-structured-matching/comparisons")


def _json_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return value


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare a deterministic job extraction with a local resume profile"
    )
    parser.add_argument("--job", type=Path, required=True)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    result = compare(_json_object(args.job), _json_object(args.profile))
    profile_name = args.profile.name.removesuffix(".local.json")
    job_name = args.job.name.removesuffix(".local.json")
    output = args.output or DEFAULT_OUTPUT_DIRECTORY / (
        f"{job_name}--{profile_name}.comparison.json"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
    output.write_text(serialized, encoding="utf-8")
    print(serialized, end="")
    print(f"Saved {output}")


if __name__ == "__main__":
    main()

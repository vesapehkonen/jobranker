from __future__ import annotations

import re


_BODY_START = re.compile(r"(?im)^full job description\s*$")
_BODY_END = re.compile(
    r"(?im)^(?:similar jobs(?:\s*\(\d+\))?|explore other jobs|report job|"
    r"hiring lab|insights from previous hires|accessibility statement)\s*$"
    r"|^©\s*\d{4}\s+Workday, Inc\.",
)


def target_job_text(text: str) -> str:
    """Remove recognizable portal chrome surrounding the target job posting."""
    start_match = _BODY_START.search(text)
    start = start_match.end() if start_match else 0
    end_match = _BODY_END.search(text, start)
    end = end_match.start() if end_match else len(text)
    return text[start:end].strip()

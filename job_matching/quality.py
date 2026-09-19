from __future__ import annotations

import re
from typing import Any

from .text import target_job_text


CONTENT_SIGNALS = re.compile(
    r"\b(?:responsibilities|qualifications|requirements|job duties|key duties|"
    r"minimum qualifications|preferred qualifications|skills required|"
    r"years? of experience|we are (?:seeking|looking for)|the ideal candidate|"
    r"you will|you(?:'|’)ll|role summary|position summary)\b",
    re.I,
)
NAVIGATION_SIGNALS = re.compile(
    r"\b(?:navigating to jobs|view open positions|current opportunities|"
    r"join (?:our )?talent community|contact sales|skip to main content|"
    r"enable accessibility|open the accessibility menu)\b",
    re.I,
)


def validate_job_text(text: str) -> dict[str, Any]:
    scoped = target_job_text(text)
    normalized = re.sub(r"\s+", " ", scoped).strip()
    character_count = len(normalized)
    content_signal_count = len(CONTENT_SIGNALS.findall(normalized))
    navigation_signal_count = len(NAVIGATION_SIGNALS.findall(normalized))
    reasons = []

    if character_count < 120:
        reasons.append("too_short")
    if navigation_signal_count and content_signal_count == 0 and character_count < 1000:
        reasons.append("navigation_only")
    # Length alone is not evidence that a capture is a job description.
    if content_signal_count == 0:
        reasons.append("missing_job_content")

    return {
        "status": "invalid" if reasons else "valid",
        "reasons": reasons,
        "character_count": character_count,
        "content_signal_count": content_signal_count,
        "navigation_signal_count": navigation_signal_count,
    }


def technology_confidence(job_count: int) -> str:
    if job_count == 0:
        return "unknown"
    if job_count <= 2:
        return "low"
    return "high"

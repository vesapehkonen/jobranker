from __future__ import annotations

import re
from typing import Any

from .text import target_job_text


EDUCATION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("high_school", re.compile(r"\b(?:high[ -]school diploma|GED)\b", re.I)),
    ("associate", re.compile(r"\bassociate(?:['’]s|s)? degree\b", re.I)),
    ("bachelor", re.compile(
        r"\b(?:bachelor(?:['’]s|s)?(?: degree)?|baccalaureate degree|BS degree|BA degree|B\.S\. degree|B\.A\. degree)\b",
        re.I,
    )),
    ("master", re.compile(
        r"\b(?:master(?:['’]s|s)(?: degree)?|master degree|MS degree|MA degree|M\.S\. degree|M\.A\. degree|MBA)\b",
        re.I,
    )),
    ("doctorate", re.compile(r"\b(?:doctoral degree|doctorate|Ph\.?D\.?)\b", re.I)),
    ("bachelor", re.compile(r"(?<![A-Za-z])(?:BS|B\.S\.)(?![A-Za-z])")),
    ("master", re.compile(r"(?<![A-Za-z])(?:MS|M\.S\.)(?![A-Za-z])")),
)

EDUCATION_RANK = {
    "high_school": 1, "associate": 2, "bachelor": 3, "master": 4, "doctorate": 5,
}

EQUIVALENT_EXPERIENCE = re.compile(
    r"\b(?:or|and/or)\s+(?:an?\s+)?(?:equivalent|equivalent combination of)[^.;\n]{0,80}experience\b"
    r"|\bequivalent\s+(?:education|degree)?\s*(?:and|/|or)?\s*experience\b"
    r"|\bin lieu of (?:a |the )?degree\b",
    re.I,
)

PREFERENCE_WORDS = re.compile(r"\b(?:preferred|desired|nice to have|a plus|ideally)\b", re.I)
REQUIREMENT_WORDS = re.compile(r"\b(?:required|requirement|minimum|must|at least)\b", re.I)
ABBREVIATED_DEGREE_CONTEXT = re.compile(
    r"\b(?:degree|education|equivalent|computer science|engineering|technical field|"
    r"related field|STEM field|mathematics|math|CS|EE|years?)\b",
    re.I,
)
OPTIONAL_DEGREE = re.compile(
    r"\b(?:or|and/or)\s+(?:an?\s+)?(?:equivalent|comparable|relevant)\b[^.\n]{0,100}"
    r"(?:experience|background)\b"
    r"|\bin lieu of (?:a |the )?degree\b"
    r"|\bequivalent\s+(?:(?:professional|work|industry|practical)\s+)?experience\b"
    r"|\bor\s+(?:a\s+)?combination of\s+(?:relevant\s+)?education[^.\n]{0,80}experience\b",
    re.I,
)
ADMINISTRATIVE_EDUCATION = re.compile(
    r"\b(?:GPA|grade point average|do not recall|application form)\b",
    re.I,
)

NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12, "fifteen": 15, "twenty": 20,
}
NUMBER_TOKEN = r"(?:\d{1,2}|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|fifteen|twenty)"
YEARS_PATTERN = re.compile(
    rf"\b(?P<low>{NUMBER_TOKEN})(?:\s*\(\s*\d{{1,2}}\s*\))?\s*"
    rf"(?:\+|(?:-|–|—|to)\s*(?P<high>{NUMBER_TOKEN})\s*\+?|or more)?\s+"
    rf"(?P<unit>years?|yrs?|months?)\b",
    re.I,
)
EXPERIENCE_SIGNAL = re.compile(
    r"\b(?:experience|experienced|professional|industry|work(?:ing)?|development|developing|"
    r"engineering|programming|hands-on|background|expertise|designing|building|education|"
    r"DevOps|SRE|role)\b",
    re.I,
)
EXPERIENCE_EXCLUSION = re.compile(
    r"\b(?:age|old|ago|founded|established|serving customers|company has|"
    r"graduated|graduation|within the (?:last|past))\b",
    re.I,
)
COMPANY_TENURE = re.compile(
    r"^\s*(?:(?:with|for)\s+)?(?:more than|over)\s+\d{2}\s+years?\b",
    re.I,
)
COMPANY_HISTORY = re.compile(
    rf"(?:"
    rf"\b(?:we(?:['’]ve| have)?|our (?:company|organization|organisation|business|firm))\b"
    rf"[^.;\n]{{0,160}}\b(?:for|over|more than)\s+{NUMBER_TOKEN}\s+years?\b"
    rf"|\b(?:for|over|more than)\s+{NUMBER_TOKEN}\s+years?\b"
    rf"[^.;\n]{{0,160}}\b(?:we(?:['’]ve| have)?|our (?:company|organization|organisation|business|firm))\b"
    rf")",
    re.I,
)
CANDIDATE_SIGNAL = re.compile(
    r"\b(?:you|your|candidate|applicant|required|requirement|must|minimum|qualification)\b",
    re.I,
)


def _line_context(text: str, start: int, end: int, radius: int = 180) -> str:
    line_start = text.rfind("\n", 0, start) + 1
    line_end = text.find("\n", end)
    if line_end < 0:
        line_end = len(text)
    line = re.sub(r"\s+", " ", text[line_start:line_end].strip())
    if len(line) <= radius * 2:
        return line
    relative_start, relative_end = start - line_start, end - line_start
    window_start = max(0, relative_start - radius)
    window_end = min(len(line), relative_end + radius)
    return ("…" if window_start else "") + line[window_start:window_end].strip() + (
        "…" if window_end < len(line) else ""
    )


def _clause_context(text: str, start: int, end: int) -> str:
    left = max(text.rfind(delimiter, 0, start) for delimiter in ("\n", ";", "."))
    right_positions = [text.find(delimiter, end) for delimiter in ("\n", ";", ".")]
    right_positions = [position for position in right_positions if position >= 0]
    right = min(right_positions) if right_positions else len(text)
    return re.sub(r"\s+", " ", text[left + 1:right].strip())


def _classification(context: str, prefix: str = "") -> str:
    if PREFERENCE_WORDS.search(context):
        return "preferred"
    if REQUIREMENT_WORDS.search(context):
        return "required"
    preferred_position = max(
        (prefix.lower().rfind(term) for term in ("preferred qualifications", "preferred requirements", "nice to have")),
        default=-1,
    )
    required_position = max(
        (prefix.lower().rfind(term) for term in ("required qualifications", "minimum qualifications", "requirements")),
        default=-1,
    )
    if preferred_position > required_position:
        return "preferred"
    if required_position >= 0:
        return "required"
    return "unspecified"


def extract_education(text: str) -> dict[str, Any]:
    text = target_job_text(text)
    mentions = []
    seen: set[tuple[str, int, int]] = set()
    for level, pattern in EDUCATION_PATTERNS:
        for match in pattern.finditer(text):
            key = (level, match.start(), match.end())
            if key in seen or any(
                seen_level == level and match.start() < seen_end and match.end() > seen_start
                for seen_level, seen_start, seen_end in seen
            ):
                continue
            context = _line_context(text, match.start(), match.end())
            if len(match.group(0).replace(".", "")) == 2 and not ABBREVIATED_DEGREE_CONTEXT.search(context):
                continue
            seen.add(key)
            clause = _clause_context(text, match.start(), match.end())
            mentions.append({
                "_position": match.start(),
                "_counts_as_minimum": (
                    _classification(
                        clause,
                        text[max(0, match.start() - 500):match.start()],
                    ) != "preferred"
                    and not OPTIONAL_DEGREE.search(context)
                    and not ADMINISTRATIVE_EDUCATION.search(context)
                ),
                "level": level,
                "matched_text": match.group(0),
                "classification": _classification(clause, text[max(0, match.start() - 500):match.start()]),
                "context": context,
            })
    mentions.sort(key=lambda item: item["_position"])
    minimum_levels = [
        item["level"] for item in mentions if item["_counts_as_minimum"]
    ]
    for item in mentions:
        item.pop("_position")
        item["counts_as_minimum"] = item.pop("_counts_as_minimum")
    mentioned_levels = [item["level"] for item in mentions]
    minimum = min(minimum_levels, key=EDUCATION_RANK.get) if minimum_levels else None
    equivalent_matches = [
        {"matched_text": match.group(0), "context": _line_context(text, match.start(), match.end())}
        for match in EQUIVALENT_EXPERIENCE.finditer(text)
    ]
    return {
        "minimum_level": minimum,
        "levels_found": sorted({item["level"] for item in mentions}, key=EDUCATION_RANK.get),
        "equivalent_experience_allowed": bool(equivalent_matches),
        "equivalent_experience_mentions": equivalent_matches,
        "mentions": mentions,
    }


def _number(value: str) -> int:
    return int(value) if value.isdigit() else NUMBER_WORDS[value.casefold()]


def _years(value: str, unit: str) -> int | float:
    amount = _number(value)
    if unit.casefold().startswith("month"):
        years = amount / 12
        return int(years) if years.is_integer() else years
    return amount


def extract_experience(text: str) -> dict[str, Any]:
    text = target_job_text(text)
    mentions = []
    for match in YEARS_PATTERN.finditer(text):
        context = _line_context(text, match.start(), match.end())
        if not EXPERIENCE_SIGNAL.search(context) or EXPERIENCE_EXCLUSION.search(context):
            continue
        clause = _clause_context(text, match.start(), match.end())
        minimum_years = _years(match.group("low"), match.group("unit"))
        if COMPANY_HISTORY.search(clause) and not CANDIDATE_SIGNAL.search(clause):
            continue
        if minimum_years >= 20 and COMPANY_TENURE.search(clause) and not CANDIDATE_SIGNAL.search(clause):
            continue
        mentions.append({
            "minimum_years": minimum_years,
            "maximum_years": (
                _years(match.group("high"), match.group("unit"))
                if match.group("high") else None
            ),
            "matched_text": match.group(0),
            "classification": _classification(clause, text[max(0, match.start() - 500):match.start()]),
            "context": context,
        })
    required = [
        item["minimum_years"] for item in mentions if item["classification"] != "preferred"
    ]
    return {
        "minimum_years": max(required) if required else None,
        "mentions": mentions,
    }

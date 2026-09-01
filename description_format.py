import html
import re


SECTION_HEADINGS = {
    "key responsibilities", "responsibilities", "required skills", "requirements",
    "preferred qualifications", "preferred skills", "qualifications",
    "required experience level", "educational requirements", "education requirements",
    "benefits", "about the role", "about the job", "what you'll do", "what you’ll do",
    "what we're looking for", "what we’re looking for",
}

LIST_SECTIONS = {
    "key responsibilities", "responsibilities", "required skills", "requirements",
    "preferred qualifications", "preferred skills", "qualifications", "benefits",
    "what you'll do", "what you’ll do", "what we're looking for", "what we’re looking for",
}

FOOTER_MARKERS = {
    "explore other jobs", "report job", "hiring lab", "career advice", "browse jobs",
    "browse companies", "your privacy choices", "privacy center and ad choices",
    "capturing job", "sending page to local ai pipeline...",
}


def _normalized(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().lower().rstrip(":")


def _is_heading(line: str) -> bool:
    return _normalized(line) in SECTION_HEADINGS or (
        line.endswith(":") and len(line) <= 80
    )


def format_description(text: str | None) -> list[dict[str, object]]:
    """Turn captured visible text into safe, readable presentation blocks."""
    if not text:
        return []

    decoded = html.unescape(text).replace("\xa0", " ")
    lines = [re.sub(r"\s+", " ", line).strip() for line in decoded.splitlines()]
    lines = [line for line in lines if line and line.lower() != "&nbsp;"]

    kept: list[str] = []
    for line in lines:
        normalized = _normalized(line)
        if normalized in FOOTER_MARKERS or normalized.startswith("discover opportunities beyond "):
            break
        kept.append(line)

    blocks: list[dict[str, object]] = []
    current_list: list[str] | None = None
    for line in kept:
        if _is_heading(line):
            heading = line.rstrip(":").strip()
            blocks.append({"type": "heading", "text": heading})
            if _normalized(heading) in LIST_SECTIONS:
                current_list = []
                blocks.append({"type": "list", "items": current_list})
            else:
                current_list = None
            continue

        value = re.sub(r"^[•·▪◦*-]\s+", "", line)
        if current_list is not None:
            current_list.append(value)
        else:
            blocks.append({"type": "paragraph", "text": value})

    return [block for block in blocks if block.get("type") != "list" or block.get("items")]

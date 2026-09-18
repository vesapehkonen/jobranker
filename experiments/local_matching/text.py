from __future__ import annotations

import re


ALIASES = {
    "amazon web services": "aws", "google cloud platform": "gcp",
    "google cloud": "gcp", "microsoft azure": "azure",
    "k8s": "kubernetes", "node js": "nodejs", "node.js": "nodejs",
    "continuous integration": "cicd", "continuous delivery": "cicd",
    "continuous deployment": "cicd", "ci/cd": "cicd",
    "artificial intelligence": "ai", "machine learning": "ml",
}

STOP_WORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "has",
    "in", "is", "it", "of", "on", "or", "our", "that", "the", "this", "to",
    "we", "will", "with", "you", "your",
}


def normalize(text: str) -> str:
    value = text.lower()
    for phrase, replacement in sorted(ALIASES.items(), key=lambda item: -len(item[0])):
        value = value.replace(phrase, replacement)
    value = re.sub(r"(?<=\w)[./-](?=\w)", "", value)
    return re.sub(r"[^a-z0-9+#.]+", " ", value).strip()


def tokens(text: str) -> list[str]:
    return [token for token in normalize(text).split() if token not in STOP_WORDS and len(token) > 1]


def chunks(text: str, max_words: int = 160) -> list[str]:
    paragraphs = [
        part.strip()
        for part in re.split(r"\n\s*\n|^\s*[•*-]\s+", text, flags=re.MULTILINE)
        if part.strip()
    ]
    result: list[str] = []
    for paragraph in paragraphs:
        words = paragraph.split()
        result.extend(" ".join(words[index:index + max_words]) for index in range(0, len(words), max_words))
    return result or ([text.strip()] if text.strip() else [])

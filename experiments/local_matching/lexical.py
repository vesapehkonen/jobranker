from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass

from .data import JobInput, ProfileInput
from .text import normalize, tokens


@dataclass(frozen=True)
class LexicalResult:
    score: float
    word_score: float
    character_score: float
    shared_terms: tuple[str, ...]


def _word_features(text: str) -> Counter[str]:
    words = tokens(text)
    features = Counter(f"w:{word}" for word in words)
    features.update(f"b:{left}_{right}" for left, right in zip(words, words[1:]))
    return features


def _character_features(text: str) -> Counter[str]:
    compact = f" {normalize(text)} "
    features: Counter[str] = Counter()
    for size in (3, 4, 5):
        features.update(f"c:{compact[index:index + size]}" for index in range(len(compact) - size + 1))
    return features


def _idf(documents: list[Counter[str]]) -> dict[str, float]:
    frequencies: Counter[str] = Counter()
    for document in documents:
        frequencies.update(document.keys())
    count = len(documents)
    return {feature: math.log((1 + count) / (1 + frequency)) + 1 for feature, frequency in frequencies.items()}


def _vector(features: Counter[str], idf: dict[str, float]) -> dict[str, float]:
    return {key: (1 + math.log(value)) * idf[key] for key, value in features.items()}


def _cosine(left: dict[str, float], right: dict[str, float]) -> float:
    common = left.keys() & right.keys()
    numerator = sum(left[key] * right[key] for key in common)
    left_norm = math.sqrt(sum(value * value for value in left.values()))
    right_norm = math.sqrt(sum(value * value for value in right.values()))
    return numerator / (left_norm * right_norm) if left_norm and right_norm else 0.0


class LexicalMatcher:
    def __init__(self, jobs: list[JobInput], profiles: list[ProfileInput]):
        texts = [item.text for item in jobs] + [item.text for item in profiles]
        word_documents = [_word_features(text) for text in texts]
        character_documents = [_character_features(text) for text in texts]
        self.word_idf = _idf(word_documents)
        self.character_idf = _idf(character_documents)
        self.word_vectors = {
            text: _vector(features, self.word_idf)
            for text, features in zip(texts, word_documents)
        }
        self.character_vectors = {
            text: _vector(features, self.character_idf)
            for text, features in zip(texts, character_documents)
        }

    def compare(self, job_text: str, profile_text: str) -> LexicalResult:
        job_words = self.word_vectors.get(job_text) or _vector(_word_features(job_text), self.word_idf)
        profile_words = self.word_vectors.get(profile_text) or _vector(_word_features(profile_text), self.word_idf)
        job_characters = self.character_vectors.get(job_text) or _vector(_character_features(job_text), self.character_idf)
        profile_characters = self.character_vectors.get(profile_text) or _vector(_character_features(profile_text), self.character_idf)
        word_score = _cosine(job_words, profile_words)
        character_score = _cosine(job_characters, profile_characters)
        score = 100 * (0.8 * word_score + 0.2 * character_score)
        shared = sorted(
            set(tokens(job_text)) & set(tokens(profile_text)),
            key=lambda term: self.word_idf.get(f"w:{term}", 0),
            reverse=True,
        )[:15]
        return LexicalResult(score, 100 * word_score, 100 * character_score, tuple(shared))

from __future__ import annotations

import math
from typing import Protocol

from .text import chunks


class Encoder(Protocol):
    def encode(self, sentences: list[str], **kwargs) -> object: ...


def _rows(values: object) -> list[list[float]]:
    if hasattr(values, "tolist"):
        values = values.tolist()
    return [[float(value) for value in row] for row in values]  # type: ignore[union-attr]


def _cosine(left: list[float], right: list[float]) -> float:
    numerator = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    return numerator / (left_norm * right_norm) if left_norm and right_norm else 0.0


class SemanticMatcher:
    def __init__(self, encoder: Encoder, *, max_words: int = 160):
        self.encoder = encoder
        self.max_words = max_words
        self.cache: dict[str, list[float]] = {}

    def _embeddings(self, texts: list[str]) -> list[list[float]]:
        missing = list(dict.fromkeys(text for text in texts if text not in self.cache))
        if missing:
            encoded = _rows(self.encoder.encode(
                missing, batch_size=16, show_progress_bar=False, normalize_embeddings=True
            ))
            self.cache.update(zip(missing, encoded))
        return [self.cache[text] for text in texts]

    def prime(self, documents: list[str]) -> None:
        """Encode all chunks in batches before pairwise comparisons."""
        all_chunks = [chunk for document in documents for chunk in chunks(document, self.max_words)]
        self._embeddings(all_chunks)

    def compare(self, job_text: str, profile_text: str) -> float:
        job_chunks = chunks(job_text, self.max_words)
        profile_chunks = chunks(profile_text, self.max_words)
        job_vectors = self._embeddings(job_chunks)
        profile_vectors = self._embeddings(profile_chunks)
        best_for_job = [
            max(_cosine(job, profile) for profile in profile_vectors)
            for job in job_vectors
        ]
        strongest = sorted(best_for_job, reverse=True)[:min(5, len(best_for_job))]
        similarity = 0.7 * (sum(strongest) / len(strongest)) + 0.3 * (
            sum(best_for_job) / len(best_for_job)
        )
        return 100 * max(0.0, min(1.0, similarity))


def load_sentence_transformer(model_name: str) -> Encoder:
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as error:
        raise RuntimeError(
            "Semantic dependencies are not installed. Run: "
            "pip install -r experiments/local_matching/requirements.txt"
        ) from error
    try:
        return SentenceTransformer(model_name, device="cpu", local_files_only=True)
    except OSError:
        # The first run may download the model; later runs remain fully local.
        return SentenceTransformer(model_name, device="cpu")

from __future__ import annotations

from dataclasses import dataclass

from software_maintaince_agent.retrieval import cosine, hashed_vector


@dataclass
class HashingTextEncoder:
    dimensions: int = 128

    def encode(self, text: str) -> list[float]:
        return hashed_vector(text, self.dimensions)

    def similarity(self, left: str, right: str) -> float:
        return cosine(self.encode(left), self.encode(right))

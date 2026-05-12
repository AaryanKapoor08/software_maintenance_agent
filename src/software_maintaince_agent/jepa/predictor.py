from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from software_maintaince_agent.jepa.encoders import HashingTextEncoder
from software_maintaince_agent.models import MaintenanceTask, RetrievalCandidate
from software_maintaince_agent.retrieval import build_file_documents, cosine


@dataclass
class CodeJepaExample:
    context: str
    target_path: str
    target_text: str


@dataclass
class CodeJepaPredictor:
    """Small latent predictor for V1 retrieval.

    This is intentionally lightweight: it maps issue context into target-file latent space by
    storing context-target pairs and predicting a target embedding with similarity-weighted
    nearest neighbors. It is JEPA-inspired because it predicts hidden code-region embeddings
    instead of reconstructing source text.
    """

    encoder: HashingTextEncoder = field(default_factory=HashingTextEncoder)
    examples: list[CodeJepaExample] = field(default_factory=list)

    def fit(self, examples: list[CodeJepaExample]) -> None:
        self.examples = examples

    def predict_target_embedding(self, context: str) -> list[float]:
        if not self.examples:
            return self.encoder.encode(context)
        context_vec = self.encoder.encode(context)
        weighted = [0.0] * self.encoder.dimensions
        total = 0.0
        for example in self.examples:
            weight = max(cosine(context_vec, self.encoder.encode(example.context)), 0.01)
            target_vec = self.encoder.encode(f"{example.target_path}\n{example.target_text}")
            for index, value in enumerate(target_vec):
                weighted[index] += value * weight
            total += weight
        if not total:
            return context_vec
        return [value / total for value in weighted]

    def rerank(
        self,
        repo_dir: Path,
        task: MaintenanceTask,
        candidates: list[RetrievalCandidate],
        top_k: int = 8,
    ) -> list[RetrievalCandidate]:
        docs = build_file_documents(repo_dir)
        predicted = self.predict_target_embedding(f"{task.title}\n{task.body}")
        ranked: list[RetrievalCandidate] = []
        candidate_paths = [candidate.path for candidate in candidates] or list(docs)
        for path in candidate_paths:
            text = docs.get(path, path)
            score = cosine(predicted, self.encoder.encode(f"{path}\n{text}"))
            baseline = next((candidate.score for candidate in candidates if candidate.path == path), 0.0)
            ranked.append(
                RetrievalCandidate(
                    path=path,
                    score=round(score + baseline * 0.05, 3),
                    reasons=["Code-JEPA predicted target embedding", "baseline score blended"],
                )
            )
        return sorted(ranked, key=lambda candidate: candidate.score, reverse=True)[:top_k]

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": "code-jepa-v1",
            "dimensions": self.encoder.dimensions,
            "objective": "predict hidden relevant file embedding from issue context",
            "examples": [example.__dict__ for example in self.examples],
        }
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> CodeJepaPredictor:
        payload = json.loads(path.read_text(encoding="utf-8"))
        encoder = HashingTextEncoder(dimensions=payload.get("dimensions", 128))
        predictor = cls(encoder=encoder)
        predictor.fit([CodeJepaExample(**item) for item in payload.get("examples", [])])
        return predictor

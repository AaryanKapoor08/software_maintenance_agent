from __future__ import annotations

import math
import re
import time
from collections import Counter, defaultdict
from hashlib import blake2b
from pathlib import Path

from software_maintaince_agent.models import MaintenanceTask, RetrievalCandidate
from software_maintaince_agent.repo_inspect import iter_repo_files

TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]+|[A-Za-z0-9_.-]+")
STACK_FILE_RE = re.compile(r'File "([^"]+\.(?:py|js|ts|tsx|jsx))"')


def tokenize(text: str) -> list[str]:
    return [token.lower() for token in TOKEN_RE.findall(text) if len(token) > 1]


def parse_stack_files(log_text: str) -> set[str]:
    return {match.replace("\\", "/") for match in STACK_FILE_RE.findall(log_text)}


def file_text(path: Path, limit: int = 12000) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")[:limit]
    except OSError:
        return ""


def build_file_documents(repo_dir: Path) -> dict[str, str]:
    docs: dict[str, str] = {}
    for path in iter_repo_files(repo_dir):
        rel = path.relative_to(repo_dir).as_posix()
        if path.suffix.lower() not in {".py", ".js", ".ts", ".tsx", ".jsx", ".md", ".toml", ".json"}:
            continue
        docs[rel] = f"{rel}\n{file_text(path)}"
    return docs


def lexical_retrieve(
    repo_dir: Path,
    task: MaintenanceTask,
    log_text: str = "",
    top_k: int = 8,
) -> list[RetrievalCandidate]:
    docs = build_file_documents(repo_dir)
    query_text = f"{task.title}\n{task.body}\n{log_text}"
    query_terms = tokenize(query_text)
    stack_files = parse_stack_files(log_text)
    if not docs:
        return []

    doc_terms = {path: tokenize(text) for path, text in docs.items()}
    df: Counter[str] = Counter()
    for terms in doc_terms.values():
        df.update(set(terms))

    scores: dict[str, float] = defaultdict(float)
    reasons: dict[str, list[str]] = defaultdict(list)
    doc_count = len(doc_terms)
    for term in query_terms:
        idf = math.log((doc_count + 1) / (df.get(term, 0) + 1)) + 1
        for path, terms in doc_terms.items():
            tf = terms.count(term)
            if tf:
                scores[path] += (1 + math.log(tf)) * idf
                if len(reasons[path]) < 5:
                    reasons[path].append(f"matched term `{term}`")

    for path in docs:
        path_tokens = tokenize(path)
        if any(term in path_tokens for term in query_terms):
            scores[path] += 6
            reasons[path].append("path token matched issue")
        if "test" in path or "/tests/" in path:
            scores[path] += 1
        if any(path.endswith(stack_file) or stack_file.endswith(path) for stack_file in stack_files):
            scores[path] += 25
            reasons[path].append("referenced by failure stack trace")

    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    return [
        RetrievalCandidate(path=path, score=round(score, 3), reasons=reasons[path] or ["repository file"])
        for path, score in ranked[:top_k]
        if score > 0
    ]


def expanded_query(task: MaintenanceTask, log_text: str = "") -> str:
    """HyDE-style low-cost query expansion for code maintenance retrieval."""
    hints = [
        task.title,
        task.body,
        log_text,
        "relevant implementation files validation parser handler schema model service utility",
        "related tests failing assertion expected actual stack trace",
    ]
    if "email" in f"{task.title}\n{task.body}".lower():
        hints.append("email validation empty blank whitespace string validator schema")
    return "\n".join(item for item in hints if item)


def hashed_vector(text: str, dimensions: int = 128) -> list[float]:
    vector = [0.0] * dimensions
    for token in tokenize(text):
        digest = blake2b(token.encode("utf-8"), digest_size=8).digest()
        vector[int.from_bytes(digest, "big") % dimensions] += 1.0
    norm = math.sqrt(sum(value * value for value in vector)) or 1.0
    return [value / norm for value in vector]


def cosine(left: list[float], right: list[float]) -> float:
    return sum(a * b for a, b in zip(left, right, strict=False))


def embedding_retrieve(
    repo_dir: Path,
    task: MaintenanceTask,
    log_text: str = "",
    top_k: int = 8,
) -> list[RetrievalCandidate]:
    started = time.perf_counter()
    del started
    docs = build_file_documents(repo_dir)
    query = hashed_vector(expanded_query(task, log_text))
    candidates: list[RetrievalCandidate] = []
    for path, text in docs.items():
        score = cosine(query, hashed_vector(text))
        candidates.append(
            RetrievalCandidate(
                path=path,
                score=round(score, 3),
                reasons=["hash embedding similarity"],
            )
        )
    return sorted(candidates, key=lambda candidate: candidate.score, reverse=True)[:top_k]


def reciprocal_rank_fusion(
    rankings: list[list[RetrievalCandidate]],
    top_k: int = 8,
    rank_constant: int = 60,
) -> list[RetrievalCandidate]:
    scores: dict[str, float] = defaultdict(float)
    reasons: dict[str, list[str]] = defaultdict(list)
    for ranking_index, ranking in enumerate(rankings, start=1):
        for rank, candidate in enumerate(ranking, start=1):
            scores[candidate.path] += 1.0 / (rank_constant + rank)
            for reason in candidate.reasons:
                annotated = f"r{ranking_index}: {reason}"
                if annotated not in reasons[candidate.path] and len(reasons[candidate.path]) < 8:
                    reasons[candidate.path].append(annotated)
    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    return [
        RetrievalCandidate(path=path, score=round(score, 6), reasons=reasons[path])
        for path, score in ranked[:top_k]
    ]


def hybrid_retrieve(
    repo_dir: Path,
    task: MaintenanceTask,
    log_text: str = "",
    top_k: int = 8,
    include_semantic_only: bool = False,
) -> list[RetrievalCandidate]:
    lexical = lexical_retrieve(repo_dir, task, log_text=log_text, top_k=max(top_k, 12))
    embedding = embedding_retrieve(repo_dir, task, log_text=log_text, top_k=max(top_k, 12))
    fused = reciprocal_rank_fusion([lexical, embedding], top_k=max(top_k, len(lexical), 1))
    if include_semantic_only or not lexical:
        return fused[:top_k]
    lexical_paths = {candidate.path for candidate in lexical}
    anchored = [candidate for candidate in fused if candidate.path in lexical_paths]
    return anchored[:top_k]


def recall_at_k(candidates: list[RetrievalCandidate], relevant: list[str], k: int) -> float:
    if not relevant:
        return 0.0
    top = {candidate.path for candidate in candidates[:k]}
    expected = {path.replace("\\", "/") for path in relevant}
    return len(top & expected) / len(expected)

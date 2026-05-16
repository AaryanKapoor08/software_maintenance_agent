from __future__ import annotations

import json
import time
from pathlib import Path

from software_maintaince_agent.agent import load_task
from software_maintaince_agent.jepa.dataset import examples_from_task_files
from software_maintaince_agent.jepa.predictor import CodeJepaPredictor
from software_maintaince_agent.models import BenchmarkReport, BenchmarkSuite, RetrievalMetrics
from software_maintaince_agent.retrieval import embedding_retrieve, hybrid_retrieve, lexical_retrieve, recall_at_k


def load_suite(path: Path) -> BenchmarkSuite:
    data = json.loads(path.read_text(encoding="utf-8"))
    suite_dir = path.parent
    tasks = []
    for item in data.get("tasks", []):
        task_file = Path(item["task_file"])
        if not task_file.is_absolute():
            task_file = (suite_dir / task_file).resolve()
        tasks.append({"task_file": task_file})
    return BenchmarkSuite(name=data["name"], tasks=tasks)


def run_retrieval_benchmark(suite_path: Path, output_dir: Path) -> BenchmarkReport:
    suite = load_suite(suite_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    task_files = [task.task_file for task in suite.tasks]
    predictor = CodeJepaPredictor()
    predictor.fit(examples_from_task_files(task_files))
    predictor.save(output_dir / "jepa_artifacts" / "code_jepa_v1.json")

    method_candidates: dict[str, list[tuple[list, list[str]]]] = {
        "keyword_bm25": [],
        "embedding": [],
        "hybrid_rrf": [],
        "code_jepa_v1": [],
    }
    latencies: dict[str, int] = {}

    for suite_task in suite.tasks:
        task = load_task(suite_task.task_file)
        repo_dir = (suite_task.task_file.parent / ".." / task.repo_url).resolve()
        if not repo_dir.exists():
            repo_dir = Path(task.repo_url).resolve()
        relevant = task.expected_relevant_files or task.expected_changed_files

        started = time.perf_counter()
        lexical = lexical_retrieve(repo_dir, task, top_k=8)
        latencies["keyword_bm25"] = latencies.get("keyword_bm25", 0) + int(
            (time.perf_counter() - started) * 1000
        )
        method_candidates["keyword_bm25"].append((lexical, relevant))

        started = time.perf_counter()
        embedding = embedding_retrieve(repo_dir, task, top_k=8)
        latencies["embedding"] = latencies.get("embedding", 0) + int(
            (time.perf_counter() - started) * 1000
        )
        method_candidates["embedding"].append((embedding, relevant))

        started = time.perf_counter()
        hybrid = hybrid_retrieve(repo_dir, task, top_k=8)
        latencies["hybrid_rrf"] = latencies.get("hybrid_rrf", 0) + int(
            (time.perf_counter() - started) * 1000
        )
        method_candidates["hybrid_rrf"].append((hybrid, relevant))

        started = time.perf_counter()
        jepa = predictor.rerank(repo_dir, task, hybrid, top_k=8)
        latencies["code_jepa_v1"] = latencies.get("code_jepa_v1", 0) + int(
            (time.perf_counter() - started) * 1000
        )
        method_candidates["code_jepa_v1"].append((jepa, relevant))

    metrics = [
        build_metrics(method, pairs, latencies.get(method, 0))
        for method, pairs in method_candidates.items()
    ]
    baseline = next(metric for metric in metrics if metric.method == "keyword_bm25")
    jepa_metric = next(metric for metric in metrics if metric.method == "code_jepa_v1")
    jepa_status = (
        "active"
        if jepa_metric.top_5_recall > baseline.top_5_recall
        or (
            jepa_metric.top_5_recall == baseline.top_5_recall
            and jepa_metric.average_context_files <= baseline.average_context_files * 0.75
        )
        else "experimental"
    )
    report = BenchmarkReport(
        suite=suite.name,
        task_count=len(suite.tasks),
        metrics=metrics,
        jepa_status=jepa_status,
    )
    report_path = output_dir / "benchmark_report.md"
    report.report_path = str(report_path)
    report_path.write_text(render_benchmark_report(report), encoding="utf-8")
    (output_dir / "benchmark_report.json").write_text(report.model_dump_json(indent=2), encoding="utf-8")
    return report


def build_metrics(method: str, pairs: list[tuple[list, list[str]]], latency_ms: int) -> RetrievalMetrics:
    if not pairs:
        return RetrievalMetrics(
            method=method,
            top_1_recall=0,
            top_3_recall=0,
            top_5_recall=0,
            average_context_files=0,
            latency_ms=latency_ms,
        )
    return RetrievalMetrics(
        method=method,
        top_1_recall=round(sum(recall_at_k(candidates, relevant, 1) for candidates, relevant in pairs) / len(pairs), 3),
        top_3_recall=round(sum(recall_at_k(candidates, relevant, 3) for candidates, relevant in pairs) / len(pairs), 3),
        top_5_recall=round(sum(recall_at_k(candidates, relevant, 5) for candidates, relevant in pairs) / len(pairs), 3),
        average_context_files=round(sum(min(len(candidates), 5) for candidates, _ in pairs) / len(pairs), 2),
        latency_ms=latency_ms,
    )


def render_benchmark_report(report: BenchmarkReport) -> str:
    lines = [
        "# Software Maintenance Agent Retrieval Benchmark",
        "",
        f"Suite: `{report.suite}`",
        f"Tasks: `{report.task_count}`",
        f"Code-JEPA status: **{report.jepa_status}**",
        "",
        "| Method | Top-1 Recall | Top-3 Recall | Top-5 Recall | Avg Context Files | Latency ms |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for metric in report.metrics:
        lines.append(
            f"| {metric.method} | {metric.top_1_recall:.3f} | {metric.top_3_recall:.3f} | "
            f"{metric.top_5_recall:.3f} | {metric.average_context_files:.2f} | {metric.latency_ms} |"
        )
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            (
                "Code-JEPA is used only when it improves top-5 recall or preserves recall with at least "
                "25% fewer context files. Otherwise it remains experimental."
            ),
        ]
    )
    return "\n".join(lines)

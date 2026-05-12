from __future__ import annotations

from pathlib import Path

from patchpilot.evals.benchmark import run_retrieval_benchmark


def test_benchmark_writes_report(tmp_path: Path) -> None:
    report = run_retrieval_benchmark(Path("benchmark/suites/mvp.json"), tmp_path)
    assert report.task_count == 2
    assert report.report_path is not None
    assert Path(report.report_path).exists()
    assert {metric.method for metric in report.metrics} >= {
        "keyword_bm25",
        "embedding",
        "hybrid_rrf",
        "code_jepa_v1",
    }

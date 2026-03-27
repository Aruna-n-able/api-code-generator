"""
metrics.py – Compute reliability metrics for individual tests across runs.

Given multiple parsed Robot Framework runs, this module groups results by
test name and computes:

* failure_rate     – fraction of runs in which the test failed
* flakiness_score  – High / Medium / Low categorical label
* duration_variance – variance in elapsed time (milliseconds²)
* first_seen       – earliest datetime of a recorded failure
* last_seen        – latest datetime of a recorded failure
* total_runs       – total number of runs containing the test
* failure_count    – number of runs in which the test failed
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from .robot_parser import ParsedRun, TestResult


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class TestMetrics:
    """Aggregated reliability metrics for a single test name."""

    name: str
    suite: str
    total_runs: int
    failure_count: int
    failure_rate: float           # 0.0 – 1.0
    flakiness_score: str          # "High" | "Medium" | "Low" | "Stable"
    duration_variance: float      # variance of elapsed_ms across runs
    first_seen: Optional[datetime]
    last_seen: Optional[datetime]
    failure_messages: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)

    @property
    def failure_rate_display(self) -> str:
        return f"{self.failure_count}/{self.total_runs} runs"


# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------

# A test is considered flaky only when it has BOTH passing and failing runs.
# This excludes consistently broken tests, which should be fixed rather than
# classified as flaky.

# Failure-rate thresholds for flakiness score categories
_HIGH_THRESHOLD = 0.50    # ≥ 50 % failure rate → High
_MEDIUM_THRESHOLD = 0.20  # ≥ 20 % failure rate → Medium


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class MetricsEngine:
    """Aggregate test results across multiple runs and compute metrics."""

    def compute(self, runs: List[ParsedRun]) -> List[TestMetrics]:
        """
        Return a list of :class:`TestMetrics` for every test that appeared in
        at least one run, sorted by flakiness score (High → Medium → Low → Stable).
        """
        # Group results by test name
        grouped: Dict[str, List[TestResult]] = {}
        for run in runs:
            for test in run.tests:
                grouped.setdefault(test.name, []).append(test)

        metrics_list: List[TestMetrics] = []
        for test_name, results in grouped.items():
            metrics_list.append(self._compute_one(test_name, results))

        metrics_list.sort(key=lambda m: self._score_order(m.flakiness_score))
        return metrics_list

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _compute_one(self, name: str, results: List[TestResult]) -> TestMetrics:
        total = len(results)
        failures = [r for r in results if r.status == "FAIL"]
        passes = [r for r in results if r.status == "PASS"]
        failure_count = len(failures)
        failure_rate = failure_count / total if total > 0 else 0.0

        # Duration variance (use all results, not just failures)
        durations = [r.elapsed_ms for r in results]
        duration_variance = statistics.variance(durations) if len(durations) >= 2 else 0.0

        # Timestamps
        failure_times = [r.start_time for r in failures if r.start_time]
        first_seen: Optional[datetime] = min(failure_times) if failure_times else None
        last_seen: Optional[datetime] = max(failure_times) if failure_times else None

        # Unique failure messages (deduplicated)
        failure_messages = list({r.message for r in failures if r.message})

        # Tags from any result
        tags = list({tag for r in results for tag in r.tags})

        # Suite name (from first result)
        suite = results[0].suite if results else ""

        # A test is only considered flaky if it has BOTH passes and failures
        # (i.e., it is genuinely inconsistent, not consistently broken)
        has_mixed_results = bool(passes) and bool(failures)
        score = self._score(has_mixed_results, failure_rate)

        return TestMetrics(
            name=name,
            suite=suite,
            total_runs=total,
            failure_count=failure_count,
            failure_rate=failure_rate,
            flakiness_score=score,
            duration_variance=duration_variance,
            first_seen=first_seen,
            last_seen=last_seen,
            failure_messages=failure_messages,
            tags=tags,
        )

    @staticmethod
    def _score(has_mixed_results: bool, failure_rate: float) -> str:
        if not has_mixed_results:
            return "Stable"
        if failure_rate >= _HIGH_THRESHOLD:
            return "High"
        if failure_rate >= _MEDIUM_THRESHOLD:
            return "Medium"
        return "Low"

    @staticmethod
    def _score_order(score: str) -> Tuple[int, str]:
        order = {"High": 0, "Medium": 1, "Low": 2, "Stable": 3}
        return (order.get(score, 4), score)

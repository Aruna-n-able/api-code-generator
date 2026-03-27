"""
recommender.py – Generate structured, code-level fix recommendations.

Each recommendation combines:
* A description of the detected pattern
* The fix template from the pattern knowledge base
* Context extracted from the actual failure messages
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from .metrics import TestMetrics
from .pattern_db import Pattern, PatternDatabase
from .robot_parser import TestResult


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class Recommendation:
    """A concrete fix recommendation for a specific flaky test."""

    test_name: str
    pattern_id: str
    pattern_name: str
    description: str
    fix_template: str
    severity_weight: int
    matched_signals: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Recommender
# ---------------------------------------------------------------------------

class Recommender:
    """
    Match flaky tests against the pattern knowledge base and produce
    actionable fix recommendations.
    """

    def __init__(self, pattern_db: PatternDatabase | None = None) -> None:
        self._db = pattern_db or PatternDatabase()

    def recommend(
        self,
        metrics: TestMetrics,
        sample_results: List[TestResult],
    ) -> List[Recommendation]:
        """
        Return a list of :class:`Recommendation` objects for *metrics*.

        *sample_results* should be the raw :class:`TestResult` entries for
        the same test name – any failed result is used for pattern matching.
        """
        if metrics.flakiness_score == "Stable":
            return []

        failed_results = [r for r in sample_results if r.status == "FAIL"]
        if not failed_results:
            return []

        seen_pattern_ids: set[str] = set()
        recommendations: List[Recommendation] = []

        for result in failed_results:
            matched = self._db.match(result)
            for pattern in matched:
                if pattern.id in seen_pattern_ids:
                    continue
                seen_pattern_ids.add(pattern.id)
                recommendations.append(
                    self._build_recommendation(metrics.name, result, pattern)
                )

        # Sort by severity weight descending (most severe first)
        recommendations.sort(key=lambda r: r.severity_weight, reverse=True)
        return recommendations

    def recommend_for_failed(
        self,
        test_name: str,
        sample_results: List[TestResult],
    ) -> List[Recommendation]:
        """
        Return pattern-based recommendations for *test_name* using only its
        failed results, without requiring a flakiness score.

        Use this when analysing a ticket that may have only a single test run
        (where the usual flakiness classification is not applicable).
        """
        failed_results = [r for r in sample_results if r.status == "FAIL"]
        if not failed_results:
            return []

        seen_pattern_ids: set[str] = set()
        recommendations: List[Recommendation] = []

        for result in failed_results:
            matched = self._db.match(result)
            for pattern in matched:
                if pattern.id in seen_pattern_ids:
                    continue
                seen_pattern_ids.add(pattern.id)
                recommendations.append(
                    self._build_recommendation(test_name, result, pattern)
                )

        recommendations.sort(key=lambda r: r.severity_weight, reverse=True)
        return recommendations

    def recommend_all(
        self,
        all_metrics: List[TestMetrics],
        all_results: dict[str, List[TestResult]],
    ) -> dict[str, List[Recommendation]]:
        """
        Convenience method: recommend fixes for every flaky test.

        *all_results* maps test name → list of TestResult objects.
        Returns a dict of test name → list of Recommendation.
        """
        output: dict[str, List[Recommendation]] = {}
        for m in all_metrics:
            if m.flakiness_score != "Stable":
                sample = all_results.get(m.name, [])
                recs = self.recommend(m, sample)
                if recs:
                    output[m.name] = recs
        return output

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _build_recommendation(
        test_name: str,
        result: TestResult,
        pattern: Pattern,
    ) -> Recommendation:
        # Collect the signals that triggered the match
        haystack = (result.name + " " + result.message + " " + result.suite).lower()
        matched_signals: List[str] = []

        for kw in pattern.keywords:
            if kw in haystack:
                matched_signals.append(f"keyword: {kw}")
        for rkw in pattern.robot_keywords:
            if rkw in haystack:
                matched_signals.append(f"robot_keyword: {rkw}")
        for regex in pattern.error_patterns:
            if regex.search(result.message):
                matched_signals.append(f"error_pattern: {regex.pattern}")

        return Recommendation(
            test_name=test_name,
            pattern_id=pattern.id,
            pattern_name=pattern.name,
            description=pattern.description,
            fix_template=pattern.fix_template,
            severity_weight=pattern.severity_weight,
            matched_signals=matched_signals,
        )

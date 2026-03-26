"""
skill.py – Claude-powered Flaky Test Analysis Skill.

This module is the top-level orchestrator.  It wires together:
  1. RobotOutputParser  – parse output.xml artefacts
  2. MetricsEngine      – compute flakiness metrics across runs
  3. PatternDatabase    – match known flaky patterns
  4. Recommender        – generate code-level fix suggestions
  5. Claude AI          – produce a natural-language summary (optional)
  6. JiraClient         – post the report to a Jira issue (optional)

The skill can be used:
  a. Programmatically via the FlakyTestAnalysisSkill class.
  b. From the command line via run_flaky_analysis.py.
  c. As an MCP tool by exposing run_analysis() through an MCP server.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from .jira_client import JiraClient
from .metrics import MetricsEngine, TestMetrics
from .pattern_db import PatternDatabase
from .recommender import Recommendation, Recommender
from .robot_parser import ParsedRun, RobotOutputParser, TestResult

logger = logging.getLogger(__name__)

try:
    import anthropic as _anthropic
    _ANTHROPIC_AVAILABLE = True
except ImportError:
    _ANTHROPIC_AVAILABLE = False


# ---------------------------------------------------------------------------
# Analysis result data model
# ---------------------------------------------------------------------------

@dataclass
class FlakyTestReport:
    """Full analysis output for a set of Robot Framework test runs."""

    runs: List[ParsedRun]
    metrics: List[TestMetrics]
    recommendations: Dict[str, List[Recommendation]]
    ai_summary: str = ""
    formatted_report: str = ""


# ---------------------------------------------------------------------------
# Skill
# ---------------------------------------------------------------------------

class FlakyTestAnalysisSkill:
    """
    Orchestrates flaky test detection, metric computation, pattern matching,
    AI summarisation, and Jira comment posting.

    Parameters
    ----------
    anthropic_api_key:
        Anthropic API key.  Falls back to the ``ANTHROPIC_API_KEY`` env var.
        When not set, AI summarisation is skipped and rule-based output is used.
    claude_model:
        Claude model to use for summarisation.
    patterns_file:
        Path to a custom ``flaky_patterns.yaml``; uses the bundled one by default.
    jira_client:
        A pre-configured :class:`JiraClient` instance.  If not supplied, one
        is created from environment variables when Jira posting is requested.
    """

    def __init__(
        self,
        anthropic_api_key: Optional[str] = None,
        claude_model: str = "claude-3-5-sonnet-20241022",
        patterns_file: Optional[str] = None,
        jira_client: Optional[JiraClient] = None,
    ) -> None:
        self._api_key = anthropic_api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self._model = claude_model
        self._parser = RobotOutputParser()
        self._metrics_engine = MetricsEngine()
        self._pattern_db = (
            PatternDatabase(patterns_file) if patterns_file else PatternDatabase()
        )
        self._recommender = Recommender(self._pattern_db)
        self._jira: Optional[JiraClient] = jira_client

    # ------------------------------------------------------------------
    # Primary entry point
    # ------------------------------------------------------------------

    def run_analysis(
        self,
        output_xml_paths: List[str | Path],
        jira_issue_key: Optional[str] = None,
        use_ai_summary: bool = True,
    ) -> FlakyTestReport:
        """
        Analyse one or more Robot Framework ``output.xml`` files.

        Parameters
        ----------
        output_xml_paths:
            Paths to ``output.xml`` files from different test runs.
            Pass multiple files to enable cross-run flakiness detection.
        jira_issue_key:
            When provided the formatted report is posted to this Jira issue.
        use_ai_summary:
            Generate a natural-language summary using the Claude API.
            Requires ``ANTHROPIC_API_KEY`` to be set.

        Returns
        -------
        FlakyTestReport
            Contains metrics, recommendations, AI summary, and the formatted
            markdown report.
        """
        logger.info("Parsing %d output.xml file(s)…", len(output_xml_paths))
        runs = self._parser.parse_files(output_xml_paths)

        logger.info("Computing flakiness metrics…")
        metrics = self._metrics_engine.compute(runs)

        # Build a lookup: test_name → all raw TestResult objects
        all_results: Dict[str, List[TestResult]] = {}
        for run in runs:
            for result in run.tests:
                all_results.setdefault(result.name, []).append(result)

        logger.info("Matching flaky patterns and generating recommendations…")
        recommendations = self._recommender.recommend_all(metrics, all_results)

        ai_summary = ""
        if use_ai_summary and self._api_key:
            ai_summary = self._generate_ai_summary(metrics, recommendations)

        formatted = self._format_report(metrics, recommendations, ai_summary, runs)

        report = FlakyTestReport(
            runs=runs,
            metrics=metrics,
            recommendations=recommendations,
            ai_summary=ai_summary,
            formatted_report=formatted,
        )

        if jira_issue_key:
            self._post_to_jira(jira_issue_key, formatted)

        return report

    # ------------------------------------------------------------------
    # AI summarisation
    # ------------------------------------------------------------------

    def _generate_ai_summary(
        self,
        metrics: List[TestMetrics],
        recommendations: Dict[str, List[Recommendation]],
    ) -> str:
        """Call Claude to produce a concise executive summary."""
        if not _ANTHROPIC_AVAILABLE:
            logger.warning(
                "anthropic package not installed; skipping AI summary. "
                "Install with: pip install anthropic"
            )
            return ""

        flaky_tests = [m for m in metrics if m.flakiness_score != "Stable"]
        if not flaky_tests:
            return "No flaky tests detected across the provided runs."

        prompt_lines = [
            "You are an expert in software testing and CI/CD reliability.",
            "",
            "Analyse the following flaky test data and write a concise executive summary "
            "(4–8 sentences). Focus on the highest-severity issues, patterns found, and "
            "the most impactful remediation steps. Do not repeat information verbatim "
            "from the data; synthesise it for an engineering audience.",
            "",
            "## Flaky Tests Detected",
            "",
        ]
        for m in flaky_tests:
            prompt_lines.append(
                f"- **{m.name}** | Score: {m.flakiness_score} | "
                f"Failure rate: {m.failure_rate_display}"
            )
            recs = recommendations.get(m.name, [])
            if recs:
                patterns = ", ".join(r.pattern_name for r in recs)
                prompt_lines.append(f"  Patterns: {patterns}")

        client = _anthropic.Anthropic(api_key=self._api_key)
        message = client.messages.create(
            model=self._model,
            max_tokens=512,
            messages=[{"role": "user", "content": "\n".join(prompt_lines)}],
        )
        return message.content[0].text if message.content else ""

    # ------------------------------------------------------------------
    # Report formatting
    # ------------------------------------------------------------------

    def _format_report(
        self,
        metrics: List[TestMetrics],
        recommendations: Dict[str, List[Recommendation]],
        ai_summary: str,
        runs: List[ParsedRun],
    ) -> str:
        lines: List[str] = ["# Flaky Test Analysis Report", ""]

        # Header statistics
        total_tests = len(metrics)
        flaky_tests = [m for m in metrics if m.flakiness_score != "Stable"]
        lines += [
            f"**Total tests analysed:** {total_tests}  ",
            f"**Flaky tests detected:** {len(flaky_tests)}  ",
            f"**Runs analysed:** {len(runs)}  ",
            "",
        ]

        # AI summary
        if ai_summary:
            lines += ["## Executive Summary", "", ai_summary, ""]

        # Per-test sections
        if not flaky_tests:
            lines += ["## Result", "", "✅ No flaky tests detected across all runs.", ""]
        else:
            lines += ["## Flaky Test Details", ""]
            for m in flaky_tests:
                lines += self._format_test_section(m, recommendations.get(m.name, []))

        # Stable tests (brief)
        stable = [m for m in metrics if m.flakiness_score == "Stable"]
        if stable:
            lines += [
                "## Stable Tests",
                "",
                f"{len(stable)} test(s) showed no flakiness:",
                "",
            ]
            for m in stable:
                lines.append(f"- ✅ `{m.name}`")
            lines.append("")

        return "\n".join(lines)

    @staticmethod
    def _format_test_section(
        m: TestMetrics,
        recs: List[Recommendation],
    ) -> List[str]:
        icon = {"High": "🔴", "Medium": "🟠", "Low": "🟡"}.get(m.flakiness_score, "⚪")
        lines: List[str] = [
            f"### {icon} `{m.name}`",
            "",
            f"| Metric | Value |",
            f"|--------|-------|",
            f"| Suite | `{m.suite}` |",
            f"| Flakiness Score | **{m.flakiness_score}** |",
            f"| Failure Rate | {m.failure_rate_display} ({m.failure_rate:.0%}) |",
            f"| Duration Variance | {m.duration_variance:.1f} ms² |",
            f"| First Seen | {m.first_seen.date() if m.first_seen else 'N/A'} |",
            f"| Last Seen | {m.last_seen.date() if m.last_seen else 'N/A'} |",
            "",
        ]

        if m.failure_messages:
            lines += ["**Failure Messages:**", ""]
            for msg in m.failure_messages[:3]:  # Show up to 3 unique messages
                lines.append(f"> {msg[:200]}")
            lines.append("")

        if recs:
            lines += ["**Detected Patterns & Recommended Fixes:**", ""]
            for rec in recs:
                lines += [
                    f"#### {rec.pattern_name}",
                    "",
                    rec.description.strip(),
                    "",
                    rec.fix_template.strip(),
                    "",
                ]
        else:
            lines += [
                "**No specific pattern matched.** Review the failure messages manually.",
                "",
            ]

        lines.append("---")
        lines.append("")
        return lines

    # ------------------------------------------------------------------
    # Jira posting
    # ------------------------------------------------------------------

    def _post_to_jira(self, issue_key: str, report: str) -> None:
        client = self._jira or JiraClient()
        try:
            client.post_analysis_report(issue_key, report)
            logger.info("Analysis report posted to Jira issue %s", issue_key)
        except Exception as exc:
            logger.error("Failed to post report to Jira: %s", exc)

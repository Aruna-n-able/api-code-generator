"""
skill.py – AI-powered Flaky Test Analysis Skill (Anthropic Claude or OpenAI).

This module is the top-level orchestrator.  It wires together:
  1. RobotOutputParser  – parse output.xml artefacts
  2. MetricsEngine      – compute flakiness metrics across runs
  3. PatternDatabase    – match known flaky patterns
  4. Recommender        – generate code-level fix suggestions
  5. Claude AI          – produce a natural-language summary (optional)
  6. JiraClient         – fetch ticket / attachments and post the report

The skill can be used:
  a. Programmatically via the FlakyTestAnalysisSkill class.
  b. From the command line via run_flaky_analysis.py.
  c. As an MCP tool by exposing run_analysis() through an MCP server.

Two top-level entry points are provided:

* ``run_analysis(output_xml_paths, ...)``
    Classic mode – given local output.xml files, detect flaky tests and
    optionally post a summary to a Jira issue.

* ``analyze_ticket(jira_issue_key, ...)``
    Ticket-driven mode – given a Jira ticket ID, fetch the ticket and all
    attached files, analyse any Robot Framework output / log content, and
    use Claude to identify the root cause and recommend a fix.  The result
    is automatically posted back to the same Jira ticket.
"""

from __future__ import annotations

import io
import logging
import os
import tempfile
import zipfile
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

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

try:
    import openai as _openai
    _OPENAI_AVAILABLE = True
except ImportError:
    _OPENAI_AVAILABLE = False

# Ordered list of OpenAI models to try when the primary model is unavailable.
# gpt-4o-mini is widely accessible (including accounts with limited credits);
# gpt-3.5-turbo is the last-resort fallback for very restricted accounts.
_OPENAI_FALLBACK_MODELS: List[str] = ["gpt-4o-mini", "gpt-3.5-turbo"]

# Groq free-tier models in preference order.
# llama-3.3-70b-versatile offers the best quality on the free tier;
# llama-3.1-8b-instant is a lighter fallback when the 70B model is unavailable.
_GROQ_BASE_URL: str = "https://api.groq.com/openai/v1"
_GROQ_FALLBACK_MODELS: List[str] = ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"]

# Footer appended to every comment posted by this skill.
# Used to identify and skip our own previously-posted comments when building
# the AI prompt so the LLM does not treat a prior "AI unavailable" message as
# evidence of the actual root cause.
_SKILL_COMMENT_MARKER: str = "_Analysis generated automatically by the Flaky Test Analysis Skill._"


def _is_openai_model_not_found(exc: Exception) -> bool:
    """Return True when *exc* indicates the requested OpenAI model is unavailable."""
    msg = str(exc)
    status = getattr(exc, "status_code", None)
    return status == 404 or "model_not_found" in msg or "does not exist" in msg


def _build_model_list(primary: str) -> List[str]:
    """Return an ordered list of models to try, starting with *primary*.

    Fallbacks from ``_OPENAI_FALLBACK_MODELS`` are appended only when they
    differ from the primary model, so there are no duplicate attempts.
    """
    models = [primary]
    for fallback in _OPENAI_FALLBACK_MODELS:
        if fallback not in models:
            models.append(fallback)
    return models


def _handle_anthropic_error(exc: Exception) -> str:
    """Log a clear, actionable message for an Anthropic API error.

    Returns a short, user-facing description of the error suitable for
    inclusion in the formatted report.
    """
    msg = str(exc)
    status = getattr(exc, "status_code", None)
    if "credit balance is too low" in msg:
        logger.error(
            "Anthropic API error: your credit balance is too low.\n"
            "  → Top up your account at https://console.anthropic.com/settings/billing\n"
            "  → Or re-run with --no-ai to skip the AI step and still get the "
            "pattern-based analysis."
        )
        return "billing error – credit balance too low"
    elif status == 401 or "authentication" in msg.lower() or "api_key" in msg.lower():
        logger.error(
            "Anthropic API authentication failed – verify ANTHROPIC_API_KEY is correct.\n"
            "  → Re-run with --no-ai to skip the AI step."
        )
        return "authentication error – check ANTHROPIC_API_KEY"
    elif status == 404 or "model_not_found" in msg or "not_found_error" in msg:
        logger.error(
            "Anthropic API error: model '%s' was not found.\n"
            "  → Verify the model name is correct and available in your account.\n"
            "  → See https://docs.anthropic.com/en/docs/about-claude/models for valid IDs.\n"
            "  → Re-run with --no-ai to skip the AI step.",
            getattr(exc, "model", "unknown"),
        )
        return "model not found – check the model name"
    elif status is None:
        # Connection / timeout / other non-HTTP error
        logger.warning(
            "Claude API call failed (connection or timeout): %s\n"
            "  → Re-run with --no-ai to skip the AI step.",
            exc,
        )
        return "connection or timeout error"
    else:
        logger.warning(
            "Claude API error (HTTP %s): %s\n"
            "  → Re-run with --no-ai to skip the AI step.",
            status,
            exc,
        )
        return f"API error (HTTP {status})"


def _handle_openai_error(exc: Exception) -> str:
    """Log a clear, actionable message for an OpenAI API error.

    Returns a short, user-facing description of the error suitable for
    inclusion in the formatted report.
    """
    msg = str(exc)
    status = getattr(exc, "status_code", None)
    if "insufficient_quota" in msg or "exceeded your current quota" in msg:
        logger.error(
            "OpenAI API error: your quota has been exceeded.\n"
            "  → Check your usage at https://platform.openai.com/usage\n"
            "  → Or re-run with --no-ai to skip the AI step and still get the "
            "pattern-based analysis."
        )
        return "billing error – OpenAI quota exceeded"
    elif status == 401 or "authentication" in msg.lower() or "api_key" in msg.lower() or "Incorrect API key" in msg:
        logger.error(
            "OpenAI API authentication failed – verify OPENAI_API_KEY is correct.\n"
            "  → Re-run with --no-ai to skip the AI step."
        )
        return "authentication error – check OPENAI_API_KEY"
    elif _is_openai_model_not_found(exc):
        logger.error(
            "OpenAI API error: the requested model was not found.\n"
            "  → Verify the model name is correct and available in your account.\n"
            "  → See https://platform.openai.com/docs/models for valid IDs.\n"
            "  → Re-run with --no-ai to skip the AI step."
        )
        return "model not found – check the OpenAI model name"
    elif status is None:
        logger.warning(
            "OpenAI API call failed (connection or timeout): %s\n"
            "  → Re-run with --no-ai to skip the AI step.",
            exc,
        )
        return "connection or timeout error"
    else:
        logger.warning(
            "OpenAI API error (HTTP %s): %s\n"
            "  → Re-run with --no-ai to skip the AI step.",
            status,
            exc,
        )
        return f"API error (HTTP {status})"


def _build_groq_model_list(primary: str) -> List[str]:
    """Return an ordered list of Groq models to try, starting with *primary*.

    Fallbacks from ``_GROQ_FALLBACK_MODELS`` are appended only when they
    differ from the primary model, so there are no duplicate attempts.
    """
    models = [primary]
    for fallback in _GROQ_FALLBACK_MODELS:
        if fallback not in models:
            models.append(fallback)
    return models


def _handle_groq_error(exc: Exception) -> str:
    """Log a clear, actionable message for a Groq API error.

    Returns a short, user-facing description of the error suitable for
    inclusion in the formatted report.
    """
    msg = str(exc)
    status = getattr(exc, "status_code", None)
    if "rate_limit_exceeded" in msg or status == 429:
        logger.error(
            "Groq API error: rate limit exceeded.\n"
            "  → Wait a moment and retry, or check your usage at https://console.groq.com\n"
            "  → Or re-run with --no-ai to skip the AI step and still get the "
            "pattern-based analysis."
        )
        return "Groq rate limit exceeded"
    elif status == 401 or "authentication" in msg.lower() or "api_key" in msg.lower() or "invalid_api_key" in msg.lower():
        logger.error(
            "Groq API authentication failed – verify GROQ_API_KEY is correct.\n"
            "  → Get a free API key at https://console.groq.com\n"
            "  → Re-run with --no-ai to skip the AI step."
        )
        return "Groq authentication error – check GROQ_API_KEY"
    elif status == 404 or "model_not_found" in msg or "does not exist" in msg:
        logger.error(
            "Groq API error: the requested model was not found.\n"
            "  → See https://console.groq.com/docs/models for valid model IDs.\n"
            "  → Re-run with --no-ai to skip the AI step."
        )
        return "Groq model not found"
    elif status is None:
        logger.warning(
            "Groq API call failed (connection or timeout): %s\n"
            "  → Re-run with --no-ai to skip the AI step.",
            exc,
        )
        return "Groq connection or timeout error"
    else:
        logger.warning(
            "Groq API error (HTTP %s): %s\n"
            "  → Re-run with --no-ai to skip the AI step.",
            status,
            exc,
        )
        return f"Groq API error (HTTP {status})"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _HTMLTextExtractor(HTMLParser):
    """Minimal HTML-to-text converter used to strip Robot log.html files."""

    def __init__(self) -> None:
        super().__init__()
        self._parts: List[str] = []
        self._skip_tags = {"script", "style"}
        self._current_skip: Optional[str] = None

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        if tag in self._skip_tags:
            self._current_skip = tag

    def handle_endtag(self, tag: str) -> None:
        if tag == self._current_skip:
            self._current_skip = None

    def handle_data(self, data: str) -> None:
        if self._current_skip is None:
            stripped = data.strip()
            if stripped:
                self._parts.append(stripped)

    def get_text(self) -> str:
        return "\n".join(self._parts)


def _strip_html(raw: str) -> str:
    extractor = _HTMLTextExtractor()
    extractor.feed(raw)
    return extractor.get_text()


# ---------------------------------------------------------------------------
# Analysis result data models
# ---------------------------------------------------------------------------

@dataclass
class FlakyTestReport:
    """Full analysis output for a set of Robot Framework test runs."""

    runs: List[ParsedRun]
    metrics: List[TestMetrics]
    recommendations: Dict[str, List[Recommendation]]
    ai_summary: str = ""
    formatted_report: str = ""


@dataclass
class AttachmentInfo:
    """Metadata and extracted text for a single Jira attachment."""

    filename: str
    mime_type: str
    size: int
    text_content: str = ""
    is_robot_xml: bool = False
    is_zip_member: bool = False


@dataclass
class TicketAnalysisReport:
    """Result of the ticket-driven analysis mode."""

    issue_key: str
    summary: str
    status: str
    attachments: List[AttachmentInfo] = field(default_factory=list)
    robot_runs: List[ParsedRun] = field(default_factory=list)
    flaky_metrics: List[TestMetrics] = field(default_factory=list)
    recommendations: Dict[str, List[Recommendation]] = field(default_factory=dict)
    root_cause: str = ""
    recommended_solution: str = ""
    code_snippet: str = ""
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
        When not set, the skill tries OpenAI, then Groq as a free fallback.
    claude_model:
        Claude model to use for summarisation.
    openai_api_key:
        OpenAI API key.  Falls back to the ``OPENAI_API_KEY`` env var.
        Used as the AI provider when Anthropic is not configured or when it
        fails during a run.
    openai_model:
        OpenAI model to use (default: ``gpt-4o-mini``).
        If the requested model is not available on the account, the skill
        automatically retries with ``gpt-4o-mini`` and then ``gpt-3.5-turbo``.
    groq_api_key:
        Groq API key.  Falls back to the ``GROQ_API_KEY`` env var.
        Groq provides a **free tier** and is used as the last-resort AI
        fallback when both Anthropic and OpenAI are unavailable or fail.
        Obtain a free key at https://console.groq.com
    groq_model:
        Groq model to use (default: ``llama-3.3-70b-versatile``).
        Falls back to ``llama-3.1-8b-instant`` if the primary model is
        unavailable.
    patterns_file:
        Path to a custom ``flaky_patterns.yaml``; uses the bundled one by default.
    jira_client:
        A pre-configured :class:`JiraClient` instance.  If not supplied, one
        is created from environment variables when Jira posting is requested.
    """

    def __init__(
        self,
        anthropic_api_key: Optional[str] = None,
        claude_model: str = "claude-sonnet-4-6",
        openai_api_key: Optional[str] = None,
        openai_model: str = "gpt-4o-mini",
        groq_api_key: Optional[str] = None,
        groq_model: str = "llama-3.3-70b-versatile",
        patterns_file: Optional[str] = None,
        jira_client: Optional[JiraClient] = None,
    ) -> None:
        self._api_key = anthropic_api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self._model = claude_model
        self._openai_api_key = openai_api_key or os.environ.get("OPENAI_API_KEY", "")
        self._openai_model = openai_model
        self._groq_api_key = groq_api_key or os.environ.get("GROQ_API_KEY", "")
        self._groq_model = groq_model
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

    def _create_openai_client(self):
        """Return an OpenAI client configured for this skill instance.

        ``max_retries=0`` is set intentionally so that the SDK does not make
        additional attempts on HTTP errors.  The model fallback chain in
        ``_generate_ai_summary_openai`` and
        ``_generate_root_cause_analysis_openai`` already handles model-level
        retries (404), and for permanent errors such as quota exceeded (429)
        or authentication failures (401), retrying is wasteful.
        """
        return _openai.OpenAI(api_key=self._openai_api_key, max_retries=0)

    def _create_groq_client(self):
        """Return a Groq client configured for this skill instance.

        Groq exposes an OpenAI-compatible API, so the same ``openai`` package
        is reused with a custom ``base_url``.  ``max_retries=0`` prevents
        wasteful SDK-level retries for permanent errors (rate limits, bad key).
        """
        return _openai.OpenAI(
            api_key=self._groq_api_key,
            base_url=_GROQ_BASE_URL,
            max_retries=0,
        )

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
            Generate a natural-language summary using the configured AI provider
            (Anthropic Claude if ``ANTHROPIC_API_KEY`` is set, otherwise OpenAI
            if ``OPENAI_API_KEY`` is set).  When neither key is set the step is
            skipped and rule-based output is used instead.

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
        if use_ai_summary:
            if self._api_key and _ANTHROPIC_AVAILABLE:
                ai_summary = self._generate_ai_summary(metrics, recommendations)
            elif self._openai_api_key and _OPENAI_AVAILABLE:
                ai_summary = self._generate_ai_summary_openai(metrics, recommendations)

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

        try:
            client = _anthropic.Anthropic(api_key=self._api_key)
            message = client.messages.create(
                model=self._model,
                max_tokens=512,
                messages=[{"role": "user", "content": "\n".join(prompt_lines)}],
            )
            return message.content[0].text if message.content else ""
        except Exception as exc:
            _handle_anthropic_error(exc)
            return ""

    def _generate_ai_summary_openai(
        self,
        metrics: List[TestMetrics],
        recommendations: Dict[str, List[Recommendation]],
    ) -> str:
        """Call OpenAI to produce a concise executive summary."""
        if not _OPENAI_AVAILABLE:
            logger.warning(
                "openai package not installed; skipping AI summary. "
                "Install with: pip install openai"
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

        client = self._create_openai_client()
        prompt = "\n".join(prompt_lines)
        models_to_try = _build_model_list(self._openai_model)
        for model in models_to_try:
            try:
                response = client.chat.completions.create(
                    model=model,
                    max_tokens=512,
                    messages=[{"role": "user", "content": prompt}],
                )
                if model != self._openai_model:
                    logger.info("OpenAI: fell back to model '%s' for AI summary.", model)
                return response.choices[0].message.content or "" if response.choices else ""
            except Exception as exc:
                if _is_openai_model_not_found(exc) and model != models_to_try[-1]:
                    logger.warning(
                        "OpenAI model '%s' not found; trying next fallback…", model
                    )
                    continue
                _handle_openai_error(exc)
                return ""

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

    # ==================================================================
    # Ticket-driven analysis mode
    # ==================================================================

    def analyze_ticket(
        self,
        jira_issue_key: str,
        use_ai: bool = True,
        post_comment: bool = True,
    ) -> TicketAnalysisReport:
        """
        Analyse a Jira ticket end-to-end.

        Given only a Jira ticket ID this method will:

        1. Fetch the ticket metadata (summary, description, status, comments).
        2. Download every attachment from the ticket.
        3. Classify attachments – Robot ``output.xml`` files are parsed by the
           existing :class:`RobotOutputParser`; HTML and plain-text log files
           have their text extracted (HTML tags are stripped automatically).
        4. Feed all gathered context to the configured AI provider (Claude or
           OpenAI) and ask for a structured root-cause analysis and recommended
           fix.
        5. Optionally post the result back to the ticket as a comment.

        Parameters
        ----------
        jira_issue_key:
            The Jira issue key, e.g. ``NCCF-1593628``.
        use_ai:
            Use an AI model to generate the root-cause analysis.  Anthropic
            Claude is tried first (``ANTHROPIC_API_KEY``); OpenAI is used as a
            fallback when Anthropic is not configured or fails
            (``OPENAI_API_KEY``).  When *False*, or when neither key is set, a
            rule-based summary is produced instead.
        post_comment:
            If *True* and the AI analysis succeeds, post the formatted report
            back to the Jira ticket as a comment.

        Returns
        -------
        TicketAnalysisReport
        """
        client = self._jira or JiraClient()

        logger.info("Fetching Jira ticket %s…", jira_issue_key)
        issue = client.get_issue(jira_issue_key)

        logger.info(
            "Ticket: %s – %s [%s]",
            jira_issue_key,
            issue.get("summary", ""),
            issue.get("status", ""),
        )

        # ----------------------------------------------------------------
        # Download and classify attachments
        # ----------------------------------------------------------------
        raw_attachments = issue.get("attachments", [])
        logger.info("Found %d attachment(s)", len(raw_attachments))

        attachment_infos, robot_xml_paths = self._process_attachments(
            client, raw_attachments
        )

        # ----------------------------------------------------------------
        # Parse Robot Framework output.xml files (if any)
        # ----------------------------------------------------------------
        robot_runs: List[ParsedRun] = []
        flaky_metrics: List[TestMetrics] = []
        ticket_recommendations: Dict[str, List[Recommendation]] = {}
        if robot_xml_paths:
            logger.info(
                "Parsing %d Robot Framework output.xml file(s)…", len(robot_xml_paths)
            )
            robot_runs = self._parser.parse_files(robot_xml_paths)
            flaky_metrics = self._metrics_engine.compute(robot_runs)

            # Run pattern matching on all failed tests (regardless of flakiness
            # score so that single-run tickets still get recommendations).
            logger.info("Matching flaky patterns and generating recommendations…")
            all_failed: Dict[str, List[TestResult]] = {}
            for run in robot_runs:
                for t in run.tests:
                    if t.status == "FAIL":
                        all_failed.setdefault(t.name, []).append(t)
            for test_name, failed_results in all_failed.items():
                recs = self._recommender.recommend_for_failed(test_name, failed_results)
                if recs:
                    ticket_recommendations[test_name] = recs

        # ----------------------------------------------------------------
        # AI root-cause analysis
        # ----------------------------------------------------------------
        root_cause = ""
        recommended_solution = ""
        code_snippet = ""
        ai_error_hint = ""
        if use_ai:
            if self._api_key and _ANTHROPIC_AVAILABLE:
                root_cause, recommended_solution, code_snippet, ai_error_hint = self._generate_root_cause_analysis(
                    issue, attachment_infos, robot_runs, flaky_metrics
                )
            if not root_cause and self._openai_api_key and _OPENAI_AVAILABLE:
                # Use OpenAI if Anthropic is not configured or failed
                root_cause, recommended_solution, code_snippet, ai_error_hint = self._generate_root_cause_analysis_openai(
                    issue, attachment_infos, robot_runs, flaky_metrics
                )
            if not root_cause and self._groq_api_key and _OPENAI_AVAILABLE:
                # Use Groq (free tier) as the last-resort fallback
                root_cause, recommended_solution, code_snippet, ai_error_hint = self._generate_root_cause_analysis_groq(
                    issue, attachment_infos, robot_runs, flaky_metrics
                )

        # ----------------------------------------------------------------
        # Format report
        # ----------------------------------------------------------------
        any_ai_key_set = bool(self._api_key) or bool(self._openai_api_key) or bool(self._groq_api_key)
        formatted = self._format_ticket_report(
            issue,
            attachment_infos,
            robot_runs,
            flaky_metrics,
            root_cause,
            recommended_solution,
            code_snippet,
            use_ai=use_ai and not ai_error_hint,
            recommendations=ticket_recommendations,
            ai_key_set=any_ai_key_set,
            ai_error_hint=ai_error_hint,
        )

        report = TicketAnalysisReport(
            issue_key=jira_issue_key,
            summary=issue.get("summary", ""),
            status=issue.get("status", ""),
            attachments=attachment_infos,
            robot_runs=robot_runs,
            flaky_metrics=flaky_metrics,
            recommendations=ticket_recommendations,
            root_cause=root_cause,
            recommended_solution=recommended_solution,
            code_snippet=code_snippet,
            formatted_report=formatted,
        )

        if post_comment:
            self._post_to_jira(jira_issue_key, formatted)

        return report

    # ------------------------------------------------------------------
    # Attachment helpers
    # ------------------------------------------------------------------

    # Maximum characters extracted per attachment for the AI prompt.
    _MAX_ATTACHMENT_CHARS = 12_000

    def _process_attachments(
        self,
        client: JiraClient,
        raw_attachments: List[Dict[str, Any]],
    ) -> Tuple[List[AttachmentInfo], List[str]]:
        """
        Download every attachment and classify it.

        Returns
        -------
        attachment_infos:
            :class:`AttachmentInfo` objects with text content extracted.
        robot_xml_paths:
            Temporary file paths for Robot Framework ``output.xml`` files
            suitable for passing to :class:`RobotOutputParser`.
        """
        attachment_infos: List[AttachmentInfo] = []
        robot_xml_paths: List[str] = []

        for att in raw_attachments:
            filename: str = att.get("filename", "attachment")
            mime_type: str = att.get("mimeType", "")
            size: int = att.get("size", 0)

            logger.info("Downloading attachment: %s (%d bytes)", filename, size)

            try:
                raw_bytes = client.download_attachment(att)
            except Exception as exc:
                logger.warning("Could not download %s: %s", filename, exc)
                attachment_infos.append(
                    AttachmentInfo(
                        filename=filename,
                        mime_type=mime_type,
                        size=size,
                        text_content=f"[Download failed: {exc}]",
                    )
                )
                continue

            # ZIP archives – extract and process their contents
            if self._is_zip_archive(filename, raw_bytes):
                zip_infos, zip_xml_paths = self._extract_zip_attachment(
                    filename, mime_type, size, raw_bytes
                )
                attachment_infos.extend(zip_infos)
                robot_xml_paths.extend(zip_xml_paths)
                continue

            is_robot_xml = self._is_robot_output_xml(filename, raw_bytes)

            if is_robot_xml:
                # Write to a temp file so the existing parser can read it
                tmp = tempfile.NamedTemporaryFile(
                    suffix=".xml", delete=False, prefix=f"robot_{filename}_"
                )
                tmp.write(raw_bytes)
                tmp.close()
                robot_xml_paths.append(tmp.name)
                attachment_infos.append(
                    AttachmentInfo(
                        filename=filename,
                        mime_type=mime_type,
                        size=size,
                        text_content="[Robot Framework output.xml – parsed separately]",
                        is_robot_xml=True,
                    )
                )
            else:
                text = self._bytes_to_text(filename, mime_type, raw_bytes)
                attachment_infos.append(
                    AttachmentInfo(
                        filename=filename,
                        mime_type=mime_type,
                        size=size,
                        text_content=text[: self._MAX_ATTACHMENT_CHARS],
                    )
                )

        return attachment_infos, robot_xml_paths

    @staticmethod
    def _is_robot_output_xml(filename: str, raw_bytes: bytes) -> bool:
        """Return True if the file looks like a Robot Framework output.xml."""
        if not filename.lower().endswith(".xml"):
            return False
        # Peek at the first 512 bytes for the Robot signature
        header = raw_bytes[:512].decode("utf-8", errors="replace")
        return "<robot " in header or 'generator="Robot' in header

    @staticmethod
    def _is_zip_archive(filename: str, raw_bytes: bytes) -> bool:
        """Return True if the file is a ZIP archive."""
        return filename.lower().endswith(".zip") or raw_bytes[:4] == b"PK\x03\x04"

    def _extract_zip_attachment(
        self,
        zip_filename: str,
        zip_mime_type: str,
        zip_size: int,
        raw_bytes: bytes,
    ) -> Tuple[List[AttachmentInfo], List[str]]:
        """
        Extract a ZIP archive and process its contents like direct attachments.

        Robot Framework ``output.xml`` files found inside the archive are written
        to temporary files and returned in ``robot_xml_paths`` for parsing.
        Other files have their text extracted the same way as regular attachments.

        The ZIP archive itself is also recorded as an :class:`AttachmentInfo` so
        it appears in the formatted report.
        """
        attachment_infos: List[AttachmentInfo] = []
        robot_xml_paths: List[str] = []

        attachment_infos.append(
            AttachmentInfo(
                filename=zip_filename,
                mime_type=zip_mime_type,
                size=zip_size,
                text_content="[ZIP archive – contents extracted and analysed below]",
            )
        )

        try:
            with zipfile.ZipFile(io.BytesIO(raw_bytes)) as zf:
                for entry in zf.infolist():
                    if entry.is_dir():
                        continue
                    entry_name = Path(entry.filename).name
                    try:
                        entry_bytes = zf.read(entry.filename)
                    except Exception as exc:
                        logger.warning(
                            "Could not read %s from %s: %s",
                            entry.filename, zip_filename, exc,
                        )
                        continue

                    if self._is_robot_output_xml(entry_name, entry_bytes):
                        tmp = tempfile.NamedTemporaryFile(
                            suffix=".xml",
                            delete=False,
                            prefix=f"robot_{entry_name}_",
                        )
                        tmp.write(entry_bytes)
                        tmp.close()
                        robot_xml_paths.append(tmp.name)
                        attachment_infos.append(
                            AttachmentInfo(
                                filename=f"{zip_filename}/{entry.filename}",
                                mime_type="application/xml",
                                size=entry.file_size,
                                text_content=(
                                    "[Robot Framework output.xml – parsed separately]"
                                ),
                                is_robot_xml=True,
                                is_zip_member=True,
                            )
                        )
                    else:
                        text = self._bytes_to_text(entry_name, "", entry_bytes)
                        attachment_infos.append(
                            AttachmentInfo(
                                filename=f"{zip_filename}/{entry.filename}",
                                mime_type="",
                                size=entry.file_size,
                                text_content=text[: self._MAX_ATTACHMENT_CHARS],
                                is_zip_member=True,
                            )
                        )
        except zipfile.BadZipFile as exc:
            logger.warning("Could not open ZIP archive %s: %s", zip_filename, exc)

        return attachment_infos, robot_xml_paths

    @staticmethod
    def _bytes_to_text(filename: str, mime_type: str, raw_bytes: bytes) -> str:
        """Decode bytes to a plain-text string, stripping HTML when needed."""
        text = raw_bytes.decode("utf-8", errors="replace")
        lower_name = filename.lower()
        lower_mime = mime_type.lower()

        if "html" in lower_mime or lower_name.endswith((".html", ".htm")):
            return _strip_html(text)
        return text

    # ------------------------------------------------------------------
    # AI root-cause analysis
    # ------------------------------------------------------------------

    def _build_root_cause_prompt(
        self,
        issue: Dict[str, Any],
        attachments: List[AttachmentInfo],
        robot_runs: List[ParsedRun],
        flaky_metrics: List[TestMetrics],
    ) -> str:
        """Build the prompt used by both AI providers for root-cause analysis."""
        prompt_lines = [
            "",
            "A Jenkins build has failed and a Jira ticket has been created automatically.",
            "Your task is to:",
            "  1. Identify the **root cause** of the failure.",
            "  2. Provide a clear, actionable **recommended solution**.",
            "  3. Provide a **code snippet** implementing the fix.",
            "",
            "Respond with exactly three clearly labelled sections:",
            "  **Root Cause:** (2–5 sentences describing what went wrong and why)",
            "  **Recommended Solution:** (concrete steps or code changes to fix the issue)",
            "  **Code Snippet:** (a ready-to-use code example implementing the fix, using a "
            "fenced code block with the appropriate language tag such as ```python or "
            "```robot; write \"N/A\" if no code change is needed)",
            "",
            "## Jira Ticket",
            "",
            f"**Key:** {issue.get('key', 'N/A')}",
            f"**Status:** {issue.get('status', 'N/A')}",
            f"**Summary:** {issue.get('summary', 'N/A')}",
            "",
        ]

        description = (issue.get("description") or "").strip()
        if description:
            prompt_lines += [
                "**Description:**",
                "",
                description[:3000],
                "",
            ]

        # Exclude auto-generated comments posted by this skill itself so the LLM
        # does not mistake a previous "AI unavailable" message for the root cause.
        comments = [
            c for c in issue.get("comments", [])
            if _SKILL_COMMENT_MARKER not in c
        ]
        if comments:
            prompt_lines += ["**Recent Comments:**", ""]
            for comment in comments[-3:]:  # Last 3 comments
                prompt_lines.append(f"> {comment[:500]}")
            prompt_lines.append("")

        # Robot Framework parsed data
        if robot_runs:
            prompt_lines += ["## Robot Framework Test Results", ""]
            for run in robot_runs:
                failed = [t for t in run.tests if t.status == "FAIL"]
                prompt_lines.append(
                    f"**Run from `{Path(run.source_file).name}`:** "
                    f"{len(run.tests)} tests, {len(failed)} failed"
                )
                for t in failed[:10]:  # Up to 10 failed tests
                    prompt_lines.append(f"  - ❌ `{t.name}` ({t.suite})")
                    if t.message:
                        prompt_lines.append(f"    Error: {t.message[:300]}")
            prompt_lines.append("")

        if flaky_metrics:
            flaky = [m for m in flaky_metrics if m.flakiness_score != "Stable"]
            if flaky:
                prompt_lines += ["## Flaky Tests Detected (across multiple runs)", ""]
                for m in flaky:
                    prompt_lines.append(
                        f"- `{m.name}`: {m.flakiness_score} flakiness, "
                        f"failure rate {m.failure_rate_display}"
                    )
                prompt_lines.append("")

        # Log / attachment content
        log_attachments = [a for a in attachments if not a.is_robot_xml and a.text_content]
        if log_attachments:
            prompt_lines += ["## Attached Logs", ""]
            for att in log_attachments:
                prompt_lines += [
                    f"### `{att.filename}`",
                    "",
                    att.text_content[:self._MAX_ATTACHMENT_CHARS],
                    "",
                ]

        return "\n".join(prompt_lines)

    def _generate_root_cause_analysis(
        self,
        issue: Dict[str, Any],
        attachments: List[AttachmentInfo],
        robot_runs: List[ParsedRun],
        flaky_metrics: List[TestMetrics],
    ) -> Tuple[str, str, str, str]:
        """
        Ask Claude to identify the root cause and recommend a fix.

        Returns a tuple of (root_cause, recommended_solution, code_snippet, error_hint) strings.
        error_hint is non-empty only when the API call failed; it is a short,
        user-facing description of what went wrong.
        """
        if not _ANTHROPIC_AVAILABLE:
            logger.warning(
                "anthropic package not installed; skipping AI analysis. "
                "Install with: pip install anthropic"
            )
            return "", "", "", ""

        prompt = self._build_root_cause_prompt(issue, attachments, robot_runs, flaky_metrics)

        try:
            client = _anthropic.Anthropic(api_key=self._api_key)
            message = client.messages.create(
                model=self._model,
                max_tokens=2048,
                messages=[{"role": "user", "content": prompt}],
            )

            full_response = message.content[0].text if message.content else ""
        except Exception as exc:
            error_hint = _handle_anthropic_error(exc)
            return "", "", "", error_hint

        # Split the response into root cause / solution / code snippet sections
        root_cause, recommended_solution, code_snippet = self._parse_ai_response(full_response)
        return root_cause, recommended_solution, code_snippet, ""

    def _generate_root_cause_analysis_openai(
        self,
        issue: Dict[str, Any],
        attachments: List[AttachmentInfo],
        robot_runs: List[ParsedRun],
        flaky_metrics: List[TestMetrics],
    ) -> Tuple[str, str, str, str]:
        """
        Ask OpenAI to identify the root cause and recommend a fix.

        Returns a tuple of (root_cause, recommended_solution, code_snippet, error_hint) strings.
        error_hint is non-empty only when the API call failed; it is a short,
        user-facing description of what went wrong.
        """
        if not _OPENAI_AVAILABLE:
            logger.warning(
                "openai package not installed; skipping AI analysis. "
                "Install with: pip install openai"
            )
            return "", "", "", ""

        prompt = self._build_root_cause_prompt(issue, attachments, robot_runs, flaky_metrics)

        client = self._create_openai_client()
        models_to_try = _build_model_list(self._openai_model)
        for model in models_to_try:
            try:
                response = client.chat.completions.create(
                    model=model,
                    max_tokens=2048,
                    messages=[{"role": "user", "content": prompt}],
                )
                if model != self._openai_model:
                    logger.info(
                        "OpenAI: fell back to model '%s' for root-cause analysis.", model
                    )
                full_response = (
                    response.choices[0].message.content or ""
                    if response.choices
                    else ""
                )
                root_cause, recommended_solution, code_snippet = self._parse_ai_response(full_response)
                return root_cause, recommended_solution, code_snippet, ""
            except Exception as exc:
                if _is_openai_model_not_found(exc) and model != models_to_try[-1]:
                    logger.warning(
                        "OpenAI model '%s' not found; trying next fallback…", model
                    )
                    continue
                error_hint = _handle_openai_error(exc)
                return "", "", "", error_hint

    def _generate_root_cause_analysis_groq(
        self,
        issue: Dict[str, Any],
        attachments: List[AttachmentInfo],
        robot_runs: List[ParsedRun],
        flaky_metrics: List[TestMetrics],
    ) -> Tuple[str, str, str, str]:
        """
        Ask Groq (free LLM tier) to identify the root cause and recommend a fix.

        Groq provides a free API tier backed by open-source models such as
        Llama 3.3 70B.  It is used as the last-resort AI fallback when both
        Anthropic and OpenAI are unavailable or have exceeded their quotas.

        Returns a tuple of (root_cause, recommended_solution, code_snippet, error_hint).
        error_hint is non-empty only when the API call failed.
        """
        if not _OPENAI_AVAILABLE:
            logger.warning(
                "openai package not installed; Groq integration requires it. "
                "Install with: pip install openai"
            )
            return "", "", "", ""

        prompt = self._build_root_cause_prompt(issue, attachments, robot_runs, flaky_metrics)

        client = self._create_groq_client()
        models_to_try = _build_groq_model_list(self._groq_model)
        for model in models_to_try:
            try:
                response = client.chat.completions.create(
                    model=model,
                    max_tokens=2048,
                    messages=[{"role": "user", "content": prompt}],
                )
                if model != self._groq_model:
                    logger.info(
                        "Groq: fell back to model '%s' for root-cause analysis.", model
                    )
                full_response = (
                    response.choices[0].message.content or ""
                    if response.choices
                    else ""
                )
                root_cause, recommended_solution, code_snippet = self._parse_ai_response(full_response)
                return root_cause, recommended_solution, code_snippet, ""
            except Exception as exc:
                if (
                    (getattr(exc, "status_code", None) == 404 or "model_not_found" in str(exc))
                    and model != models_to_try[-1]
                ):
                    logger.warning(
                        "Groq model '%s' not found; trying next fallback…", model
                    )
                    continue
                error_hint = _handle_groq_error(exc)
                return "", "", "", error_hint

    @staticmethod
    def _parse_ai_response(response: str) -> Tuple[str, str, str]:
        """Extract root cause, recommended solution, and code snippet from the AI response.

        Returns a ``(root_cause, recommended_solution, code_snippet)`` 3-tuple.
        ``code_snippet`` is the empty string when the AI returned "N/A" or did not
        include a ``Code Snippet:`` section.
        """
        root_cause = ""
        recommended_solution = ""
        code_snippet = ""

        # Look for the three labelled sections (case-insensitive)
        import re

        rc_match = re.search(
            r"\*{0,2}Root Cause:?\*{0,2}\s*(.*?)"
            r"(?=\*{0,2}Recommended Solution:?|\*{0,2}Code Snippet:?|\Z)",
            response,
            re.IGNORECASE | re.DOTALL,
        )
        sol_match = re.search(
            r"\*{0,2}Recommended Solution:?\*{0,2}\s*(.*?)"
            r"(?=\*{0,2}Code Snippet:?|\Z)",
            response,
            re.IGNORECASE | re.DOTALL,
        )
        snippet_match = re.search(
            r"\*{0,2}Code Snippet:?\*{0,2}\s*(.*)",
            response,
            re.IGNORECASE | re.DOTALL,
        )

        if rc_match:
            root_cause = rc_match.group(1).strip()
        if sol_match:
            recommended_solution = sol_match.group(1).strip()
        if snippet_match:
            snippet_text = snippet_match.group(1).strip()
            if snippet_text.upper() not in ("N/A", "NONE", ""):
                code_snippet = snippet_text

        # Fallback: if the model didn't use the expected labels, return the full text
        if not root_cause and not recommended_solution:
            root_cause = response.strip()

        return root_cause, recommended_solution, code_snippet

    # ------------------------------------------------------------------
    # Ticket report formatting
    # ------------------------------------------------------------------

    def _format_ticket_report(
        self,
        issue: Dict[str, Any],
        attachments: List[AttachmentInfo],
        robot_runs: List[ParsedRun],
        flaky_metrics: List[TestMetrics],
        root_cause: str,
        recommended_solution: str,
        code_snippet: str = "",
        use_ai: bool = True,
        recommendations: Optional[Dict[str, List[Recommendation]]] = None,
        ai_key_set: bool = False,
        ai_error_hint: str = "",
    ) -> str:
        if recommendations is None:
            recommendations = {}

        lines: List[str] = [
            f"# Root Cause Analysis – {issue.get('key', 'N/A')}",
            "",
            f"**Summary:** {issue.get('summary', '')}  ",
            f"**Status:** {issue.get('status', '')}  ",
            f"**Attachments analysed:** {len(attachments)}  ",
            "",
        ]

        # Attachments inventory
        if attachments:
            lines += ["## Attachments Found", ""]
            # Count how many files were extracted from each ZIP so the parent
            # line can show a summary instead of listing every member filename.
            zip_member_counts: Dict[str, int] = {}
            for att in attachments:
                if att.is_zip_member:
                    parent = att.filename.split("/", 1)[0]
                    zip_member_counts[parent] = zip_member_counts.get(parent, 0) + 1
            for att in attachments:
                if att.is_zip_member:
                    continue  # shown as part of the parent ZIP line
                member_count = zip_member_counts.get(att.filename)
                if member_count is not None:
                    icon = "📦"
                    suffix = f" – unzipped, {member_count} file(s) found"
                elif att.is_robot_xml:
                    icon = "🤖"
                    suffix = ""
                else:
                    icon = "📄"
                    suffix = ""
                lines.append(
                    f"- {icon} `{att.filename}` ({att.mime_type or 'unknown'}, "
                    f"{att.size:,} bytes){suffix}"
                )
            lines.append("")

        # Robot test results
        if robot_runs:
            lines += ["## Robot Framework Test Results", ""]
            for run in robot_runs:
                failed = [t for t in run.tests if t.status == "FAIL"]
                passed = [t for t in run.tests if t.status == "PASS"]
                lines += [
                    f"**Run:** `{Path(run.source_file).name}`  ",
                    f"**Passed:** {len(passed)} | **Failed:** {len(failed)}",
                    "",
                ]
                if failed:
                    lines.append("| Test | Suite | Error |")
                    lines.append("|------|-------|-------|")
                    for t in failed[:20]:
                        msg = (t.message or "")[:120].replace("\n", " ")
                        lines.append(f"| `{t.name}` | `{t.suite}` | {msg} |")
                    lines.append("")

        # Flaky test summary
        flaky = [m for m in flaky_metrics if m.flakiness_score != "Stable"]
        if flaky:
            lines += ["## Flaky Tests Detected", ""]
            for m in flaky:
                icon = {"High": "🔴", "Medium": "🟠", "Low": "🟡"}.get(
                    m.flakiness_score, "⚪"
                )
                lines.append(
                    f"- {icon} `{m.name}` — **{m.flakiness_score}** "
                    f"({m.failure_rate_display})"
                )
            lines.append("")

        # Pattern-based recommendations for failed tests
        if recommendations:
            lines += ["## Detected Patterns & Recommendations", ""]
            for test_name, recs in recommendations.items():
                lines += [f"### `{test_name}`", ""]
                for rec in recs:
                    lines += [
                        f"#### {rec.pattern_name}",
                        "",
                        rec.description.strip(),
                        "",
                        rec.fix_template.strip(),
                        "",
                    ]

        # Root cause
        if root_cause:
            lines += ["## 🔍 Root Cause", "", root_cause, ""]
        elif not use_ai:
            has_patterns = bool(recommendations)
            has_robot_results = bool(robot_runs)
            if has_patterns and has_robot_results:
                suffix = "See Robot Framework test results and detected patterns above."
            elif has_robot_results:
                suffix = "See Robot Framework test results above."
            elif has_patterns:
                suffix = "See detected patterns above."
            else:
                suffix = "No Robot Framework test results were found in the ticket attachments."
            if ai_error_hint:
                intro = f"_AI analysis unavailable ({ai_error_hint})."
            else:
                intro = "_AI analysis skipped (`--no-ai`)."
            lines += [
                "## 🔍 Root Cause",
                "",
                f"{intro} {suffix}_",
                "",
            ]
        else:
            if ai_key_set:
                if ai_error_hint:
                    failure_msg = (
                        f"_AI analysis failed ({ai_error_hint}). "
                        "Re-run with `--no-ai` to skip the AI step._"
                    )
                else:
                    failure_msg = (
                        "_AI analysis failed. Check the logs for details "
                        "(e.g. invalid model or API error). "
                        "Re-run with `--no-ai` to skip the AI step._"
                    )
                lines += ["## 🔍 Root Cause", "", failure_msg, ""]
            else:
                lines += [
                    "## 🔍 Root Cause",
                    "",
                    "_AI analysis not available. Set `ANTHROPIC_API_KEY` to enable._",
                    "",
                ]

        # Recommended solution
        if recommended_solution:
            lines += ["## ✅ Recommended Solution", "", recommended_solution, ""]
        elif root_cause:
            lines += ["## ✅ Recommended Solution", "", "_See root cause above._", ""]

        # Code snippet
        snippet = (code_snippet or "").strip()
        if snippet and snippet.upper() not in ("N/A", "NONE"):
            lines += ["## 💻 Code Snippet", "", snippet, ""]

        lines += [
            "---",
            _SKILL_COMMENT_MARKER,
        ]
        return "\n".join(lines)

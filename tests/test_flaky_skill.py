"""
Unit tests for the Flaky Test Analysis Skill.

Run with:
    pytest tests/test_flaky_skill.py -v
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------

FIXTURE_DIR = Path(__file__).parent / "fixtures"
SAMPLE_RUN1 = FIXTURE_DIR / "sample_output.xml"
SAMPLE_RUN2 = FIXTURE_DIR / "sample_output_run2.xml"


# ===========================================================================
# RobotOutputParser
# ===========================================================================

class TestRobotOutputParser:
    def setup_method(self):
        from skills.flaky_test_analysis.robot_parser import RobotOutputParser
        self.parser = RobotOutputParser()

    def test_parse_file_returns_parsed_run(self):
        run = self.parser.parse_file(SAMPLE_RUN1)
        assert run.source_file == str(SAMPLE_RUN1)
        assert len(run.tests) > 0

    def test_parse_file_extracts_test_names(self):
        run = self.parser.parse_file(SAMPLE_RUN1)
        names = {t.name for t in run.tests}
        assert "test_user_session_timeout" in names
        assert "test_login_with_valid_credentials" in names

    def test_parse_file_records_status(self):
        run = self.parser.parse_file(SAMPLE_RUN1)
        by_name = {t.name: t for t in run.tests}
        assert by_name["test_user_session_timeout"].status == "FAIL"
        assert by_name["test_login_with_valid_credentials"].status == "PASS"

    def test_parse_file_records_failure_message(self):
        run = self.parser.parse_file(SAMPLE_RUN1)
        timeout_test = next(
            t for t in run.tests if t.name == "test_user_session_timeout"
        )
        # The fixture message explicitly contains "AssertionError" and "datetime.now()"
        assert "AssertionError" in timeout_test.message
        assert "datetime.now()" in timeout_test.message

    def test_parse_file_records_elapsed_ms(self):
        run = self.parser.parse_file(SAMPLE_RUN1)
        for test in run.tests:
            assert test.elapsed_ms >= 0

    def test_parse_file_records_tags(self):
        run = self.parser.parse_file(SAMPLE_RUN1)
        db_test = next(
            t for t in run.tests if t.name == "test_user_registration_unique_email"
        )
        assert "database" in db_test.tags

    def test_parse_files_returns_multiple_runs(self):
        runs = self.parser.parse_files([SAMPLE_RUN1, SAMPLE_RUN2])
        assert len(runs) == 2

    def test_parse_file_missing_raises(self):
        with pytest.raises(Exception):
            self.parser.parse_file("/nonexistent/path/output.xml")


# ===========================================================================
# PatternDatabase
# ===========================================================================

class TestPatternDatabase:
    def setup_method(self):
        from skills.flaky_test_analysis.pattern_db import PatternDatabase
        self.db = PatternDatabase()

    def test_loads_patterns(self):
        assert len(self.db.all_patterns) >= 5

    def test_get_pattern_by_id(self):
        pattern = self.db.get_pattern("datetime_timing")
        assert pattern is not None
        assert pattern.name == "Datetime / Timing Issue"

    def test_get_nonexistent_pattern_returns_none(self):
        assert self.db.get_pattern("nonexistent_id") is None

    def test_match_datetime_pattern(self):
        from skills.flaky_test_analysis.robot_parser import TestResult
        test = TestResult(
            name="test_user_session_timeout",
            suite="Auth Suite",
            status="FAIL",
            message="AssertionError: Session expected to be expired. datetime.now() returned unexpected value.",
            start_time=None,
            end_time=None,
            elapsed_ms=1000,
        )
        matches = self.db.match(test)
        pattern_ids = {p.id for p in matches}
        assert "datetime_timing" in pattern_ids

    def test_match_database_pattern(self):
        from skills.flaky_test_analysis.robot_parser import TestResult
        test = TestResult(
            name="test_user_registration",
            suite="DB Suite",
            status="FAIL",
            message="IntegrityError: duplicate key value violates unique constraint",
            start_time=None,
            end_time=None,
            elapsed_ms=500,
        )
        matches = self.db.match(test)
        pattern_ids = {p.id for p in matches}
        assert "database_state" in pattern_ids

    def test_match_external_api_pattern(self):
        from skills.flaky_test_analysis.robot_parser import TestResult
        test = TestResult(
            name="test_send_email",
            suite="API Suite",
            status="FAIL",
            message="ConnectionError: HTTPSConnectionPool max retries exceeded sendgrid",
            start_time=None,
            end_time=None,
            elapsed_ms=5000,
        )
        matches = self.db.match(test)
        pattern_ids = {p.id for p in matches}
        assert "unmocked_external_api" in pattern_ids

    def test_no_match_for_passing_test_with_no_signals(self):
        from skills.flaky_test_analysis.robot_parser import TestResult
        test = TestResult(
            name="test_simple_addition",
            suite="Math Suite",
            status="FAIL",
            message="AssertionError: 2 + 2 expected 4 got 5",
            start_time=None,
            end_time=None,
            elapsed_ms=10,
        )
        matches = self.db.match(test)
        # Should not match any specific pattern
        assert isinstance(matches, list)


# ===========================================================================
# MetricsEngine
# ===========================================================================

class TestMetricsEngine:
    def setup_method(self):
        from skills.flaky_test_analysis.metrics import MetricsEngine
        from skills.flaky_test_analysis.robot_parser import RobotOutputParser
        self.engine = MetricsEngine()
        parser = RobotOutputParser()
        self.runs = parser.parse_files([SAMPLE_RUN1, SAMPLE_RUN2])

    def test_compute_returns_metrics_for_all_tests(self):
        metrics = self.engine.compute(self.runs)
        assert len(metrics) > 0

    def test_flaky_test_detected(self):
        metrics = self.engine.compute(self.runs)
        by_name = {m.name: m for m in metrics}
        # test_user_session_timeout fails in run1 (FAIL) and passes in run2 (PASS)
        # → 1 failure in 2 runs = 50% failure rate → "High"
        m = by_name.get("test_user_session_timeout")
        assert m is not None
        assert m.flakiness_score == "High"

    def test_stable_test_not_flaky(self):
        metrics = self.engine.compute(self.runs)
        by_name = {m.name: m for m in metrics}
        # test_login_with_valid_credentials always passes
        m = by_name.get("test_login_with_valid_credentials")
        assert m is not None
        assert m.flakiness_score == "Stable"

    def test_failure_rate_calculation(self):
        metrics = self.engine.compute(self.runs)
        by_name = {m.name: m for m in metrics}
        m = by_name["test_user_session_timeout"]
        # Fails in 1 of 2 runs → 50%
        assert m.failure_count == 1
        assert m.total_runs == 2
        assert abs(m.failure_rate - 0.5) < 0.01

    def test_metrics_sorted_by_severity(self):
        metrics = self.engine.compute(self.runs)
        non_stable = [m for m in metrics if m.flakiness_score != "Stable"]
        order = {"High": 0, "Medium": 1, "Low": 2}
        for i in range(len(non_stable) - 1):
            assert order.get(non_stable[i].flakiness_score, 3) <= order.get(
                non_stable[i + 1].flakiness_score, 3
            )

    def test_failure_rate_display_format(self):
        metrics = self.engine.compute(self.runs)
        for m in metrics:
            assert "/" in m.failure_rate_display


# ===========================================================================
# Recommender
# ===========================================================================

class TestRecommender:
    def setup_method(self):
        from skills.flaky_test_analysis.metrics import MetricsEngine
        from skills.flaky_test_analysis.recommender import Recommender
        from skills.flaky_test_analysis.robot_parser import RobotOutputParser
        self.recommender = Recommender()
        parser = RobotOutputParser()
        self.runs = parser.parse_files([SAMPLE_RUN1, SAMPLE_RUN2])
        self.engine = MetricsEngine()
        self.metrics = self.engine.compute(self.runs)

    def _build_all_results(self):
        from skills.flaky_test_analysis.robot_parser import RobotOutputParser
        parser = RobotOutputParser()
        all_results = {}
        for run in self.runs:
            for t in run.tests:
                all_results.setdefault(t.name, []).append(t)
        return all_results

    def test_recommend_all_returns_dict(self):
        all_results = self._build_all_results()
        recs = self.recommender.recommend_all(self.metrics, all_results)
        assert isinstance(recs, dict)

    def test_no_recommendation_for_stable_tests(self):
        all_results = self._build_all_results()
        recs = self.recommender.recommend_all(self.metrics, all_results)
        # Stable tests should not be in the recommendations dict
        stable = {m.name for m in self.metrics if m.flakiness_score == "Stable"}
        for name in stable:
            assert name not in recs

    def test_recommendation_has_required_fields(self):
        all_results = self._build_all_results()
        recs = self.recommender.recommend_all(self.metrics, all_results)
        for test_name, rec_list in recs.items():
            for rec in rec_list:
                assert rec.test_name == test_name
                assert rec.pattern_id
                assert rec.pattern_name
                assert rec.fix_template

    def test_datetime_pattern_recommendation(self):
        all_results = self._build_all_results()
        recs = self.recommender.recommend_all(self.metrics, all_results)
        timeout_recs = recs.get("test_user_session_timeout", [])
        pattern_ids = {r.pattern_id for r in timeout_recs}
        assert "datetime_timing" in pattern_ids

    def test_recommend_for_failed_returns_recs_for_single_run_failed_test(self):
        """recommend_for_failed matches patterns even when there is only 1 run (no flakiness)."""
        from skills.flaky_test_analysis.robot_parser import RobotOutputParser
        parser = RobotOutputParser()
        single_run = parser.parse_files([SAMPLE_RUN1])  # single run → all tests are "Stable"
        # Collect the failed test results
        failed_by_name = {}
        for run in single_run:
            for t in run.tests:
                if t.status == "FAIL":
                    failed_by_name.setdefault(t.name, []).append(t)

        # The datetime failing test should still get a recommendation
        timeout_results = failed_by_name.get("test_user_session_timeout", [])
        recs = self.recommender.recommend_for_failed("test_user_session_timeout", timeout_results)
        assert len(recs) > 0
        pattern_ids = {r.pattern_id for r in recs}
        assert "datetime_timing" in pattern_ids

    def test_recommend_for_failed_returns_empty_for_passing_test(self):
        """recommend_for_failed returns [] when all provided results are passing."""
        from skills.flaky_test_analysis.robot_parser import RobotOutputParser
        parser = RobotOutputParser()
        single_run = parser.parse_files([SAMPLE_RUN1])
        passing = [t for run in single_run for t in run.tests if t.status == "PASS"]
        recs = self.recommender.recommend_for_failed("test_login_with_valid_credentials", passing)
        assert recs == []


# ===========================================================================
# FlakyTestAnalysisSkill (integration, no AI)
# ===========================================================================

class TestFlakyTestAnalysisSkill:
    def setup_method(self):
        from skills.flaky_test_analysis import FlakyTestAnalysisSkill
        self.skill = FlakyTestAnalysisSkill()

    def test_default_model_is_current(self):
        """The default Claude model must be a currently-available model ID."""
        from skills.flaky_test_analysis import FlakyTestAnalysisSkill
        skill = FlakyTestAnalysisSkill()
        # Must not reference the deprecated claude-3-5-sonnet-20241022 model
        assert "claude-3-5-sonnet-20241022" not in skill._model
        # Must be one of the known current model IDs
        assert "claude-sonnet-4-5" in skill._model or "claude-sonnet-4" in skill._model

    def test_run_analysis_returns_report(self):
        report = self.skill.run_analysis(
            [SAMPLE_RUN1, SAMPLE_RUN2],
            use_ai_summary=False,
        )
        assert report is not None
        assert len(report.metrics) > 0

    def test_formatted_report_is_markdown(self):
        report = self.skill.run_analysis(
            [SAMPLE_RUN1, SAMPLE_RUN2],
            use_ai_summary=False,
        )
        assert "# Flaky Test Analysis Report" in report.formatted_report

    def test_flaky_tests_appear_in_report(self):
        report = self.skill.run_analysis(
            [SAMPLE_RUN1, SAMPLE_RUN2],
            use_ai_summary=False,
        )
        assert "test_user_session_timeout" in report.formatted_report

    def test_single_run_marks_no_flakiness(self):
        """A single run cannot demonstrate flakiness; all tests should be Stable."""
        report = self.skill.run_analysis(
            [SAMPLE_RUN1],
            use_ai_summary=False,
        )
        # With only one run there are no passing counterparts for failing tests,
        # so no test has mixed results → all are Stable.
        flaky = [m for m in report.metrics if m.flakiness_score != "Stable"]
        assert len(flaky) == 0

    def test_jira_posting_is_called_when_key_provided(self):
        from skills.flaky_test_analysis import FlakyTestAnalysisSkill
        mock_jira = MagicMock()
        skill = FlakyTestAnalysisSkill(jira_client=mock_jira)
        skill.run_analysis(
            [SAMPLE_RUN1, SAMPLE_RUN2],
            jira_issue_key="TEST-1",
            use_ai_summary=False,
        )
        mock_jira.post_analysis_report.assert_called_once()

    def test_no_jira_call_without_issue_key(self):
        from skills.flaky_test_analysis import FlakyTestAnalysisSkill
        mock_jira = MagicMock()
        skill = FlakyTestAnalysisSkill(jira_client=mock_jira)
        skill.run_analysis(
            [SAMPLE_RUN1, SAMPLE_RUN2],
            jira_issue_key=None,
            use_ai_summary=False,
        )
        mock_jira.post_analysis_report.assert_not_called()

    def test_ai_summary_skipped_without_api_key(self):
        """When ANTHROPIC_API_KEY is not set, ai_summary should be empty string."""
        with patch.dict("os.environ", {}, clear=True):
            from skills.flaky_test_analysis import FlakyTestAnalysisSkill
            skill = FlakyTestAnalysisSkill(anthropic_api_key="")
            report = skill.run_analysis(
                [SAMPLE_RUN1, SAMPLE_RUN2],
                use_ai_summary=True,
            )
            assert report.ai_summary == ""


# ===========================================================================
# JiraClient
# ===========================================================================

class TestJiraClient:
    def test_mcp_mode_returns_stub(self):
        from skills.flaky_test_analysis.jira_client import JiraClient
        client = JiraClient(auth_mode="mcp")
        result = client.post_comment("TEST-1", "Hello")
        assert result["status"] == "stub"
        assert result["issue_key"] == "TEST-1"

    def test_rest_mode_raises_without_config(self):
        from skills.flaky_test_analysis.jira_client import JiraClient
        client = JiraClient(auth_mode="rest", base_url="", user_email="", api_token="")
        with pytest.raises(RuntimeError, match="Missing Jira configuration"):
            client.post_comment("TEST-1", "Hello")

    def test_rest_mode_posts_comment(self):
        from skills.flaky_test_analysis.jira_client import JiraClient
        client = JiraClient(
            base_url="https://example.atlassian.net",
            user_email="user@example.com",
            api_token="fake-token",
            auth_mode="rest",
        )
        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.json.return_value = {"id": "12345", "body": "Hello"}
        mock_response.raise_for_status = MagicMock()

        with patch("skills.flaky_test_analysis.jira_client._requests") as mock_req:
            mock_req.post.return_value = mock_response
            result = client.post_comment("TEST-1", "Hello")

        mock_req.post.assert_called_once()
        assert result["id"] == "12345"


# ===========================================================================
# JiraClient – read operations (get_issue, list_attachments, download)
# ===========================================================================

class TestJiraClientRead:
    """Tests for the new read-side methods added to JiraClient."""

    def _make_client(self):
        from skills.flaky_test_analysis.jira_client import JiraClient
        return JiraClient(
            base_url="https://example.atlassian.net",
            user_email="user@example.com",
            api_token="fake-token",
            auth_mode="rest",
        )

    def _mock_response(self, json_data, status_code=200):
        mock_resp = MagicMock()
        mock_resp.status_code = status_code
        mock_resp.json.return_value = json_data
        mock_resp.raise_for_status = MagicMock()
        return mock_resp

    def test_get_issue_returns_normalised_dict(self):
        client = self._make_client()
        api_payload = {
            "key": "NCCF-1",
            "fields": {
                "summary": "Build failed",
                "description": "Some description",
                "status": {"name": "Open"},
                "attachment": [
                    {
                        "id": "10001",
                        "filename": "output.xml",
                        "mimeType": "application/xml",
                        "size": 1024,
                        "content": "https://example.atlassian.net/secure/attachment/10001/output.xml",
                    }
                ],
                "comment": {
                    "comments": [
                        {"body": "First comment"},
                        {"body": "Second comment"},
                    ]
                },
            },
        }
        with patch("skills.flaky_test_analysis.jira_client._requests") as mock_req:
            mock_req.get.return_value = self._mock_response(api_payload)
            issue = client.get_issue("NCCF-1")

        assert issue["key"] == "NCCF-1"
        assert issue["summary"] == "Build failed"
        assert issue["status"] == "Open"
        assert len(issue["attachments"]) == 1
        assert issue["attachments"][0]["filename"] == "output.xml"
        assert issue["comments"] == ["First comment", "Second comment"]

    def test_get_issue_handles_missing_fields_gracefully(self):
        client = self._make_client()
        # Minimal API response – some fields absent
        api_payload = {"key": "NCCF-2", "fields": {}}
        with patch("skills.flaky_test_analysis.jira_client._requests") as mock_req:
            mock_req.get.return_value = self._mock_response(api_payload)
            issue = client.get_issue("NCCF-2")

        assert issue["summary"] == ""
        assert issue["description"] == ""
        assert issue["status"] == ""
        assert issue["attachments"] == []
        assert issue["comments"] == []

    def test_list_attachments_returns_list(self):
        client = self._make_client()
        api_payload = {
            "key": "NCCF-3",
            "fields": {
                "attachment": [
                    {"id": "1", "filename": "log.html", "mimeType": "text/html", "size": 512,
                     "content": "https://example.atlassian.net/secure/attachment/1/log.html"},
                    {"id": "2", "filename": "output.xml", "mimeType": "application/xml",
                     "size": 256, "content": "https://example.atlassian.net/secure/attachment/2/output.xml"},
                ],
                "comment": {"comments": []},
            },
        }
        with patch("skills.flaky_test_analysis.jira_client._requests") as mock_req:
            mock_req.get.return_value = self._mock_response(api_payload)
            attachments = client.list_attachments("NCCF-3")

        assert len(attachments) == 2
        filenames = {a["filename"] for a in attachments}
        assert filenames == {"log.html", "output.xml"}

    def test_download_attachment_returns_bytes(self):
        client = self._make_client()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b"<robot generator='Robot'>...</robot>"
        mock_resp.raise_for_status = MagicMock()

        attachment = {
            "filename": "output.xml",
            "content": "https://example.atlassian.net/secure/attachment/1/output.xml",
        }

        with patch("skills.flaky_test_analysis.jira_client._requests") as mock_req:
            mock_req.get.return_value = mock_resp
            data = client.download_attachment(attachment)

        assert isinstance(data, bytes)
        assert b"robot" in data

    def test_download_attachment_raises_without_content_url(self):
        from skills.flaky_test_analysis.jira_client import JiraClient
        client = JiraClient(
            base_url="https://example.atlassian.net",
            user_email="user@example.com",
            api_token="fake-token",
        )
        with pytest.raises(RuntimeError, match="no content URL"):
            client.download_attachment({"filename": "empty.txt", "content": ""})

    def test_get_issue_raises_on_http_error(self):
        client = self._make_client()
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_resp.text = "Not Found"
        mock_resp.raise_for_status.side_effect = Exception("404")

        with patch("skills.flaky_test_analysis.jira_client._requests") as mock_req:
            mock_req.get.return_value = mock_resp
            with pytest.raises(RuntimeError, match="Jira API error"):
                client.get_issue("NCCF-999")


# ===========================================================================
# FlakyTestAnalysisSkill – analyze_ticket()
# ===========================================================================

SAMPLE_OUTPUT_XML = (Path(__file__).parent / "fixtures" / "sample_output.xml").read_bytes()


def _make_jira_mock(
    summary="Build failed on login suite",
    status="Open",
    description="Jenkins build #42 failed.\n\nSee attached log.",
    attachments=None,
    comments=None,
):
    """Return a mock JiraClient configured for ticket-driven tests."""
    mock_client = MagicMock()
    mock_client.get_issue.return_value = {
        "key": "NCCF-1",
        "summary": summary,
        "status": status,
        "description": description,
        "attachments": attachments or [],
        "comments": comments or [],
    }
    mock_client.list_attachments.return_value = attachments or []
    mock_client.download_attachment.return_value = b"plain text log content: ERROR timeout"
    mock_client.post_analysis_report.return_value = {"id": "99"}
    return mock_client


class TestAnalyzeTicket:
    def setup_method(self):
        from skills.flaky_test_analysis import FlakyTestAnalysisSkill
        self.skill = FlakyTestAnalysisSkill

    def test_analyze_ticket_returns_ticket_report(self):
        from skills.flaky_test_analysis import FlakyTestAnalysisSkill, TicketAnalysisReport
        mock_jira = _make_jira_mock()
        skill = FlakyTestAnalysisSkill(jira_client=mock_jira)
        report = skill.analyze_ticket("NCCF-1", use_ai=False, post_comment=False)
        assert isinstance(report, TicketAnalysisReport)
        assert report.issue_key == "NCCF-1"
        assert report.summary == "Build failed on login suite"

    def test_analyze_ticket_posts_comment_by_default(self):
        from skills.flaky_test_analysis import FlakyTestAnalysisSkill
        mock_jira = _make_jira_mock()
        skill = FlakyTestAnalysisSkill(jira_client=mock_jira)
        skill.analyze_ticket("NCCF-1", use_ai=False, post_comment=True)
        mock_jira.post_analysis_report.assert_called_once_with("NCCF-1", mock_jira.post_analysis_report.call_args[0][1])

    def test_analyze_ticket_skips_post_when_no_post(self):
        from skills.flaky_test_analysis import FlakyTestAnalysisSkill
        mock_jira = _make_jira_mock()
        skill = FlakyTestAnalysisSkill(jira_client=mock_jira)
        skill.analyze_ticket("NCCF-1", use_ai=False, post_comment=False)
        mock_jira.post_analysis_report.assert_not_called()

    def test_analyze_ticket_with_text_attachment(self):
        from skills.flaky_test_analysis import FlakyTestAnalysisSkill
        attachments = [
            {
                "id": "1",
                "filename": "build.log",
                "mimeType": "text/plain",
                "size": 100,
                "content": "https://example.atlassian.net/secure/attachment/1/build.log",
            }
        ]
        mock_jira = _make_jira_mock(attachments=attachments)
        mock_jira.download_attachment.return_value = b"ERROR: test_login FAILED\nTimeout after 30s"
        skill = FlakyTestAnalysisSkill(jira_client=mock_jira)
        report = skill.analyze_ticket("NCCF-1", use_ai=False, post_comment=False)
        assert len(report.attachments) == 1
        assert report.attachments[0].filename == "build.log"
        assert "ERROR" in report.attachments[0].text_content

    def test_analyze_ticket_with_html_attachment(self):
        from skills.flaky_test_analysis import FlakyTestAnalysisSkill
        attachments = [
            {
                "id": "2",
                "filename": "log.html",
                "mimeType": "text/html",
                "size": 200,
                "content": "https://example.atlassian.net/secure/attachment/2/log.html",
            }
        ]
        mock_jira = _make_jira_mock(attachments=attachments)
        html_content = b"<html><body><h1>Log</h1><p>Test failed</p><script>var x=1;</script></body></html>"
        mock_jira.download_attachment.return_value = html_content
        skill = FlakyTestAnalysisSkill(jira_client=mock_jira)
        report = skill.analyze_ticket("NCCF-1", use_ai=False, post_comment=False)
        text = report.attachments[0].text_content
        # HTML tags and script content should be stripped
        assert "<html>" not in text
        assert "var x=1" not in text
        assert "Test failed" in text

    def test_analyze_ticket_with_robot_xml_attachment(self):
        from skills.flaky_test_analysis import FlakyTestAnalysisSkill
        attachments = [
            {
                "id": "3",
                "filename": "output.xml",
                "mimeType": "application/xml",
                "size": len(SAMPLE_OUTPUT_XML),
                "content": "https://example.atlassian.net/secure/attachment/3/output.xml",
            }
        ]
        mock_jira = _make_jira_mock(attachments=attachments)
        mock_jira.download_attachment.return_value = SAMPLE_OUTPUT_XML
        skill = FlakyTestAnalysisSkill(jira_client=mock_jira)
        report = skill.analyze_ticket("NCCF-1", use_ai=False, post_comment=False)
        # The robot xml should be classified as a robot xml attachment
        assert any(a.is_robot_xml for a in report.attachments)
        # And robot runs should be parsed
        assert len(report.robot_runs) >= 1

    def test_analyze_ticket_formatted_report_contains_key(self):
        from skills.flaky_test_analysis import FlakyTestAnalysisSkill
        mock_jira = _make_jira_mock()
        skill = FlakyTestAnalysisSkill(jira_client=mock_jira)
        report = skill.analyze_ticket("NCCF-1", use_ai=False, post_comment=False)
        assert "NCCF-1" in report.formatted_report

    def test_analyze_ticket_formatted_report_contains_root_cause_section(self):
        from skills.flaky_test_analysis import FlakyTestAnalysisSkill
        mock_jira = _make_jira_mock()
        skill = FlakyTestAnalysisSkill(jira_client=mock_jira)
        report = skill.analyze_ticket("NCCF-1", use_ai=False, post_comment=False)
        assert "Root Cause" in report.formatted_report

    def test_analyze_ticket_ai_skipped_without_api_key(self):
        from skills.flaky_test_analysis import FlakyTestAnalysisSkill
        with patch.dict("os.environ", {}, clear=True):
            mock_jira = _make_jira_mock()
            skill = FlakyTestAnalysisSkill(anthropic_api_key="", jira_client=mock_jira)
            report = skill.analyze_ticket("NCCF-1", use_ai=True, post_comment=False)
            # No API key → root_cause stays empty
            assert report.root_cause == ""
            # Report should tell user to set the key
            assert "Set `ANTHROPIC_API_KEY`" in report.formatted_report

    def test_analyze_ticket_ai_failure_shows_check_logs_message(self):
        """When the key IS set but the AI call fails, show the error cause not 'set key'."""
        from skills.flaky_test_analysis import FlakyTestAnalysisSkill
        mock_jira = _make_jira_mock()

        with patch("skills.flaky_test_analysis.skill._ANTHROPIC_AVAILABLE", True), \
             patch("skills.flaky_test_analysis.skill._anthropic", create=True) as mock_ant:
            # Simulate any API error (e.g. model not found, billing, etc.)
            mock_ant.APIStatusError = Exception
            mock_ant.Anthropic.return_value.messages.create.side_effect = Exception("model_not_found")
            skill = FlakyTestAnalysisSkill(anthropic_api_key="sk-test", jira_client=mock_jira)
            report = skill.analyze_ticket("NCCF-1", use_ai=True, post_comment=False)

        # root_cause empty because the call failed
        assert report.root_cause == ""
        # Should NOT tell user to set the key (it is set)
        assert "Set `ANTHROPIC_API_KEY`" not in report.formatted_report
        # Should describe the specific failure cause in the report, with graceful fallback wording
        assert "AI analysis unavailable" in report.formatted_report
        assert "model not found" in report.formatted_report

    def test_analyze_ticket_ai_calls_claude_when_key_set(self):
        from skills.flaky_test_analysis import FlakyTestAnalysisSkill
        mock_jira = _make_jira_mock()
        mock_message = MagicMock()
        mock_message.content = [MagicMock(text="**Root Cause:** Timeout. **Recommended Solution:** Add retry.")]

        with patch("skills.flaky_test_analysis.skill._ANTHROPIC_AVAILABLE", True), \
             patch("skills.flaky_test_analysis.skill._anthropic", create=True) as mock_ant:
            mock_ant.Anthropic.return_value.messages.create.return_value = mock_message
            skill = FlakyTestAnalysisSkill(anthropic_api_key="sk-test", jira_client=mock_jira)
            report = skill.analyze_ticket("NCCF-1", use_ai=True, post_comment=False)

        assert "Timeout" in report.root_cause or "Timeout" in report.recommended_solution

    def test_parse_ai_response_extracts_sections(self):
        from skills.flaky_test_analysis.skill import FlakyTestAnalysisSkill
        response = (
            "**Root Cause:** The test relies on a real system clock.\n\n"
            "**Recommended Solution:** Use freezegun to freeze time in tests."
        )
        rc, sol, al, snippet = FlakyTestAnalysisSkill._parse_ai_response(response)
        assert "real system clock" in rc
        assert "freezegun" in sol

    def test_parse_ai_response_fallback_when_no_labels(self):
        from skills.flaky_test_analysis.skill import FlakyTestAnalysisSkill
        response = "The test is broken because of a timing issue."
        rc, sol, al, snippet = FlakyTestAnalysisSkill._parse_ai_response(response)
        # Fallback: everything goes into root_cause
        assert "timing issue" in rc
        assert sol == ""

    def test_analyze_ticket_with_zip_containing_robot_xml(self):
        """A ZIP attachment containing a Robot output.xml is extracted and parsed."""
        import io
        import zipfile
        from skills.flaky_test_analysis import FlakyTestAnalysisSkill

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("output.xml", SAMPLE_OUTPUT_XML)
        zip_bytes = buf.getvalue()

        attachments = [
            {
                "id": "5",
                "filename": "test_results.zip",
                "mimeType": "application/zip",
                "size": len(zip_bytes),
                "content": "https://example.atlassian.net/secure/attachment/5/test_results.zip",
            }
        ]
        mock_jira = _make_jira_mock(attachments=attachments)
        mock_jira.download_attachment.return_value = zip_bytes
        skill = FlakyTestAnalysisSkill(jira_client=mock_jira)
        report = skill.analyze_ticket("NCCF-1", use_ai=False, post_comment=False)

        # The zip archive itself should appear in attachment infos
        assert any("test_results.zip" in a.filename for a in report.attachments)
        # The Robot XML entry extracted from the zip should be classified correctly
        assert any(a.is_robot_xml for a in report.attachments)
        # Robot runs must have been parsed from the extracted XML
        assert len(report.robot_runs) >= 1

    def test_analyze_ticket_with_zip_containing_text_files(self):
        """Text files inside a ZIP attachment are extracted and their content captured."""
        import io
        import zipfile
        from skills.flaky_test_analysis import FlakyTestAnalysisSkill

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("build.log", "ERROR: test_login FAILED\nTimeout after 30s")
        zip_bytes = buf.getvalue()

        attachments = [
            {
                "id": "6",
                "filename": "logs.zip",
                "mimeType": "application/zip",
                "size": len(zip_bytes),
                "content": "https://example.atlassian.net/secure/attachment/6/logs.zip",
            }
        ]
        mock_jira = _make_jira_mock(attachments=attachments)
        mock_jira.download_attachment.return_value = zip_bytes
        skill = FlakyTestAnalysisSkill(jira_client=mock_jira)
        report = skill.analyze_ticket("NCCF-1", use_ai=False, post_comment=False)

        # The extracted log entry should carry its text content
        log_entries = [a for a in report.attachments if "build.log" in a.filename]
        assert log_entries, "Expected an AttachmentInfo for build.log extracted from zip"
        assert "ERROR" in log_entries[0].text_content

    def test_analyze_ticket_no_ai_fallback_message(self):
        """With use_ai=False and no robot runs the report says AI was skipped, not missing."""
        from skills.flaky_test_analysis import FlakyTestAnalysisSkill
        mock_jira = _make_jira_mock()
        skill = FlakyTestAnalysisSkill(jira_client=mock_jira)
        report = skill.analyze_ticket("NCCF-1", use_ai=False, post_comment=False)
        # Should mention --no-ai, not tell user to set ANTHROPIC_API_KEY
        assert "--no-ai" in report.formatted_report
        assert "Set `ANTHROPIC_API_KEY`" not in report.formatted_report

    def test_analyze_ticket_pattern_matching_runs_on_single_run_failed_tests(self):
        """Pattern matching runs on failed tests even with a single robot XML (no flakiness)."""
        from skills.flaky_test_analysis import FlakyTestAnalysisSkill
        attachments = [
            {
                "id": "7",
                "filename": "output.xml",
                "mimeType": "application/xml",
                "size": len(SAMPLE_OUTPUT_XML),
                "content": "https://example.atlassian.net/secure/attachment/7/output.xml",
            }
        ]
        mock_jira = _make_jira_mock(attachments=attachments)
        mock_jira.download_attachment.return_value = SAMPLE_OUTPUT_XML
        skill = FlakyTestAnalysisSkill(jira_client=mock_jira)
        report = skill.analyze_ticket("NCCF-1", use_ai=False, post_comment=False)
        # The single-run XML has tests failing with "datetime.now()" and "ConnectionError" etc.
        assert len(report.recommendations) > 0
        # The datetime_timing pattern should be found for the timing test
        timeout_recs = report.recommendations.get("test_user_session_timeout", [])
        assert any(r.pattern_id == "datetime_timing" for r in timeout_recs)

    def test_analyze_ticket_report_shows_detected_patterns_section(self):
        """The formatted report includes a 'Detected Patterns' section when patterns are found."""
        from skills.flaky_test_analysis import FlakyTestAnalysisSkill
        attachments = [
            {
                "id": "8",
                "filename": "output.xml",
                "mimeType": "application/xml",
                "size": len(SAMPLE_OUTPUT_XML),
                "content": "https://example.atlassian.net/secure/attachment/8/output.xml",
            }
        ]
        mock_jira = _make_jira_mock(attachments=attachments)
        mock_jira.download_attachment.return_value = SAMPLE_OUTPUT_XML
        skill = FlakyTestAnalysisSkill(jira_client=mock_jira)
        report = skill.analyze_ticket("NCCF-1", use_ai=False, post_comment=False)
        assert "Detected Patterns" in report.formatted_report

    def test_analyze_ticket_no_ai_fallback_mentions_patterns_when_present(self):
        """The --no-ai fallback message mentions 'detected patterns' when patterns were found."""
        from skills.flaky_test_analysis import FlakyTestAnalysisSkill
        attachments = [
            {
                "id": "9",
                "filename": "output.xml",
                "mimeType": "application/xml",
                "size": len(SAMPLE_OUTPUT_XML),
                "content": "https://example.atlassian.net/secure/attachment/9/output.xml",
            }
        ]
        mock_jira = _make_jira_mock(attachments=attachments)
        mock_jira.download_attachment.return_value = SAMPLE_OUTPUT_XML
        skill = FlakyTestAnalysisSkill(jira_client=mock_jira)
        report = skill.analyze_ticket("NCCF-1", use_ai=False, post_comment=False)
        # When patterns are present the fallback should reference them
        assert "detected patterns" in report.formatted_report

    def test_analyze_ticket_no_ai_fallback_omits_patterns_when_none_found(self):
        """The --no-ai fallback message does NOT mention patterns when none were matched."""
        from skills.flaky_test_analysis import FlakyTestAnalysisSkill
        # Use a plain text attachment (no Robot XML) so no patterns can match
        mock_jira = _make_jira_mock()  # no attachments → no robot runs → no patterns
        skill = FlakyTestAnalysisSkill(jira_client=mock_jira)
        report = skill.analyze_ticket("NCCF-1", use_ai=False, post_comment=False)
        assert "detected patterns" not in report.formatted_report

    def test_no_attachment_ai_error_shows_no_results_found_message(self):
        """When AI fails AND there are no attachments the Root Cause message says
        'No Robot Framework test results were found' rather than 'See … above.'"""
        from skills.flaky_test_analysis import FlakyTestAnalysisSkill
        import skills.flaky_test_analysis.skill as skill_module

        quota_exc = Exception("You exceeded your current quota, please check your plan.")
        quota_exc.status_code = 429

        fake_openai = MagicMock()
        fake_openai.OpenAI.return_value.chat.completions.create.side_effect = quota_exc

        # No API key for Anthropic → OpenAI path; no attachments on the ticket
        mock_jira = _make_jira_mock()  # 0 attachments
        skill = FlakyTestAnalysisSkill(
            openai_api_key="sk-test",
            jira_client=mock_jira,
        )

        with patch.object(skill_module, "_openai", fake_openai, create=True), \
             patch.object(skill_module, "_OPENAI_AVAILABLE", True):
            report = skill.analyze_ticket("NCCF-1", use_ai=True, post_comment=False)

        assert "No Robot Framework test results were found" in report.formatted_report
        assert "See Robot Framework test results above" not in report.formatted_report

    def test_no_attachment_no_ai_shows_no_results_found_message(self):
        """When --no-ai is used AND there are no attachments the Root Cause message says
        'No Robot Framework test results were found' rather than 'See … above.'"""
        from skills.flaky_test_analysis import FlakyTestAnalysisSkill
        mock_jira = _make_jira_mock()  # 0 attachments
        skill = FlakyTestAnalysisSkill(jira_client=mock_jira)
        report = skill.analyze_ticket("NCCF-1", use_ai=False, post_comment=False)
        assert "No Robot Framework test results were found" in report.formatted_report
        assert "See Robot Framework test results above" not in report.formatted_report

    def test_openai_client_created_with_max_retries_zero(self):
        """_create_openai_client() passes max_retries=0 to the OpenAI constructor
        so that the SDK does not make extra attempts for permanent errors
        (quota exceeded, auth failure, model not found)."""
        from skills.flaky_test_analysis import FlakyTestAnalysisSkill
        import skills.flaky_test_analysis.skill as skill_module

        captured_kwargs: list = []

        class FakeClient:
            def __init__(self, **kwargs):
                captured_kwargs.append(kwargs)

        fake_openai = MagicMock()
        fake_openai.OpenAI.side_effect = FakeClient

        skill = FlakyTestAnalysisSkill(openai_api_key="sk-test")
        with patch.object(skill_module, "_openai", fake_openai, create=True):
            skill._create_openai_client()

        assert captured_kwargs, "OpenAI() constructor should have been called"
        assert captured_kwargs[0].get("max_retries") == 0, (
            "_create_openai_client must pass max_retries=0 to OpenAI() to prevent "
            "wasteful retry delays for permanent errors"
        )

    def test_is_zip_archive_detects_by_extension(self):
        from skills.flaky_test_analysis.skill import FlakyTestAnalysisSkill
        assert FlakyTestAnalysisSkill._is_zip_archive("archive.zip", b"anything") is True
        assert FlakyTestAnalysisSkill._is_zip_archive("output.xml", b"anything") is False

    def test_is_zip_archive_detects_by_magic_bytes(self):
        from skills.flaky_test_analysis.skill import FlakyTestAnalysisSkill
        zip_magic = b"PK\x03\x04" + b"\x00" * 10
        assert FlakyTestAnalysisSkill._is_zip_archive("noextension", zip_magic) is True
        assert FlakyTestAnalysisSkill._is_zip_archive("noextension", b"not a zip") is False

    def test_zip_attachment_formatted_report_shows_summary_not_member_names(self):
        """The formatted report should show ZIP as one line with a file count,
        not expand every extracted filename in the Attachments Found section."""
        import io
        import zipfile
        from skills.flaky_test_analysis import FlakyTestAnalysisSkill

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("build.log", "ERROR: timeout")
            zf.writestr("report.html", "<html>ok</html>")
        zip_bytes = buf.getvalue()

        attachments = [
            {
                "id": "10",
                "filename": "results.zip",
                "mimeType": "application/zip",
                "size": len(zip_bytes),
                "content": "https://example.atlassian.net/secure/attachment/10/results.zip",
            }
        ]
        mock_jira = _make_jira_mock(attachments=attachments)
        mock_jira.download_attachment.return_value = zip_bytes
        skill = FlakyTestAnalysisSkill(jira_client=mock_jira)
        report = skill.analyze_ticket("NCCF-1", use_ai=False, post_comment=False)

        # The ZIP itself should appear with a file count
        assert "results.zip" in report.formatted_report
        assert "unzipped" in report.formatted_report
        assert "2 file(s) found" in report.formatted_report
        # Individual member names must NOT appear in the formatted report's attachments section
        assert "build.log" not in report.formatted_report
        assert "report.html" not in report.formatted_report
        # The raw AttachmentInfo objects for members are still available for AI/pattern analysis
        assert any("build.log" in a.filename for a in report.attachments)


# ===========================================================================
# CLI – --jira-ticket argument
# ===========================================================================

class TestCLIJiraTicketMode:
    _FAKE_JIRA_ENV = {
        "JIRA_BASE_URL": "https://example.atlassian.net",
        "JIRA_USER_EMAIL": "ci@example.com",
        "JIRA_API_TOKEN": "fake-token",
    }

    def test_jira_ticket_mode_calls_analyze_ticket(self):
        from run_flaky_analysis import main
        mock_report = MagicMock()
        mock_report.formatted_report = "# Root Cause Analysis\nDone."
        mock_report.flaky_metrics = []

        with patch.dict("os.environ", self._FAKE_JIRA_ENV), \
             patch("run_flaky_analysis.FlakyTestAnalysisSkill") as MockSkill:
            MockSkill.return_value.analyze_ticket.return_value = mock_report
            with pytest.raises(SystemExit) as exc_info:
                main(["--jira-ticket", "NCCF-1", "--no-ai", "--no-post"])
            assert exc_info.value.code == 0
            MockSkill.return_value.analyze_ticket.assert_called_once_with(
                jira_issue_key="NCCF-1",
                use_ai=False,
                post_comment=False,
            )

    def test_both_modes_mutually_exclusive(self):
        from run_flaky_analysis import main
        with pytest.raises(SystemExit) as exc_info:
            main(["--jira-ticket", "NCCF-1", "--robot-output", "file.xml"])
        assert exc_info.value.code == 1

    def test_no_mode_exits_with_error(self):
        from run_flaky_analysis import main
        with pytest.raises(SystemExit) as exc_info:
            main([])
        assert exc_info.value.code != 0

    def test_missing_jira_env_exits_with_friendly_message(self, capsys):
        from run_flaky_analysis import main
        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(SystemExit) as exc_info:
                main(["--jira-ticket", "NCCF-1"])
        assert exc_info.value.code == 1
        err = capsys.readouterr().err
        assert "JIRA_BASE_URL" in err
        assert "JIRA_USER_EMAIL" in err
        assert "JIRA_API_TOKEN" in err
        # Should not be a raw traceback
        assert "Traceback" not in err

    def test_partial_jira_env_lists_only_missing_vars(self, capsys):
        from run_flaky_analysis import main
        with patch.dict("os.environ", {"JIRA_BASE_URL": "https://example.atlassian.net"}, clear=True):
            with pytest.raises(SystemExit) as exc_info:
                main(["--jira-ticket", "NCCF-1"])
        assert exc_info.value.code == 1
        err = capsys.readouterr().err
        # The two missing vars should be listed under "not set:"
        assert "JIRA_USER_EMAIL" in err
        assert "JIRA_API_TOKEN" in err
        # JIRA_BASE_URL should NOT appear in the "not set" bullet list
        # (it may still appear in the static example section)
        not_set_block = err.split("Set them and re-run")[0]
        assert "JIRA_BASE_URL" not in not_set_block

    def test_runtime_error_from_analyze_ticket_is_handled_gracefully(self, capsys):
        from run_flaky_analysis import main
        with patch.dict("os.environ", self._FAKE_JIRA_ENV), \
             patch("run_flaky_analysis.FlakyTestAnalysisSkill") as MockSkill:
            MockSkill.return_value.analyze_ticket.side_effect = RuntimeError("Connection refused")
            with pytest.raises(SystemExit) as exc_info:
                main(["--jira-ticket", "NCCF-1", "--no-ai", "--no-post"])
        assert exc_info.value.code == 1
        err = capsys.readouterr().err
        assert "Connection refused" in err
        assert "Traceback" not in err

    def test_unexpected_error_shows_no_ai_tip(self, capsys):
        """Generic exceptions from analyze_ticket should suggest --no-ai."""
        from run_flaky_analysis import main
        with patch.dict("os.environ", self._FAKE_JIRA_ENV), \
             patch("run_flaky_analysis.FlakyTestAnalysisSkill") as MockSkill:
            MockSkill.return_value.analyze_ticket.side_effect = Exception("boom")
            with pytest.raises(SystemExit) as exc_info:
                main(["--jira-ticket", "NCCF-1", "--no-post"])
        assert exc_info.value.code == 1
        err = capsys.readouterr().err
        assert "--no-ai" in err


# ===========================================================================
# Anthropic API error handling
# ===========================================================================

class TestAnthropicErrorHandling:
    """_generate_ai_summary and _generate_root_cause_analysis must handle
    Anthropic API errors gracefully instead of propagating them to callers."""

    def _make_api_status_error(self, status_code: int, message: str):
        """Build a minimal fake that quacks like anthropic.APIStatusError."""
        exc = Exception(f"Error code: {status_code} - {message}")
        exc.status_code = status_code
        return exc

    def test_ai_summary_returns_empty_string_on_billing_error(self, caplog):
        """A 400 credit-balance error must be caught; the method returns ''."""
        from skills.flaky_test_analysis import FlakyTestAnalysisSkill
        import skills.flaky_test_analysis.skill as skill_module

        billing_exc = self._make_api_status_error(
            400,
            "Your credit balance is too low to access the Anthropic API."
        )

        # Simulate anthropic being available with a fake module object
        fake_anthropic = MagicMock()
        fake_anthropic.APIStatusError = type(billing_exc)
        fake_anthropic.Anthropic.return_value.messages.create.side_effect = billing_exc

        skill = FlakyTestAnalysisSkill(anthropic_api_key="fake-key")

        with patch.object(skill_module, "_anthropic", fake_anthropic, create=True), \
             patch.object(skill_module, "_ANTHROPIC_AVAILABLE", True):
            from skills.flaky_test_analysis.metrics import TestMetrics
            metric = MagicMock(spec=TestMetrics)
            metric.flakiness_score = "High"
            metric.name = "test_foo"
            metric.failure_rate_display = "50%"

            result = skill._generate_ai_summary([metric], {})

        assert result == ""

    def test_root_cause_returns_empty_tuple_on_billing_error(self, caplog):
        """A 400 credit-balance error in _generate_root_cause_analysis must be
        caught and return ('', '', <error_hint>)."""
        from skills.flaky_test_analysis import FlakyTestAnalysisSkill
        import skills.flaky_test_analysis.skill as skill_module

        billing_exc = self._make_api_status_error(
            400,
            "Your credit balance is too low to access the Anthropic API."
        )

        fake_anthropic = MagicMock()
        fake_anthropic.APIStatusError = type(billing_exc)
        fake_anthropic.Anthropic.return_value.messages.create.side_effect = billing_exc

        skill = FlakyTestAnalysisSkill(anthropic_api_key="fake-key")

        with patch.object(skill_module, "_anthropic", fake_anthropic, create=True), \
             patch.object(skill_module, "_ANTHROPIC_AVAILABLE", True):
            result = skill._generate_root_cause_analysis(
                issue={"key": "X-1", "status": "Open", "summary": "Test"},
                attachments=[],
                robot_runs=[],
                flaky_metrics=[],
            )

        assert result[:2] == ("", "")
        root_cause, recommended_solution, affected_line, code_snippet, error_hint = result
        assert error_hint  # billing error hint must be non-empty

    def test_auth_error_returns_empty_string(self, caplog):
        """A 401 authentication error must also be handled gracefully."""
        from skills.flaky_test_analysis import FlakyTestAnalysisSkill
        import skills.flaky_test_analysis.skill as skill_module

        auth_exc = self._make_api_status_error(401, "Invalid API key")

        fake_anthropic = MagicMock()
        fake_anthropic.APIStatusError = type(auth_exc)
        fake_anthropic.Anthropic.return_value.messages.create.side_effect = auth_exc

        skill = FlakyTestAnalysisSkill(anthropic_api_key="bad-key")

        with patch.object(skill_module, "_anthropic", fake_anthropic, create=True), \
             patch.object(skill_module, "_ANTHROPIC_AVAILABLE", True):
            result = skill._generate_root_cause_analysis(
                issue={"key": "X-1", "status": "Open", "summary": "Test"},
                attachments=[],
                robot_runs=[],
                flaky_metrics=[],
            )

        assert result[:2] == ("", "")
        root_cause, recommended_solution, affected_line, code_snippet, error_hint = result
        assert error_hint  # auth error hint must be non-empty

    def test_connection_error_returns_empty_tuple(self, caplog):
        """A non-HTTP error (connection / timeout) must also be caught gracefully."""
        from skills.flaky_test_analysis import FlakyTestAnalysisSkill
        import skills.flaky_test_analysis.skill as skill_module

        conn_exc = ConnectionError("Failed to establish a connection")

        fake_anthropic = MagicMock()
        fake_anthropic.Anthropic.return_value.messages.create.side_effect = conn_exc

        skill = FlakyTestAnalysisSkill(anthropic_api_key="fake-key")

        with patch.object(skill_module, "_anthropic", fake_anthropic, create=True), \
             patch.object(skill_module, "_ANTHROPIC_AVAILABLE", True):
            result = skill._generate_root_cause_analysis(
                issue={"key": "X-1", "status": "Open", "summary": "Test"},
                attachments=[],
                robot_runs=[],
                flaky_metrics=[],
            )

        assert result[:2] == ("", "")
        root_cause, recommended_solution, affected_line, code_snippet, error_hint = result
        assert error_hint  # connection error hint must be non-empty

    def test_ai_not_called_when_anthropic_unavailable(self):
        """When _ANTHROPIC_AVAILABLE is False, AI functions must not be called."""
        from skills.flaky_test_analysis import FlakyTestAnalysisSkill
        import skills.flaky_test_analysis.skill as skill_module

        mock_jira = MagicMock()
        mock_jira.get_issue.return_value = {
            "key": "X-1", "summary": "S", "status": "Open",
            "description": "", "attachments": [], "comments": [],
        }
        mock_jira.list_attachments.return_value = []

        skill = FlakyTestAnalysisSkill(anthropic_api_key="sk-real-key", jira_client=mock_jira)

        with patch.object(skill_module, "_ANTHROPIC_AVAILABLE", False), \
             patch.object(skill, "_generate_root_cause_analysis", wraps=skill._generate_root_cause_analysis) as spy:
            report = skill.analyze_ticket("X-1", use_ai=True, post_comment=False)

        # _ANTHROPIC_AVAILABLE is False → the AI function must NOT have been called
        spy.assert_not_called()
        assert report.root_cause == ""


# ===========================================================================
# OpenAI support
# ===========================================================================

class TestOpenAISupport:
    """Tests covering OpenAI as an alternative AI provider."""

    def _make_openai_error(self, status_code: int, message: str):
        """Build a minimal fake that quacks like openai.APIStatusError."""
        exc = Exception(f"Error code: {status_code} - {message}")
        exc.status_code = status_code
        return exc

    # ------------------------------------------------------------------
    # Constructor / configuration
    # ------------------------------------------------------------------

    def test_skill_accepts_openai_api_key_parameter(self):
        """FlakyTestAnalysisSkill stores the openai_api_key passed directly."""
        from skills.flaky_test_analysis import FlakyTestAnalysisSkill
        skill = FlakyTestAnalysisSkill(openai_api_key="sk-openai-test")
        assert skill._openai_api_key == "sk-openai-test"

    def test_skill_reads_openai_api_key_from_env(self):
        """When openai_api_key is not passed, the OPENAI_API_KEY env var is used."""
        from skills.flaky_test_analysis import FlakyTestAnalysisSkill
        with patch.dict("os.environ", {"OPENAI_API_KEY": "sk-env-key"}):
            skill = FlakyTestAnalysisSkill()
        assert skill._openai_api_key == "sk-env-key"

    def test_skill_accepts_openai_model_parameter(self):
        """FlakyTestAnalysisSkill stores the openai_model passed directly."""
        from skills.flaky_test_analysis import FlakyTestAnalysisSkill
        skill = FlakyTestAnalysisSkill(openai_model="gpt-4-turbo")
        assert skill._openai_model == "gpt-4-turbo"

    def test_openai_model_default_is_gpt4o_mini(self):
        """The default OpenAI model is gpt-4o-mini (widely accessible, low cost)."""
        from skills.flaky_test_analysis import FlakyTestAnalysisSkill
        skill = FlakyTestAnalysisSkill()
        assert skill._openai_model == "gpt-4o-mini"

    # ------------------------------------------------------------------
    # _build_model_list helper
    # ------------------------------------------------------------------

    def test_build_model_list_primary_not_in_fallbacks(self):
        """When the primary model is not in _OPENAI_FALLBACK_MODELS, all fallbacks are appended."""
        from skills.flaky_test_analysis.skill import _build_model_list
        result = _build_model_list("gpt-4o")
        assert result[0] == "gpt-4o"
        assert "gpt-4o-mini" in result
        assert "gpt-3.5-turbo" in result
        # No duplicates
        assert len(result) == len(set(result))

    def test_build_model_list_primary_is_fallback(self):
        """When the primary model is already in _OPENAI_FALLBACK_MODELS, no duplicates."""
        from skills.flaky_test_analysis.skill import _build_model_list
        result = _build_model_list("gpt-4o-mini")
        assert result[0] == "gpt-4o-mini"
        assert result.count("gpt-4o-mini") == 1

    def test_build_model_list_last_fallback_as_primary(self):
        """When the primary is the last fallback, the list still has no duplicates."""
        from skills.flaky_test_analysis.skill import _build_model_list
        result = _build_model_list("gpt-3.5-turbo")
        assert result[0] == "gpt-3.5-turbo"
        assert result.count("gpt-3.5-turbo") == 1

    # ------------------------------------------------------------------
    # model-not-found fallback in _generate_root_cause_analysis_openai
    # ------------------------------------------------------------------

    def test_root_cause_openai_falls_back_on_model_not_found(self):
        """A 404 model-not-found error triggers a retry with the next fallback model."""
        from skills.flaky_test_analysis import FlakyTestAnalysisSkill
        import skills.flaky_test_analysis.skill as skill_module

        not_found_exc = self._make_openai_error(404, "The model `gpt-4o` does not exist")

        choice = MagicMock()
        choice.message.content = (
            "**Root Cause:** Timer drift.\n\n"
            "**Recommended Solution:** Use monotonic clock."
        )
        success_response = MagicMock()
        success_response.choices = [choice]

        fake_openai = MagicMock()
        # First call raises 404; second call succeeds
        fake_openai.OpenAI.return_value.chat.completions.create.side_effect = [
            not_found_exc,
            success_response,
        ]

        skill = FlakyTestAnalysisSkill(openai_api_key="sk-openai-test", openai_model="gpt-4o")

        with patch.object(skill_module, "_openai", fake_openai, create=True), \
             patch.object(skill_module, "_OPENAI_AVAILABLE", True):
            rc, sol, al, snippet, err = skill._generate_root_cause_analysis_openai(
                issue={"key": "X-1", "status": "Open", "summary": "Test"},
                attachments=[],
                robot_runs=[],
                flaky_metrics=[],
            )

        assert "Timer drift" in rc
        assert "monotonic" in sol
        assert err == ""
        # create() should have been called twice (primary failed, fallback succeeded)
        assert fake_openai.OpenAI.return_value.chat.completions.create.call_count == 2

    def test_root_cause_openai_returns_error_when_all_models_fail(self):
        """When every model in the fallback list raises 404, return an error hint."""
        from skills.flaky_test_analysis import FlakyTestAnalysisSkill
        import skills.flaky_test_analysis.skill as skill_module

        not_found_exc = self._make_openai_error(404, "The model does not exist")

        fake_openai = MagicMock()
        fake_openai.OpenAI.return_value.chat.completions.create.side_effect = not_found_exc

        skill = FlakyTestAnalysisSkill(openai_api_key="sk-openai-test", openai_model="gpt-4o")

        with patch.object(skill_module, "_openai", fake_openai, create=True), \
             patch.object(skill_module, "_OPENAI_AVAILABLE", True):
            rc, sol, al, snippet, err = skill._generate_root_cause_analysis_openai(
                issue={"key": "X-1", "status": "Open", "summary": "Test"},
                attachments=[],
                robot_runs=[],
                flaky_metrics=[],
            )

        assert rc == ""
        assert sol == ""
        assert "model not found" in err

    # ------------------------------------------------------------------
    # _generate_root_cause_analysis_openai – happy path
    # ------------------------------------------------------------------

    def test_generate_root_cause_analysis_openai_success(self):
        """OpenAI root-cause analysis returns parsed root_cause and solution."""
        from skills.flaky_test_analysis import FlakyTestAnalysisSkill
        import skills.flaky_test_analysis.skill as skill_module

        fake_openai = MagicMock()
        choice = MagicMock()
        choice.message.content = (
            "**Root Cause:** The test relies on a real clock.\n\n"
            "**Recommended Solution:** Use freezegun."
        )
        fake_openai.OpenAI.return_value.chat.completions.create.return_value.choices = [choice]

        skill = FlakyTestAnalysisSkill(openai_api_key="sk-openai-test")

        with patch.object(skill_module, "_openai", fake_openai, create=True), \
             patch.object(skill_module, "_OPENAI_AVAILABLE", True):
            rc, sol, al, snippet, err = skill._generate_root_cause_analysis_openai(
                issue={"key": "X-1", "status": "Open", "summary": "Test"},
                attachments=[],
                robot_runs=[],
                flaky_metrics=[],
            )

        assert "real clock" in rc
        assert "freezegun" in sol
        assert err == ""

    # ------------------------------------------------------------------
    # _generate_root_cause_analysis_openai – error handling
    # ------------------------------------------------------------------

    def test_root_cause_openai_returns_empty_on_quota_error(self, caplog):
        """OpenAI quota error is caught and returns ('', '', '', '', error_hint)."""
        from skills.flaky_test_analysis import FlakyTestAnalysisSkill
        import skills.flaky_test_analysis.skill as skill_module

        quota_exc = self._make_openai_error(
            429,
            "You exceeded your current quota, please check your plan."
        )

        fake_openai = MagicMock()
        fake_openai.OpenAI.return_value.chat.completions.create.side_effect = quota_exc

        skill = FlakyTestAnalysisSkill(openai_api_key="sk-openai-test")

        with patch.object(skill_module, "_openai", fake_openai, create=True), \
             patch.object(skill_module, "_OPENAI_AVAILABLE", True):
            result = skill._generate_root_cause_analysis_openai(
                issue={"key": "X-1", "status": "Open", "summary": "Test"},
                attachments=[],
                robot_runs=[],
                flaky_metrics=[],
            )

        assert result[:2] == ("", "")
        assert result[4]  # error_hint must be non-empty (index 4 in 5-tuple)

    def test_root_cause_openai_returns_empty_on_auth_error(self, caplog):
        """OpenAI 401 error is caught and returns ('', '', '', '', error_hint)."""
        from skills.flaky_test_analysis import FlakyTestAnalysisSkill
        import skills.flaky_test_analysis.skill as skill_module

        auth_exc = self._make_openai_error(401, "Incorrect API key provided.")

        fake_openai = MagicMock()
        fake_openai.OpenAI.return_value.chat.completions.create.side_effect = auth_exc

        skill = FlakyTestAnalysisSkill(openai_api_key="bad-key")

        with patch.object(skill_module, "_openai", fake_openai, create=True), \
             patch.object(skill_module, "_OPENAI_AVAILABLE", True):
            result = skill._generate_root_cause_analysis_openai(
                issue={"key": "X-1", "status": "Open", "summary": "Test"},
                attachments=[],
                robot_runs=[],
                flaky_metrics=[],
            )

        assert result[:2] == ("", "")
        assert result[4]  # error_hint must be non-empty (index 4 in 5-tuple)

    def test_root_cause_openai_returns_empty_when_package_missing(self):
        """When _OPENAI_AVAILABLE is False the method returns ('', '', '', '', '')."""
        from skills.flaky_test_analysis import FlakyTestAnalysisSkill
        import skills.flaky_test_analysis.skill as skill_module

        skill = FlakyTestAnalysisSkill(openai_api_key="sk-openai-test")

        with patch.object(skill_module, "_OPENAI_AVAILABLE", False):
            result = skill._generate_root_cause_analysis_openai(
                issue={"key": "X-1", "status": "Open", "summary": "Test"},
                attachments=[],
                robot_runs=[],
                flaky_metrics=[],
            )

        assert result == ("", "", "", "", "")

    # ------------------------------------------------------------------
    # analyze_ticket – OpenAI used when Anthropic not configured
    # ------------------------------------------------------------------

    def test_analyze_ticket_uses_openai_when_no_anthropic_key(self):
        """When only OPENAI_API_KEY is set, analyze_ticket uses OpenAI."""
        from skills.flaky_test_analysis import FlakyTestAnalysisSkill
        import skills.flaky_test_analysis.skill as skill_module

        mock_jira = _make_jira_mock()

        fake_openai = MagicMock()
        choice = MagicMock()
        choice.message.content = (
            "**Root Cause:** Network timeout.\n"
            "**Recommended Solution:** Add retry logic."
        )
        fake_openai.OpenAI.return_value.chat.completions.create.return_value.choices = [choice]

        skill = FlakyTestAnalysisSkill(openai_api_key="sk-openai-test", jira_client=mock_jira)

        with patch.object(skill_module, "_ANTHROPIC_AVAILABLE", False), \
             patch.object(skill_module, "_OPENAI_AVAILABLE", True), \
             patch.object(skill_module, "_openai", fake_openai, create=True):
            report = skill.analyze_ticket("NCCF-1", use_ai=True, post_comment=False)

        assert "Network timeout" in report.root_cause
        assert "retry" in report.recommended_solution

    def test_analyze_ticket_falls_back_to_openai_when_anthropic_fails(self):
        """When Anthropic fails, OpenAI is tried as a fallback."""
        from skills.flaky_test_analysis import FlakyTestAnalysisSkill
        import skills.flaky_test_analysis.skill as skill_module

        mock_jira = _make_jira_mock()

        fake_anthropic = MagicMock()
        fake_anthropic.Anthropic.return_value.messages.create.side_effect = Exception(
            "credit balance is too low"
        )

        fake_openai = MagicMock()
        choice = MagicMock()
        choice.message.content = (
            "**Root Cause:** Timeout in CI.\n"
            "**Recommended Solution:** Increase timeout."
        )
        fake_openai.OpenAI.return_value.chat.completions.create.return_value.choices = [choice]

        skill = FlakyTestAnalysisSkill(
            anthropic_api_key="sk-ant-key",
            openai_api_key="sk-openai-key",
            jira_client=mock_jira,
        )

        with patch.object(skill_module, "_ANTHROPIC_AVAILABLE", True), \
             patch.object(skill_module, "_anthropic", fake_anthropic, create=True), \
             patch.object(skill_module, "_OPENAI_AVAILABLE", True), \
             patch.object(skill_module, "_openai", fake_openai, create=True):
            report = skill.analyze_ticket("NCCF-1", use_ai=True, post_comment=False)

        assert "Timeout in CI" in report.root_cause

    def test_analyze_ticket_no_ai_skips_openai(self):
        """With use_ai=False, neither Anthropic nor OpenAI should be called."""
        from skills.flaky_test_analysis import FlakyTestAnalysisSkill
        import skills.flaky_test_analysis.skill as skill_module

        mock_jira = _make_jira_mock()
        skill = FlakyTestAnalysisSkill(
            openai_api_key="sk-openai-test", jira_client=mock_jira
        )

        with patch.object(skill, "_generate_root_cause_analysis_openai",
                          wraps=skill._generate_root_cause_analysis_openai) as spy:
            report = skill.analyze_ticket("NCCF-1", use_ai=False, post_comment=False)

        spy.assert_not_called()
        assert report.root_cause == ""

    # ------------------------------------------------------------------
    # _generate_ai_summary_openai – happy path
    # ------------------------------------------------------------------

    def test_generate_ai_summary_openai_success(self):
        """OpenAI summary generation returns the model response text."""
        from skills.flaky_test_analysis import FlakyTestAnalysisSkill
        import skills.flaky_test_analysis.skill as skill_module
        from skills.flaky_test_analysis.metrics import TestMetrics

        fake_openai = MagicMock()
        choice = MagicMock()
        choice.message.content = "Several tests are intermittently failing due to timing."
        fake_openai.OpenAI.return_value.chat.completions.create.return_value.choices = [choice]

        skill = FlakyTestAnalysisSkill(openai_api_key="sk-openai-test")

        metric = MagicMock(spec=TestMetrics)
        metric.flakiness_score = "High"
        metric.name = "test_foo"
        metric.failure_rate_display = "50%"

        with patch.object(skill_module, "_openai", fake_openai, create=True), \
             patch.object(skill_module, "_OPENAI_AVAILABLE", True):
            result = skill._generate_ai_summary_openai([metric], {})

        assert "timing" in result

    def test_generate_ai_summary_openai_returns_empty_on_error(self, caplog):
        """OpenAI API errors during summary generation are caught; returns ''."""
        from skills.flaky_test_analysis import FlakyTestAnalysisSkill
        import skills.flaky_test_analysis.skill as skill_module
        from skills.flaky_test_analysis.metrics import TestMetrics

        fake_openai = MagicMock()
        fake_openai.OpenAI.return_value.chat.completions.create.side_effect = Exception(
            "exceeded your current quota"
        )

        skill = FlakyTestAnalysisSkill(openai_api_key="sk-openai-test")

        metric = MagicMock(spec=TestMetrics)
        metric.flakiness_score = "High"
        metric.name = "test_foo"
        metric.failure_rate_display = "50%"

        with patch.object(skill_module, "_openai", fake_openai, create=True), \
             patch.object(skill_module, "_OPENAI_AVAILABLE", True):
            result = skill._generate_ai_summary_openai([metric], {})

        assert result == ""

    def test_generate_ai_summary_openai_returns_stable_message_when_no_flaky(self):
        """When there are no flaky tests, returns the standard stable message."""
        from skills.flaky_test_analysis import FlakyTestAnalysisSkill
        import skills.flaky_test_analysis.skill as skill_module
        from skills.flaky_test_analysis.metrics import TestMetrics

        skill = FlakyTestAnalysisSkill(openai_api_key="sk-openai-test")

        metric = MagicMock(spec=TestMetrics)
        metric.flakiness_score = "Stable"

        with patch.object(skill_module, "_OPENAI_AVAILABLE", True):
            result = skill._generate_ai_summary_openai([metric], {})

        assert "No flaky tests" in result

    # ------------------------------------------------------------------
    # run_analysis – routes to OpenAI when Anthropic not available
    # ------------------------------------------------------------------

    def test_run_analysis_uses_openai_when_anthropic_not_available(self):
        """run_analysis calls _generate_ai_summary_openai when OpenAI is the only provider."""
        from skills.flaky_test_analysis import FlakyTestAnalysisSkill
        import skills.flaky_test_analysis.skill as skill_module

        skill = FlakyTestAnalysisSkill(openai_api_key="sk-openai-test")

        with patch.object(skill_module, "_ANTHROPIC_AVAILABLE", False), \
             patch.object(skill_module, "_OPENAI_AVAILABLE", True), \
             patch.object(skill, "_generate_ai_summary_openai",
                          return_value="OpenAI summary") as mock_summary:
            report = skill.run_analysis(
                [str(SAMPLE_RUN1)],
                use_ai_summary=True,
            )

        mock_summary.assert_called_once()
        assert report.ai_summary == "OpenAI summary"

    # ------------------------------------------------------------------
    # CLI – --openai-model argument
    # ------------------------------------------------------------------

    def test_cli_openai_model_arg_is_passed_to_skill(self):
        """--openai-model CLI argument is forwarded to FlakyTestAnalysisSkill."""
        from run_flaky_analysis import main

        _FAKE_JIRA_ENV = {
            "JIRA_BASE_URL": "https://example.atlassian.net",
            "JIRA_USER_EMAIL": "ci@example.com",
            "JIRA_API_TOKEN": "fake-token",
        }
        mock_report = MagicMock()
        mock_report.formatted_report = "# Done"
        mock_report.flaky_metrics = []

        with patch.dict("os.environ", _FAKE_JIRA_ENV), \
             patch("run_flaky_analysis.FlakyTestAnalysisSkill") as MockSkill:
            MockSkill.return_value.analyze_ticket.return_value = mock_report
            with pytest.raises(SystemExit):
                main(["--jira-ticket", "NCCF-1", "--no-ai", "--no-post",
                      "--openai-model", "gpt-4-turbo"])

        _, kwargs = MockSkill.call_args
        assert kwargs.get("openai_model") == "gpt-4-turbo"


# ===========================================================================
# Groq free-LLM integration
# ===========================================================================

class TestGroqSupport:
    """Tests covering Groq as the free-tier fallback AI provider."""

    def _make_groq_error(self, status_code: int, message: str):
        exc = Exception(f"Error code: {status_code} - {message}")
        exc.status_code = status_code
        return exc

    # ------------------------------------------------------------------
    # Constructor / configuration
    # ------------------------------------------------------------------

    def test_skill_accepts_groq_api_key_parameter(self):
        """FlakyTestAnalysisSkill stores the groq_api_key passed directly."""
        from skills.flaky_test_analysis import FlakyTestAnalysisSkill
        skill = FlakyTestAnalysisSkill(groq_api_key="gsk-test")
        assert skill._groq_api_key == "gsk-test"

    def test_skill_reads_groq_api_key_from_env(self):
        """When groq_api_key is not passed, GROQ_API_KEY env var is used."""
        from skills.flaky_test_analysis import FlakyTestAnalysisSkill
        with patch.dict("os.environ", {"GROQ_API_KEY": "gsk-env-key"}):
            skill = FlakyTestAnalysisSkill()
        assert skill._groq_api_key == "gsk-env-key"

    def test_skill_accepts_groq_model_parameter(self):
        """FlakyTestAnalysisSkill stores the groq_model passed directly."""
        from skills.flaky_test_analysis import FlakyTestAnalysisSkill
        skill = FlakyTestAnalysisSkill(groq_model="llama-3.1-8b-instant")
        assert skill._groq_model == "llama-3.1-8b-instant"

    def test_groq_model_default_is_llama33_70b(self):
        """The default Groq model is llama-3.3-70b-versatile (best free-tier quality)."""
        from skills.flaky_test_analysis import FlakyTestAnalysisSkill
        skill = FlakyTestAnalysisSkill()
        assert skill._groq_model == "llama-3.3-70b-versatile"

    # ------------------------------------------------------------------
    # _create_groq_client
    # ------------------------------------------------------------------

    def test_groq_client_uses_groq_base_url(self):
        """_create_groq_client() creates an OpenAI client pointing at the Groq endpoint."""
        from skills.flaky_test_analysis import FlakyTestAnalysisSkill
        import skills.flaky_test_analysis.skill as skill_module

        captured: list = []

        class FakeClient:
            def __init__(self, **kwargs):
                captured.append(kwargs)

        fake_openai = MagicMock()
        fake_openai.OpenAI.side_effect = FakeClient

        skill = FlakyTestAnalysisSkill(groq_api_key="gsk-test")
        with patch.object(skill_module, "_openai", fake_openai, create=True):
            skill._create_groq_client()

        assert captured, "OpenAI() constructor should have been called"
        assert captured[0].get("base_url") == skill_module._GROQ_BASE_URL
        assert captured[0].get("max_retries") == 0

    # ------------------------------------------------------------------
    # _build_groq_model_list helper
    # ------------------------------------------------------------------

    def test_build_groq_model_list_primary_not_in_fallbacks(self):
        """A non-default primary model gets all fallbacks appended without duplicates."""
        from skills.flaky_test_analysis.skill import _build_groq_model_list
        result = _build_groq_model_list("llama-3.3-70b-versatile")
        assert result[0] == "llama-3.3-70b-versatile"
        assert len(result) == len(set(result))

    def test_build_groq_model_list_primary_is_fallback(self):
        """When the primary is already a known fallback, no duplicates are added."""
        from skills.flaky_test_analysis.skill import _build_groq_model_list
        result = _build_groq_model_list("llama-3.1-8b-instant")
        assert result[0] == "llama-3.1-8b-instant"
        assert result.count("llama-3.1-8b-instant") == 1

    # ------------------------------------------------------------------
    # _generate_root_cause_analysis_groq – success path
    # ------------------------------------------------------------------

    def test_generate_root_cause_analysis_groq_success(self):
        """A successful Groq call returns (root_cause, recommended_solution, '', '', '')."""
        from skills.flaky_test_analysis import FlakyTestAnalysisSkill
        import skills.flaky_test_analysis.skill as skill_module

        choice = MagicMock()
        choice.message.content = (
            "**Root Cause:** Flaky timing dependency.\n"
            "**Recommended Solution:** Use deterministic waits."
        )
        fake_openai = MagicMock()
        fake_openai.OpenAI.return_value.chat.completions.create.return_value.choices = [choice]

        skill = FlakyTestAnalysisSkill(groq_api_key="gsk-test")
        with patch.object(skill_module, "_OPENAI_AVAILABLE", True), \
             patch.object(skill_module, "_openai", fake_openai, create=True):
            rc, sol, al, snippet, hint = skill._generate_root_cause_analysis_groq(
                issue={"key": "X-1", "status": "Open", "summary": "Test"},
                attachments=[],
                robot_runs=[],
                flaky_metrics=[],
            )

        assert "timing" in rc.lower()
        assert "deterministic" in sol.lower()
        assert hint == ""

    # ------------------------------------------------------------------
    # Error handling
    # ------------------------------------------------------------------

    def test_groq_rate_limit_returns_error_hint(self, caplog):
        """A 429 rate-limit error from Groq returns a non-empty error_hint."""
        from skills.flaky_test_analysis import FlakyTestAnalysisSkill
        import skills.flaky_test_analysis.skill as skill_module

        rate_exc = self._make_groq_error(429, "rate_limit_exceeded")
        fake_openai = MagicMock()
        fake_openai.OpenAI.return_value.chat.completions.create.side_effect = rate_exc

        skill = FlakyTestAnalysisSkill(groq_api_key="gsk-test")
        with caplog.at_level("ERROR"), \
             patch.object(skill_module, "_OPENAI_AVAILABLE", True), \
             patch.object(skill_module, "_openai", fake_openai, create=True):
            rc, sol, al, snippet, hint = skill._generate_root_cause_analysis_groq(
                issue={"key": "X-1", "status": "Open", "summary": "Test"},
                attachments=[],
                robot_runs=[],
                flaky_metrics=[],
            )

        assert rc == "" and sol == ""
        assert "rate limit" in hint.lower()

    def test_groq_returns_empty_when_package_missing(self):
        """When _OPENAI_AVAILABLE is False the Groq method returns ('', '', '', '', '')."""
        from skills.flaky_test_analysis import FlakyTestAnalysisSkill
        import skills.flaky_test_analysis.skill as skill_module

        skill = FlakyTestAnalysisSkill(groq_api_key="gsk-test")
        with patch.object(skill_module, "_OPENAI_AVAILABLE", False):
            result = skill._generate_root_cause_analysis_groq(
                issue={"key": "X-1", "status": "Open", "summary": "Test"},
                attachments=[],
                robot_runs=[],
                flaky_metrics=[],
            )
        assert result == ("", "", "", "", "")

    def test_groq_falls_back_on_model_not_found(self):
        """A 404 model-not-found triggers retry with the next fallback model."""
        from skills.flaky_test_analysis import FlakyTestAnalysisSkill
        import skills.flaky_test_analysis.skill as skill_module

        not_found_exc = self._make_groq_error(404, "model_not_found for llama-3.3-70b-versatile")

        choice = MagicMock()
        choice.message.content = (
            "**Root Cause:** Timeout.\n**Recommended Solution:** Increase wait."
        )
        success_resp = MagicMock()
        success_resp.choices = [choice]

        call_results = [not_found_exc, success_resp]

        def side_effect(**kwargs):
            result = call_results.pop(0)
            if isinstance(result, Exception):
                raise result
            return result

        fake_openai = MagicMock()
        fake_openai.OpenAI.return_value.chat.completions.create.side_effect = side_effect

        skill = FlakyTestAnalysisSkill(
            groq_api_key="gsk-test",
            groq_model="llama-3.3-70b-versatile",
        )
        with patch.object(skill_module, "_OPENAI_AVAILABLE", True), \
             patch.object(skill_module, "_openai", fake_openai, create=True):
            rc, sol, al, snippet, hint = skill._generate_root_cause_analysis_groq(
                issue={"key": "X-1", "status": "Open", "summary": "Test"},
                attachments=[],
                robot_runs=[],
                flaky_metrics=[],
            )

        assert "Timeout" in rc
        assert hint == ""

    # ------------------------------------------------------------------
    # analyze_ticket – Groq as third-priority fallback
    # ------------------------------------------------------------------

    def test_analyze_ticket_falls_back_to_groq_when_both_paid_fail(self):
        """When Anthropic and OpenAI both fail, analyze_ticket falls back to Groq."""
        from skills.flaky_test_analysis import FlakyTestAnalysisSkill
        import skills.flaky_test_analysis.skill as skill_module

        mock_jira = _make_jira_mock()

        # Anthropic billing error
        fake_anthropic = MagicMock()
        billing_exc = Exception("your credit balance is too low")
        fake_anthropic.Anthropic.return_value.messages.create.side_effect = billing_exc

        # OpenAI quota error
        openai_quota_exc = Exception("Error code: 429 - exceeded your current quota")
        openai_quota_exc.status_code = 429

        # Groq success
        groq_choice = MagicMock()
        groq_choice.message.content = (
            "**Root Cause:** Service not available.\n"
            "**Recommended Solution:** Retry with back-off."
        )

        call_count = {"n": 0}

        def openai_side_effect(**kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise openai_quota_exc
            resp = MagicMock()
            resp.choices = [groq_choice]
            return resp

        fake_openai = MagicMock()
        fake_openai.OpenAI.return_value.chat.completions.create.side_effect = openai_side_effect

        skill = FlakyTestAnalysisSkill(
            anthropic_api_key="ant-test",
            openai_api_key="sk-test",
            groq_api_key="gsk-test",
            jira_client=mock_jira,
        )

        with patch.object(skill_module, "_ANTHROPIC_AVAILABLE", True), \
             patch.object(skill_module, "_OPENAI_AVAILABLE", True), \
             patch.object(skill_module, "_anthropic", fake_anthropic, create=True), \
             patch.object(skill_module, "_openai", fake_openai, create=True):
            report = skill.analyze_ticket("NCCF-1", use_ai=True, post_comment=False)

        assert "Service not available" in report.root_cause
        assert "back-off" in report.recommended_solution

    def test_analyze_ticket_no_ai_skips_groq(self):
        """With use_ai=False, Groq is never called."""
        from skills.flaky_test_analysis import FlakyTestAnalysisSkill
        import skills.flaky_test_analysis.skill as skill_module

        mock_jira = _make_jira_mock()
        skill = FlakyTestAnalysisSkill(groq_api_key="gsk-test", jira_client=mock_jira)

        fake_openai = MagicMock()
        with patch.object(skill_module, "_OPENAI_AVAILABLE", True), \
             patch.object(skill_module, "_openai", fake_openai, create=True):
            skill.analyze_ticket("NCCF-1", use_ai=False, post_comment=False)

        fake_openai.OpenAI.assert_not_called()

    # ------------------------------------------------------------------
    # CLI support
    # ------------------------------------------------------------------

    def test_cli_groq_model_arg_is_passed_to_skill(self):
        """--groq-model CLI argument is forwarded to FlakyTestAnalysisSkill."""
        from run_flaky_analysis import main

        _FAKE_JIRA_ENV = {
            "JIRA_BASE_URL": "https://example.atlassian.net",
            "JIRA_USER_EMAIL": "ci@example.com",
            "JIRA_API_TOKEN": "fake-token",
        }
        mock_report = MagicMock()
        mock_report.formatted_report = "# Done"
        mock_report.flaky_metrics = []

        with patch.dict("os.environ", _FAKE_JIRA_ENV), \
             patch("run_flaky_analysis.FlakyTestAnalysisSkill") as MockSkill:
            MockSkill.return_value.analyze_ticket.return_value = mock_report
            with pytest.raises(SystemExit):
                main(["--jira-ticket", "NCCF-1", "--no-ai", "--no-post",
                      "--groq-model", "llama-3.1-8b-instant"])

        _, kwargs = MockSkill.call_args
        assert kwargs.get("groq_model") == "llama-3.1-8b-instant"

    def test_cli_groq_model_default(self):
        """When --groq-model is not passed, the default llama-3.3-70b-versatile is used."""
        from run_flaky_analysis import main

        _FAKE_JIRA_ENV = {
            "JIRA_BASE_URL": "https://example.atlassian.net",
            "JIRA_USER_EMAIL": "ci@example.com",
            "JIRA_API_TOKEN": "fake-token",
        }
        mock_report = MagicMock()
        mock_report.formatted_report = "# Done"
        mock_report.flaky_metrics = []

        with patch.dict("os.environ", _FAKE_JIRA_ENV), \
             patch("run_flaky_analysis.FlakyTestAnalysisSkill") as MockSkill:
            MockSkill.return_value.analyze_ticket.return_value = mock_report
            with pytest.raises(SystemExit):
                main(["--jira-ticket", "NCCF-1", "--no-ai", "--no-post"])

        _, kwargs = MockSkill.call_args
        assert kwargs.get("groq_model") == "llama-3.3-70b-versatile"


class TestBuildRootCausePrompt:
    """Tests for _build_root_cause_prompt, shared by all AI providers."""

    def _make_skill(self):
        from skills.flaky_test_analysis import FlakyTestAnalysisSkill
        return FlakyTestAnalysisSkill()

    def test_auto_generated_comments_are_excluded_from_prompt(self):
        """
        Previously posted auto-generated comments must not appear in the AI
        prompt.  When both Anthropic and OpenAI fail the skill posts a comment
        such as "AI analysis unavailable …\n_Analysis generated automatically
        by the Flaky Test Analysis Skill._".  If that comment is fed back to
        Groq on a subsequent run, the model confuses the billing error message
        for the actual root cause.
        """
        from skills.flaky_test_analysis.skill import _SKILL_COMMENT_MARKER

        skill = self._make_skill()
        auto_comment = (
            "# Root Cause Analysis – NCCF-1\n"
            "_AI analysis unavailable (billing error – OpenAI quota exceeded)._\n"
            "---\n"
            f"{_SKILL_COMMENT_MARKER}"
        )
        issue = {
            "key": "NCCF-1",
            "summary": "Two_Factor_Authentication suite failure",
            "status": "Closed",
            "description": "Robot Framework test run failed.",
            "comments": [
                "First comment from a human",
                auto_comment,
            ],
        }

        prompt = skill._build_root_cause_prompt(issue, [], [], [])

        assert _SKILL_COMMENT_MARKER not in prompt, (
            "Auto-generated skill comment must be filtered out of the AI prompt"
        )
        assert "First comment from a human" in prompt, (
            "Non-auto-generated comments should still appear in the prompt"
        )
        assert "OpenAI quota exceeded" not in prompt, (
            "Billing error text from a prior auto-generated comment must not reach the LLM"
        )

    def test_human_comments_are_included_in_prompt(self):
        """Regular (non-auto-generated) comments must still be included."""
        skill = self._make_skill()
        issue = {
            "key": "NCCF-2",
            "summary": "Login suite failure",
            "status": "Open",
            "description": "",
            "comments": [
                "Manual triage: looks like a network timeout.",
                "Rerun confirmed it fails consistently.",
            ],
        }

        prompt = skill._build_root_cause_prompt(issue, [], [], [])

        assert "Manual triage" in prompt
        assert "Rerun confirmed" in prompt

    def test_prompt_requests_code_snippet_section(self):
        """The prompt must instruct the AI to produce a 'Code Snippet:' section."""
        skill = self._make_skill()
        issue = {
            "key": "NCCF-3",
            "summary": "Test",
            "status": "Open",
            "description": "",
            "comments": [],
        }
        prompt = skill._build_root_cause_prompt(issue, [], [], [])
        assert "Code Snippet" in prompt, (
            "The prompt must request a Code Snippet section from the AI"
        )


# ===========================================================================
# Feature: code snippet extraction from AI response
# ===========================================================================

class TestParseAiResponseCodeSnippet:
    """Tests for _parse_ai_response – code-snippet extraction."""

    def test_extracts_code_snippet_from_three_section_response(self):
        """A response with all four sections returns correct 4-tuple."""
        from skills.flaky_test_analysis.skill import FlakyTestAnalysisSkill

        response = (
            "**Root Cause:** The test depends on system time.\n\n"
            "**Recommended Solution:** Use a time-mocking library.\n\n"
            "**Code Snippet:**\n"
            "```python\n"
            "from freezegun import freeze_time\n\n"
            "@freeze_time('2024-01-01')\n"
            "def test_example():\n"
            "    assert True\n"
            "```"
        )
        rc, sol, al, snippet = FlakyTestAnalysisSkill._parse_ai_response(response)

        assert "system time" in rc
        assert "time-mocking" in sol
        assert "freezegun" in snippet
        assert "freeze_time" in snippet

    def test_na_code_snippet_returns_empty_string(self):
        """When the AI responds with 'N/A' for the code snippet, the field is empty."""
        from skills.flaky_test_analysis.skill import FlakyTestAnalysisSkill

        response = (
            "**Root Cause:** Config issue.\n\n"
            "**Recommended Solution:** Update config file.\n\n"
            "**Code Snippet:** N/A"
        )
        rc, sol, al, snippet = FlakyTestAnalysisSkill._parse_ai_response(response)

        assert "Config issue" in rc
        assert snippet == ""

    def test_missing_code_snippet_section_returns_empty_string(self):
        """If the AI omits the Code Snippet section entirely, snippet is empty."""
        from skills.flaky_test_analysis.skill import FlakyTestAnalysisSkill

        response = (
            "**Root Cause:** Network timeout.\n\n"
            "**Recommended Solution:** Add retry logic."
        )
        _rc, _sol, _al, snippet = FlakyTestAnalysisSkill._parse_ai_response(response)
        assert snippet == ""

    def test_code_snippet_is_stored_on_ticket_report(self):
        """code_snippet returned by the AI is stored on the TicketAnalysisReport."""
        from skills.flaky_test_analysis import FlakyTestAnalysisSkill
        import skills.flaky_test_analysis.skill as skill_module
        from unittest.mock import MagicMock, patch

        mock_jira = MagicMock()
        mock_jira.get_issue.return_value = {
            "key": "NCCF-1",
            "summary": "Test",
            "status": "Open",
            "description": "",
            "attachments": [],
            "comments": [],
        }
        mock_jira.list_attachments.return_value = []

        fake_openai = MagicMock()
        choice = MagicMock()
        choice.message.content = (
            "**Root Cause:** Timer drift.\n\n"
            "**Recommended Solution:** Use monotonic clock.\n\n"
            "**Code Snippet:**\n"
            "```python\nimport time\ntime.monotonic()\n```"
        )
        fake_openai.OpenAI.return_value.chat.completions.create.return_value.choices = [choice]

        skill = FlakyTestAnalysisSkill(openai_api_key="sk-test", jira_client=mock_jira)

        with patch.object(skill_module, "_ANTHROPIC_AVAILABLE", False), \
             patch.object(skill_module, "_OPENAI_AVAILABLE", True), \
             patch.object(skill_module, "_openai", fake_openai, create=True):
            report = skill.analyze_ticket("NCCF-1", use_ai=True, post_comment=False)

        assert "monotonic" in report.code_snippet or "time" in report.code_snippet

    def test_code_snippet_appears_in_formatted_markdown_report(self):
        """The formatted Markdown report includes a '## 💻 Corrected Code Snippet' section."""
        from skills.flaky_test_analysis import FlakyTestAnalysisSkill
        import skills.flaky_test_analysis.skill as skill_module
        from unittest.mock import MagicMock, patch

        mock_jira = MagicMock()
        mock_jira.get_issue.return_value = {
            "key": "NCCF-1",
            "summary": "Test",
            "status": "Open",
            "description": "",
            "attachments": [],
            "comments": [],
        }
        mock_jira.list_attachments.return_value = []

        fake_openai = MagicMock()
        choice = MagicMock()
        choice.message.content = (
            "**Root Cause:** Timer drift.\n\n"
            "**Recommended Solution:** Fix it.\n\n"
            "**Code Snippet:**\n```python\nx = 1\n```"
        )
        fake_openai.OpenAI.return_value.chat.completions.create.return_value.choices = [choice]

        skill = FlakyTestAnalysisSkill(openai_api_key="sk-test", jira_client=mock_jira)

        with patch.object(skill_module, "_ANTHROPIC_AVAILABLE", False), \
             patch.object(skill_module, "_OPENAI_AVAILABLE", True), \
             patch.object(skill_module, "_openai", fake_openai, create=True):
            report = skill.analyze_ticket("NCCF-1", use_ai=True, post_comment=False)

        assert "💻 Corrected Code Snippet" in report.formatted_report


# ===========================================================================
# Feature: HTML report generation
# ===========================================================================

class TestHtmlReport:
    """Tests for render_html_report and markdown_wrap."""

    def _make_report(self, issue_key="NCCF-1", status="Open", root_cause="Timer drift",
                     solution="Use monotonic.", snippet="```python\nx=1\n```"):
        from skills.flaky_test_analysis import TicketAnalysisReport
        return TicketAnalysisReport(
            issue_key=issue_key,
            summary=f"Test suite failure – {issue_key}",
            status=status,
            root_cause=root_cause,
            recommended_solution=solution,
            code_snippet=snippet,
            formatted_report=f"# {issue_key}\n{root_cause}",
        )

    def test_render_html_report_is_valid_html(self):
        """render_html_report returns a string containing standard HTML scaffolding."""
        from skills.flaky_test_analysis.html_report import render_html_report
        report = self._make_report()
        html = render_html_report([report])
        assert "<!DOCTYPE html>" in html
        assert "<html" in html
        assert "</html>" in html

    def test_render_html_report_contains_ticket_key(self):
        """The HTML report must include the ticket key."""
        from skills.flaky_test_analysis.html_report import render_html_report
        report = self._make_report(issue_key="NCCF-999")
        html = render_html_report([report])
        assert "NCCF-999" in html

    def test_render_html_report_contains_root_cause(self):
        """The root cause text must appear in the HTML report."""
        from skills.flaky_test_analysis.html_report import render_html_report
        report = self._make_report(root_cause="The test depends on system time.")
        html = render_html_report([report])
        assert "system time" in html

    def test_render_html_report_contains_code_snippet(self):
        """The HTML report must include the code snippet."""
        from skills.flaky_test_analysis.html_report import render_html_report
        report = self._make_report(snippet="```python\nfrom freezegun import freeze_time\n```")
        html = render_html_report([report])
        assert "freezegun" in html
        assert "Corrected Code Snippet" in html

    def test_render_html_report_na_snippet_is_omitted(self):
        """When code_snippet is 'N/A', the snippet section must not appear."""
        from skills.flaky_test_analysis.html_report import render_html_report
        report = self._make_report(snippet="N/A")
        html = render_html_report([report])
        assert "Corrected Code Snippet" not in html

    def test_render_html_report_batch_summary_table(self):
        """When multiple reports are provided, a summary table is rendered."""
        from skills.flaky_test_analysis.html_report import render_html_report
        reports = [
            self._make_report(issue_key="NCCF-1", status="Open"),
            self._make_report(issue_key="NCCF-2", status="Closed"),
        ]
        html = render_html_report(reports, title="Batch Analysis")
        assert "NCCF-1" in html
        assert "NCCF-2" in html
        assert "2 tickets analysed" in html
        assert "Batch Analysis" in html

    def test_render_html_report_status_badge_closed(self):
        """Closed tickets get a red status badge CSS class."""
        from skills.flaky_test_analysis.html_report import render_html_report
        report = self._make_report(status="Closed")
        html = render_html_report([report])
        assert "badge-closed" in html

    def test_render_html_report_status_badge_open(self):
        """Open tickets get a green status badge CSS class."""
        from skills.flaky_test_analysis.html_report import render_html_report
        report = self._make_report(status="Open")
        html = render_html_report([report])
        assert "badge-open" in html

    def test_markdown_wrap_returns_html(self):
        """markdown_wrap converts a Markdown string to an HTML document."""
        from skills.flaky_test_analysis.html_report import markdown_wrap
        md = "# Flaky Test Report\n\n## Summary\n\nNo flaky tests detected."
        html = markdown_wrap(md, title="My Report")
        assert "<!DOCTYPE html>" in html
        assert "My Report" in html
        assert "No flaky tests detected" in html

    def test_html_report_is_exported_from_package(self):
        """render_html_report and markdown_wrap must be importable from the package."""
        from skills.flaky_test_analysis import render_html_report, markdown_wrap
        assert callable(render_html_report)
        assert callable(markdown_wrap)

    def test_render_html_report_none_mime_type_does_not_crash(self):
        """render_html_report must not crash when an attachment has mime_type=None."""
        from skills.flaky_test_analysis import render_html_report, TicketAnalysisReport
        from skills.flaky_test_analysis.skill import AttachmentInfo

        att = AttachmentInfo(filename="report.zip", mime_type=None, size=1024)
        report = TicketAnalysisReport(
            issue_key="NCCF-42",
            summary="Null mime type test",
            status="Open",
            attachments=[att],
        )
        html = render_html_report([report])
        assert "NCCF-42" in html
        assert "report.zip" in html


# ===========================================================================
# Feature: batch Jira ticket analysis (--jira-tickets)
# ===========================================================================

class TestBatchJiraTickets:
    """Tests for the --jira-tickets CLI mode."""

    _FAKE_JIRA_ENV = {
        "JIRA_BASE_URL": "https://example.atlassian.net",
        "JIRA_USER_EMAIL": "ci@example.com",
        "JIRA_API_TOKEN": "fake-token",
    }

    def _make_report(self, key="NCCF-1"):
        mock_report = MagicMock()
        mock_report.formatted_report = f"# Report for {key}\nDone."
        mock_report.flaky_metrics = []
        return mock_report

    def test_jira_tickets_calls_analyze_ticket_for_each_key(self):
        """--jira-tickets calls analyze_ticket once per ticket key."""
        from run_flaky_analysis import main

        with patch.dict("os.environ", self._FAKE_JIRA_ENV), \
             patch("run_flaky_analysis.FlakyTestAnalysisSkill") as MockSkill, \
             patch("run_flaky_analysis.render_html_report"):
            MockSkill.return_value.analyze_ticket.side_effect = [
                self._make_report("NCCF-1"),
                self._make_report("NCCF-2"),
            ]
            with pytest.raises(SystemExit) as exc_info:
                main(["--jira-tickets", "NCCF-1", "NCCF-2", "--no-ai", "--no-post"])
            assert exc_info.value.code == 0

        calls = MockSkill.return_value.analyze_ticket.call_args_list
        called_keys = [c.kwargs["jira_issue_key"] for c in calls]
        assert called_keys == ["NCCF-1", "NCCF-2"]

    def test_jira_tickets_mutually_exclusive_with_jira_ticket(self):
        """--jira-tickets and --jira-ticket together must exit with error."""
        from run_flaky_analysis import main
        with pytest.raises(SystemExit) as exc_info:
            main(["--jira-tickets", "NCCF-1", "--jira-ticket", "NCCF-2"])
        assert exc_info.value.code == 1

    def test_jira_tickets_mutually_exclusive_with_robot_output(self):
        """--jira-tickets and --robot-output together must exit with error."""
        from run_flaky_analysis import main
        with pytest.raises(SystemExit) as exc_info:
            main(["--jira-tickets", "NCCF-1", "--robot-output", "file.xml"])
        assert exc_info.value.code == 1

    def test_jira_tickets_missing_env_exits_cleanly(self, capsys):
        """--jira-tickets without Jira env vars exits with a friendly error."""
        from run_flaky_analysis import main
        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(SystemExit) as exc_info:
                main(["--jira-tickets", "NCCF-1", "NCCF-2"])
        assert exc_info.value.code == 1
        err = capsys.readouterr().err
        assert "JIRA_BASE_URL" in err

    def test_jira_tickets_writes_html_report(self, tmp_path):
        """When --html-report is given, an HTML file is written for batch tickets."""
        from run_flaky_analysis import main

        html_path = tmp_path / "report.html"

        with patch.dict("os.environ", self._FAKE_JIRA_ENV), \
             patch("run_flaky_analysis.FlakyTestAnalysisSkill") as MockSkill, \
             patch("run_flaky_analysis.render_html_report", return_value="<html/>") as mock_render:
            MockSkill.return_value.analyze_ticket.return_value = self._make_report("NCCF-1")
            with pytest.raises(SystemExit):
                main([
                    "--jira-tickets", "NCCF-1",
                    "--no-ai", "--no-post",
                    "--html-report", str(html_path),
                ])

        mock_render.assert_called_once()
        assert html_path.exists()
        assert html_path.read_text() == "<html/>"

    def test_jira_tickets_failed_ticket_continues(self, capsys):
        """When one ticket fails, processing continues for remaining tickets."""
        from run_flaky_analysis import main

        with patch.dict("os.environ", self._FAKE_JIRA_ENV), \
             patch("run_flaky_analysis.FlakyTestAnalysisSkill") as MockSkill, \
             patch("run_flaky_analysis.render_html_report"):
            MockSkill.return_value.analyze_ticket.side_effect = [
                RuntimeError("Not found"),
                self._make_report("NCCF-2"),
            ]
            with pytest.raises(SystemExit) as exc_info:
                main(["--jira-tickets", "NCCF-1", "NCCF-2", "--no-ai", "--no-post"])

        # Should still call analyze_ticket for NCCF-2
        assert MockSkill.return_value.analyze_ticket.call_count == 2
        err = capsys.readouterr().err
        assert "NCCF-1" in err  # error message must mention the failing ticket


class TestHtmlReportCliFlag:
    """Tests for --html-report CLI flag in single-ticket and local-file modes."""

    _FAKE_JIRA_ENV = {
        "JIRA_BASE_URL": "https://example.atlassian.net",
        "JIRA_USER_EMAIL": "ci@example.com",
        "JIRA_API_TOKEN": "fake-token",
    }

    def test_html_report_written_for_single_ticket(self, tmp_path):
        """--html-report writes an HTML file in single-ticket mode."""
        from run_flaky_analysis import main

        html_path = tmp_path / "report.html"
        mock_report = MagicMock()
        mock_report.formatted_report = "# Done"
        mock_report.flaky_metrics = []

        with patch.dict("os.environ", self._FAKE_JIRA_ENV), \
             patch("run_flaky_analysis.FlakyTestAnalysisSkill") as MockSkill, \
             patch("run_flaky_analysis.render_html_report", return_value="<html/>") as mock_render:
            MockSkill.return_value.analyze_ticket.return_value = mock_report
            with pytest.raises(SystemExit):
                main([
                    "--jira-ticket", "NCCF-1",
                    "--no-ai", "--no-post",
                    "--html-report", str(html_path),
                ])

        mock_render.assert_called_once()
        assert html_path.exists()

    def test_html_report_written_for_robot_output(self, tmp_path):
        """--html-report writes an HTML file in local robot-output mode."""
        from run_flaky_analysis import main

        html_path = tmp_path / "report.html"
        xml_path = tmp_path / "output.xml"
        # Create a minimal robot XML file
        xml_path.write_text(
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<robot generator="Robot" generated="20240101 00:00:00.000">'
            '<suite name="S"><test name="T"><status status="PASS"/></test></suite>'
            '<statistics/><errors/></robot>',
            encoding="utf-8",
        )

        with patch("run_flaky_analysis.markdown_wrap", return_value="<html/>") as mock_wrap:
            with pytest.raises(SystemExit):
                main([
                    "--robot-output", str(xml_path),
                    "--no-ai",
                    "--html-report", str(html_path),
                ])

        mock_wrap.assert_called_once()
        assert html_path.exists()


# ===========================================================================
# Feature: GitHubClient and _extract_test_case
# ===========================================================================

class TestGitHubClient:
    """Unit tests for GitHubClient (all HTTP calls are mocked)."""

    def _make_client(self, token="test-token"):
        from skills.flaky_test_analysis.github_client import GitHubClient
        return GitHubClient(token=token, owner="nable-nc", repo="n-central")

    def test_client_sets_auth_header_when_token_provided(self):
        client = self._make_client(token="my-token")
        assert "Authorization" in client._session.headers
        assert "my-token" in client._session.headers["Authorization"]

    def test_client_has_no_auth_header_without_token(self):
        from skills.flaky_test_analysis.github_client import GitHubClient
        with patch.dict("os.environ", {}, clear=True):
            client = GitHubClient(token="", owner="nable-nc", repo="n-central")
        assert "Authorization" not in client._session.headers

    def test_search_robot_test_returns_empty_when_no_results(self):
        client = self._make_client()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"items": []}
        mock_resp.raise_for_status.return_value = None
        with patch.object(client._session, "get", return_value=mock_resp):
            file_path, snippet = client.search_robot_test("Verify Login")
        assert file_path == ""
        assert snippet == ""

    def test_search_robot_test_returns_path_and_snippet_on_success(self):
        """A search hit triggers get_file_content and returns the test snippet."""
        from skills.flaky_test_analysis.github_client import _extract_test_case
        import base64

        robot_src = (
            "*** Test Cases ***\n"
            "Verify Login\n"
            "    [Documentation]    Test login\n"
            "    Open Browser    ${URL}\n"
            "    Input Text    username    admin\n"
            "    Click Button    Submit\n\n"
            "Another Test\n"
            "    Log    hello\n"
        )
        encoded = base64.b64encode(robot_src.encode()).decode()

        search_resp = MagicMock()
        search_resp.raise_for_status.return_value = None
        search_resp.json.return_value = {"items": [{"path": "tests/login.robot"}]}

        content_resp = MagicMock()
        content_resp.raise_for_status.return_value = None
        content_resp.json.return_value = {"content": encoded}

        client = self._make_client()
        call_count = [0]

        def fake_get(url, **kwargs):
            call_count[0] += 1
            if "search" in url:
                return search_resp
            return content_resp

        with patch.object(client._session, "get", side_effect=fake_get):
            file_path, snippet = client.search_robot_test("Verify Login")

        assert file_path == "tests/login.robot"
        assert "Verify Login" in snippet
        assert "Open Browser" in snippet
        # The "Another Test" block must not be included
        assert "Another Test" not in snippet
        assert call_count[0] == 2  # search + content fetch

    def test_search_robot_test_returns_empty_on_network_error(self):
        client = self._make_client()
        with patch.object(client._session, "get", side_effect=ConnectionError("timeout")):
            file_path, snippet = client.search_robot_test("Verify Login")
        assert file_path == ""
        assert snippet == ""

    def test_get_file_content_decodes_base64(self):
        import base64
        content = "*** Settings ***\nLibrary    OperatingSystem\n"
        encoded = base64.b64encode(content.encode()).decode()
        client = self._make_client()
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {"content": encoded}
        with patch.object(client._session, "get", return_value=mock_resp):
            result = client.get_file_content("path/to/file.robot")
        assert result == content

    def test_get_file_content_returns_empty_on_error(self):
        client = self._make_client()
        with patch.object(client._session, "get", side_effect=RuntimeError("boom")):
            result = client.get_file_content("path/to/file.robot")
        assert result == ""

    def test_github_token_read_from_env(self):
        from skills.flaky_test_analysis.github_client import GitHubClient
        with patch.dict("os.environ", {"GITHUB_TOKEN": "env-token"}):
            client = GitHubClient()
        assert "env-token" in client._session.headers.get("Authorization", "")


class TestExtractTestCase:
    """Tests for _extract_test_case helper."""

    _ROBOT_FILE = (
        "*** Settings ***\n"
        "Library    SeleniumLibrary\n\n"
        "*** Test Cases ***\n"
        "Verify Login\n"
        "    [Documentation]    Tests login flow\n"
        "    Open Browser    ${URL}    Chrome\n"
        "    Input Text    username    admin\n"
        "    Click Button    Submit\n"
        "    Page Should Contain    Dashboard\n\n"
        "Verify Logout\n"
        "    Click Link    Logout\n"
        "    Page Should Contain    Login\n\n"
        "*** Keywords ***\n"
        "Open App\n"
        "    Open Browser    ${URL}    Chrome\n"
    )

    def test_extracts_correct_test_case(self):
        from skills.flaky_test_analysis.github_client import _extract_test_case
        result = _extract_test_case(self._ROBOT_FILE, "Verify Login")
        assert "Verify Login" in result
        assert "Open Browser" in result
        assert "Verify Logout" not in result

    def test_second_test_case_is_correct(self):
        from skills.flaky_test_analysis.github_client import _extract_test_case
        result = _extract_test_case(self._ROBOT_FILE, "Verify Logout")
        assert "Verify Logout" in result
        assert "Click Link    Logout" in result
        assert "Open Browser" not in result

    def test_returns_file_excerpt_when_test_not_found(self):
        from skills.flaky_test_analysis.github_client import _extract_test_case
        result = _extract_test_case(self._ROBOT_FILE, "Nonexistent Test")
        # Falls back to first 3000 chars of file
        assert "*** Settings ***" in result

    def test_case_insensitive_match(self):
        from skills.flaky_test_analysis.github_client import _extract_test_case
        result = _extract_test_case(self._ROBOT_FILE, "verify login")
        assert "Open Browser" in result

    def test_underscore_space_equivalence(self):
        from skills.flaky_test_analysis.github_client import _extract_test_case
        result = _extract_test_case(self._ROBOT_FILE, "Verify_Login")
        assert "Open Browser" in result


# ===========================================================================
# Feature: pointwise AI prompt format
# ===========================================================================

class TestPointwisePrompt:
    """The AI prompt must request bullet-point/numbered-list responses."""

    def _make_skill(self):
        from skills.flaky_test_analysis import FlakyTestAnalysisSkill
        return FlakyTestAnalysisSkill()

    def test_root_cause_requested_as_bullet_list(self):
        skill = self._make_skill()
        issue = {
            "key": "NCCF-1",
            "summary": "Test",
            "status": "Open",
            "description": "",
            "comments": [],
        }
        prompt = skill._build_root_cause_prompt(issue, [], [], [])
        assert "bullet" in prompt.lower() or "- " in prompt, (
            "Prompt must describe bullet-point format for Root Cause"
        )

    def test_recommended_solution_requested_as_numbered_list(self):
        skill = self._make_skill()
        issue = {
            "key": "NCCF-1",
            "summary": "Test",
            "status": "Open",
            "description": "",
            "comments": [],
        }
        prompt = skill._build_root_cause_prompt(issue, [], [], [])
        assert "numbered" in prompt.lower() or "1." in prompt, (
            "Prompt must describe numbered-list format for Recommended Solution"
        )

    def test_prompt_includes_robot_source_when_provided(self):
        skill = self._make_skill()
        issue = {
            "key": "NCCF-1",
            "summary": "Test",
            "status": "Open",
            "description": "",
            "comments": [],
        }
        snippet = "Verify Login\n    Open Browser    ${URL}\n    Input Text    user    admin"
        prompt = skill._build_root_cause_prompt(
            issue, [], [], [],
            robot_source_file="tests/login.robot",
            robot_source_snippet=snippet,
        )
        assert "Failing Test Source" in prompt
        assert "Verify Login" in prompt
        assert "corrected" in prompt.lower(), (
            "When source is provided, prompt must ask for corrected version"
        )

    def test_prompt_omits_source_section_when_not_provided(self):
        skill = self._make_skill()
        issue = {
            "key": "NCCF-1",
            "summary": "Test",
            "status": "Open",
            "description": "",
            "comments": [],
        }
        prompt = skill._build_root_cause_prompt(issue, [], [], [])
        assert "Failing Test Source" not in prompt


# ===========================================================================
# Feature: robot source in TicketAnalysisReport and formatted report
# ===========================================================================

class TestRobotSourceInReport:
    """Tests that robot_source_file/snippet flow through analyze_ticket correctly."""

    def _make_jira_mock_no_attachments(self):
        mock_jira = MagicMock()
        mock_jira.get_issue.return_value = {
            "key": "NCCF-1",
            "summary": "Test failure",
            "status": "Open",
            "description": "",
            "attachments": [],
            "comments": [],
        }
        mock_jira.list_attachments.return_value = []
        return mock_jira

    def test_robot_source_stored_on_report(self):
        """When GitHub returns a test snippet, it is stored on TicketAnalysisReport."""
        from skills.flaky_test_analysis import FlakyTestAnalysisSkill

        mock_jira = self._make_jira_mock_no_attachments()
        mock_github = MagicMock()
        mock_github.search_robot_test.return_value = (
            "tests/login.robot",
            "Verify Login\n    Open Browser\n",
        )

        skill = FlakyTestAnalysisSkill(jira_client=mock_jira, github_client=mock_github)
        # We won't have any failing tests (no attachments) so GitHub won't be called
        report = skill.analyze_ticket("NCCF-1", use_ai=False, post_comment=False)
        # With no failing tests, GitHub should not have been queried
        mock_github.search_robot_test.assert_not_called()
        assert report.robot_source_file == ""
        assert report.robot_source_snippet == ""

    def test_robot_source_fetched_when_failing_tests_found(self):
        """When failing tests exist (from XML attachment), GitHub is queried."""
        from skills.flaky_test_analysis import FlakyTestAnalysisSkill

        # Build a minimal Robot XML with a FAIL result
        xml = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<robot generator="Robot" generated="20240101 00:00:00.000">'
            '<suite name="Login">'
            '<test name="Verify Login">'
            '<status status="FAIL" message="Element not found"/>'
            '</test>'
            '</suite>'
            '<statistics/><errors/></robot>'
        ).encode()

        attachments = [{
            "id": "1",
            "filename": "output.xml",
            "mimeType": "application/xml",
            "size": len(xml),
            "content": "https://example.atlassian.net/secure/attachment/1/output.xml",
        }]

        mock_jira = MagicMock()
        mock_jira.get_issue.return_value = {
            "key": "NCCF-2",
            "summary": "Login failure",
            "status": "Open",
            "description": "",
            "attachments": attachments,
            "comments": [],
        }
        mock_jira.download_attachment.return_value = xml

        mock_github = MagicMock()
        mock_github.search_robot_test.return_value = (
            "tests/login.robot",
            "Verify Login\n    Open Browser\n",
        )

        skill = FlakyTestAnalysisSkill(jira_client=mock_jira, github_client=mock_github)
        report = skill.analyze_ticket("NCCF-2", use_ai=False, post_comment=False)

        mock_github.search_robot_test.assert_called_once_with("Verify Login")
        assert report.robot_source_file == "tests/login.robot"
        assert "Verify Login" in report.robot_source_snippet

    def test_failing_test_source_appears_in_markdown_report(self):
        """The formatted Markdown report must include the '🤖 Failing Test Source' section."""
        from skills.flaky_test_analysis import FlakyTestAnalysisSkill

        xml = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<robot generator="Robot" generated="20240101 00:00:00.000">'
            '<suite name="Login">'
            '<test name="Verify Login">'
            '<status status="FAIL" message="Element not found"/>'
            '</test>'
            '</suite>'
            '<statistics/><errors/></robot>'
        ).encode()

        attachments = [{
            "id": "1",
            "filename": "output.xml",
            "mimeType": "application/xml",
            "size": len(xml),
            "content": "https://example.atlassian.net/secure/attachment/1/output.xml",
        }]

        mock_jira = MagicMock()
        mock_jira.get_issue.return_value = {
            "key": "NCCF-3",
            "summary": "Login failure",
            "status": "Open",
            "description": "",
            "attachments": attachments,
            "comments": [],
        }
        mock_jira.download_attachment.return_value = xml

        mock_github = MagicMock()
        mock_github.search_robot_test.return_value = (
            "tests/login.robot",
            "Verify Login\n    Open Browser    ${URL}\n",
        )

        skill = FlakyTestAnalysisSkill(jira_client=mock_jira, github_client=mock_github)
        report = skill.analyze_ticket("NCCF-3", use_ai=False, post_comment=False)

        assert "🤖 Failing Test Source" in report.formatted_report
        assert "tests/login.robot" in report.formatted_report
        assert "Open Browser" in report.formatted_report

    def test_no_failing_test_source_section_when_github_not_configured(self):
        """Without a GitHub client, there is no 'Failing Test Source' section."""
        from skills.flaky_test_analysis import FlakyTestAnalysisSkill

        xml = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<robot generator="Robot" generated="20240101 00:00:00.000">'
            '<suite name="Login">'
            '<test name="Verify Login">'
            '<status status="FAIL" message="Element not found"/>'
            '</test>'
            '</suite>'
            '<statistics/><errors/></robot>'
        ).encode()

        attachments = [{
            "id": "1",
            "filename": "output.xml",
            "mimeType": "application/xml",
            "size": len(xml),
            "content": "https://example.atlassian.net/secure/attachment/1/output.xml",
        }]

        mock_jira = MagicMock()
        mock_jira.get_issue.return_value = {
            "key": "NCCF-4",
            "summary": "Login failure",
            "status": "Open",
            "description": "",
            "attachments": attachments,
            "comments": [],
        }
        mock_jira.download_attachment.return_value = xml

        # Provide a mock that always returns empty (simulates no GitHub token)
        mock_github = MagicMock()
        mock_github.search_robot_test.return_value = ("", "")

        skill = FlakyTestAnalysisSkill(jira_client=mock_jira, github_client=mock_github)
        report = skill.analyze_ticket("NCCF-4", use_ai=False, post_comment=False)

        assert "Failing Test Source" not in report.formatted_report


# ===========================================================================
# Feature: HTML report renders Failing Test Source and pointwise sections
# ===========================================================================

class TestHtmlReportPointwiseAndSource:
    """Tests for the new HTML report features."""

    def _make_report(self, robot_source_file="", robot_source_snippet="",
                     root_cause="", recommended_solution=""):
        from skills.flaky_test_analysis import TicketAnalysisReport
        return TicketAnalysisReport(
            issue_key="NCCF-1",
            summary="Test",
            status="Open",
            root_cause=root_cause,
            recommended_solution=recommended_solution,
            robot_source_file=robot_source_file,
            robot_source_snippet=robot_source_snippet,
            formatted_report="",
        )

    def test_html_report_renders_failing_test_source(self):
        from skills.flaky_test_analysis.html_report import render_html_report
        report = self._make_report(
            robot_source_file="tests/login.robot",
            robot_source_snippet="Verify Login\n    Open Browser\n",
        )
        html = render_html_report([report])
        assert "Failing Test Source" in html
        assert "tests/login.robot" in html
        assert "Open Browser" in html

    def test_html_report_omits_source_section_when_empty(self):
        from skills.flaky_test_analysis.html_report import render_html_report
        report = self._make_report()
        html = render_html_report([report])
        assert "Failing Test Source" not in html

    def test_html_report_renders_bullet_root_cause_as_ul(self):
        from skills.flaky_test_analysis.html_report import render_html_report
        report = self._make_report(
            root_cause="- The test relies on system time.\n- The CI clock drifts.\n- No mock is used."
        )
        html = render_html_report([report])
        assert "<ul>" in html
        assert "<li>" in html
        assert "system time" in html

    def test_html_report_renders_numbered_solution_as_ol(self):
        from skills.flaky_test_analysis.html_report import render_html_report
        report = self._make_report(
            recommended_solution="1. Add freezegun dependency.\n2. Decorate the test.\n3. Rerun CI."
        )
        html = render_html_report([report])
        assert "<ol>" in html
        assert "freezegun" in html

    def test_pointwise_html_helper_converts_bullets(self):
        from skills.flaky_test_analysis.html_report import _pointwise_html
        text = "- First point\n- Second point\n- Third point"
        html = _pointwise_html(text)
        assert "<ul>" in html
        assert html.count("<li>") == 3

    def test_pointwise_html_helper_converts_numbered(self):
        from skills.flaky_test_analysis.html_report import _pointwise_html
        text = "1. Step one\n2. Step two\n3. Step three"
        html = _pointwise_html(text)
        assert "<ol>" in html
        assert html.count("<li>") == 3

    def test_pointwise_html_helper_falls_back_to_paragraph(self):
        from skills.flaky_test_analysis.html_report import _pointwise_html
        text = "This is plain prose without any list markers."
        html = _pointwise_html(text)
        assert "<p>" in html
        assert "plain prose" in html


# ===========================================================================
# Feature: GitHubClient exported from package; CLI args pass through
# ===========================================================================

class TestGitHubClientIntegration:
    """Package-level export and CLI wiring tests."""

    def test_github_client_exported_from_package(self):
        from skills.flaky_test_analysis import GitHubClient
        assert callable(GitHubClient)

    def test_skill_accepts_github_client_parameter(self):
        from skills.flaky_test_analysis import FlakyTestAnalysisSkill, GitHubClient
        mock_gh = MagicMock(spec=GitHubClient)
        skill = FlakyTestAnalysisSkill(github_client=mock_gh)
        assert skill._github is mock_gh

    def test_skill_accepts_github_token_parameter(self):
        from skills.flaky_test_analysis import FlakyTestAnalysisSkill
        skill = FlakyTestAnalysisSkill(github_token="my-pat", github_owner="nable-nc", github_repo="n-central")
        assert "my-pat" in skill._github._session.headers.get("Authorization", "")

    def test_cli_github_token_passed_to_skill(self):
        from run_flaky_analysis import main
        _FAKE_JIRA_ENV = {
            "JIRA_BASE_URL": "https://example.atlassian.net",
            "JIRA_USER_EMAIL": "ci@example.com",
            "JIRA_API_TOKEN": "fake-token",
        }
        mock_report = MagicMock()
        mock_report.formatted_report = "# Done"
        mock_report.flaky_metrics = []

        captured = {}
        original_init = __import__(
            "skills.flaky_test_analysis", fromlist=["FlakyTestAnalysisSkill"]
        ).FlakyTestAnalysisSkill.__init__

        def fake_init(self, **kwargs):
            captured.update(kwargs)
            original_init(self, **kwargs)

        with patch.dict("os.environ", _FAKE_JIRA_ENV), \
             patch("run_flaky_analysis.FlakyTestAnalysisSkill") as MockSkill:
            MockSkill.return_value.analyze_ticket.return_value = mock_report
            with pytest.raises(SystemExit):
                main([
                    "--jira-ticket", "NCCF-1",
                    "--no-ai", "--no-post",
                    "--github-token", "my-gh-token",
                    "--ncrepo-owner", "nable-nc",
                    "--ncrepo-repo", "n-central",
                ])

        _, kwargs = MockSkill.call_args
        assert kwargs.get("github_token") == "my-gh-token"
        assert kwargs.get("github_owner") == "nable-nc"
        assert kwargs.get("github_repo") == "n-central"


# ===========================================================================
# Feature: line-number annotation in extracted Robot test snippet
# ===========================================================================

class TestLineNumberAnnotation:
    """_extract_test_case annotates each line with its 1-based file line number."""

    _ROBOT_FILE = (
        "*** Settings ***\n"
        "Library    SeleniumLibrary\n\n"
        "*** Test Cases ***\n"
        "Verify Login\n"
        "    Open Browser    ${URL}    Chrome\n"
        "    Input Text    username    admin\n"
        "    Click Button    Submit\n\n"
        "Verify Logout\n"
        "    Click Link    Logout\n"
    )

    def test_snippet_contains_line_number_prefix(self):
        from skills.flaky_test_analysis.github_client import _extract_test_case
        result = _extract_test_case(self._ROBOT_FILE, "Verify Login")
        # Lines must have the  │  separator
        assert "│" in result

    def test_snippet_has_correct_line_number(self):
        from skills.flaky_test_analysis.github_client import _extract_test_case
        result = _extract_test_case(self._ROBOT_FILE, "Verify Login")
        # "Verify Login" is on line 5 of the file (1-based)
        assert "5 │ Verify Login" in result

    def test_fallback_excerpt_has_line_numbers(self):
        from skills.flaky_test_analysis.github_client import _extract_test_case
        result = _extract_test_case(self._ROBOT_FILE, "Does Not Exist")
        assert "1 │ *** Settings ***" in result

    def test_annotated_snippet_still_contains_keywords(self):
        from skills.flaky_test_analysis.github_client import _extract_test_case
        result = _extract_test_case(self._ROBOT_FILE, "Verify Login")
        # Content still findable within annotation
        assert "Open Browser" in result
        assert "Input Text" in result


# ===========================================================================
# Feature: failing_test_name and affected_line in report
# ===========================================================================

class TestFailingTestNameAndAffectedLine:
    """failing_test_name and affected_line are stored and rendered correctly."""

    def _make_jira_with_xml(self, test_name="Verify Login", status="FAIL"):
        xml = (
            f'<?xml version="1.0" encoding="UTF-8"?>'
            f'<robot generator="Robot" generated="20240101 00:00:00.000">'
            f'<suite name="TwoFactorAuthentication">'
            f'<test name="{test_name}">'
            f'<status status="{status}" message="Element not found"/>'
            f'</test>'
            f'</suite>'
            f'<statistics/><errors/></robot>'
        ).encode()

        attachments = [{
            "id": "1",
            "filename": "output.xml",
            "mimeType": "application/xml",
            "size": len(xml),
            "content": "https://example.atlassian.net/secure/attachment/1/output.xml",
        }]

        mock_jira = MagicMock()
        mock_jira.get_issue.return_value = {
            "key": "NCCF-99",
            "summary": "2FA login failure",
            "status": "Open",
            "description": "",
            "attachments": attachments,
            "comments": [],
        }
        mock_jira.download_attachment.return_value = xml
        return mock_jira

    def test_failing_test_name_stored_on_report(self):
        from skills.flaky_test_analysis import FlakyTestAnalysisSkill
        mock_jira = self._make_jira_with_xml("Verify Login")
        mock_github = MagicMock()
        mock_github.search_robot_test.return_value = ("tests/login.robot", "5 │ Verify Login\n6 │     Open Browser")
        skill = FlakyTestAnalysisSkill(jira_client=mock_jira, github_client=mock_github)
        report = skill.analyze_ticket("NCCF-99", use_ai=False, post_comment=False)
        assert report.failing_test_name == "Verify Login"

    def test_failing_test_name_appears_in_markdown_report(self):
        from skills.flaky_test_analysis import FlakyTestAnalysisSkill
        mock_jira = self._make_jira_with_xml("Verify 2FA Login")
        mock_github = MagicMock()
        mock_github.search_robot_test.return_value = ("", "")
        skill = FlakyTestAnalysisSkill(jira_client=mock_jira, github_client=mock_github)
        report = skill.analyze_ticket("NCCF-99", use_ai=False, post_comment=False)
        assert "Verify 2FA Login" in report.formatted_report

    def test_affected_line_stored_on_report_from_ai(self):
        from skills.flaky_test_analysis import FlakyTestAnalysisSkill
        import skills.flaky_test_analysis.skill as skill_module
        mock_jira = self._make_jira_with_xml("Verify Login")
        mock_github = MagicMock()
        mock_github.search_robot_test.return_value = ("tests/login.robot", "5 │ Verify Login\n6 │     Click Button")
        fake_openai = MagicMock()
        choice = MagicMock()
        choice.message.content = (
            "**Root Cause:**\n- Button ID changed.\n\n"
            "**Recommended Solution:**\n1. Update the button locator.\n\n"
            "**Affected Line:** `6 │     Click Button    Submit` — locator outdated\n\n"
            "**Code Snippet:** N/A"
        )
        fake_openai.OpenAI.return_value.chat.completions.create.return_value.choices = [choice]
        skill = FlakyTestAnalysisSkill(
            openai_api_key="sk-test",
            jira_client=mock_jira,
            github_client=mock_github,
        )
        with patch.object(skill_module, "_ANTHROPIC_AVAILABLE", False), \
             patch.object(skill_module, "_OPENAI_AVAILABLE", True), \
             patch.object(skill_module, "_openai", fake_openai, create=True):
            report = skill.analyze_ticket("NCCF-99", use_ai=True, post_comment=False)
        assert report.affected_line != ""
        assert "Click Button" in report.affected_line or "6" in report.affected_line

    def test_affected_line_appears_in_markdown_report(self):
        from skills.flaky_test_analysis import FlakyTestAnalysisSkill
        import skills.flaky_test_analysis.skill as skill_module
        mock_jira = self._make_jira_with_xml("Verify Login")
        mock_github = MagicMock()
        mock_github.search_robot_test.return_value = ("tests/login.robot", "5 │ Verify Login")
        fake_openai = MagicMock()
        choice = MagicMock()
        choice.message.content = (
            "**Root Cause:**\n- Element not found.\n\n"
            "**Recommended Solution:**\n1. Fix locator.\n\n"
            "**Affected Line:** `7 │     Input Text    username    admin` — field renamed\n\n"
            "**Code Snippet:** N/A"
        )
        fake_openai.OpenAI.return_value.chat.completions.create.return_value.choices = [choice]
        skill = FlakyTestAnalysisSkill(
            openai_api_key="sk-test",
            jira_client=mock_jira,
            github_client=mock_github,
        )
        with patch.object(skill_module, "_ANTHROPIC_AVAILABLE", False), \
             patch.object(skill_module, "_OPENAI_AVAILABLE", True), \
             patch.object(skill_module, "_openai", fake_openai, create=True):
            report = skill.analyze_ticket("NCCF-99", use_ai=True, post_comment=False)
        assert "📍 Affected Line" in report.formatted_report

    def test_no_affected_line_section_when_ai_not_used(self):
        from skills.flaky_test_analysis import FlakyTestAnalysisSkill
        mock_jira = self._make_jira_with_xml("Verify Login")
        mock_github = MagicMock()
        mock_github.search_robot_test.return_value = ("", "")
        skill = FlakyTestAnalysisSkill(jira_client=mock_jira, github_client=mock_github)
        report = skill.analyze_ticket("NCCF-99", use_ai=False, post_comment=False)
        assert "📍 Affected Line" not in report.formatted_report


# ===========================================================================
# Feature: affected_line section in HTML report
# ===========================================================================

class TestHtmlReportAffectedLine:
    """HTML report renders affected_line correctly."""

    def _make_report(self, affected_line="", failing_test_name=""):
        from skills.flaky_test_analysis import TicketAnalysisReport
        return TicketAnalysisReport(
            issue_key="NCCF-1",
            summary="Test",
            status="Open",
            affected_line=affected_line,
            failing_test_name=failing_test_name,
            formatted_report="",
        )

    def test_html_report_renders_affected_line(self):
        from skills.flaky_test_analysis.html_report import render_html_report
        report = self._make_report(
            affected_line="42 │     Click Button    Submit — locator outdated"
        )
        html = render_html_report([report])
        assert "Affected Line" in html
        assert "Click Button" in html

    def test_html_report_omits_affected_line_when_empty(self):
        from skills.flaky_test_analysis.html_report import render_html_report
        report = self._make_report()
        html = render_html_report([report])
        assert "Affected Line" not in html

    def test_html_report_renders_failing_test_name_in_meta_table(self):
        from skills.flaky_test_analysis.html_report import render_html_report
        report = self._make_report(failing_test_name="Verify 2FA Login")
        html = render_html_report([report])
        assert "Failing Test" in html
        assert "Verify 2FA Login" in html

    def test_html_report_omits_failing_test_row_when_empty(self):
        from skills.flaky_test_analysis.html_report import render_html_report
        report = self._make_report()
        html = render_html_report([report])
        # The "Failing Test" row should not appear when the field is empty
        assert "Failing Test" not in html


# ===========================================================================
# Feature: _parse_ai_response handles four-section response
# ===========================================================================

class TestParseAiResponseFourSections:
    """_parse_ai_response correctly extracts all four sections."""

    def test_extracts_all_four_sections(self):
        from skills.flaky_test_analysis.skill import FlakyTestAnalysisSkill
        response = (
            "**Root Cause:**\n- Timer depends on wall clock.\n- No mocking used.\n\n"
            "**Recommended Solution:**\n1. Add freezegun.\n2. Decorate test.\n\n"
            "**Affected Line:** `7 │     time.sleep(5)` — hardcoded sleep causes flakiness\n\n"
            "**Code Snippet:**\n```python\n@freeze_time('2024-01-01')\ndef test_fn():\n    pass\n```"
        )
        rc, sol, al, snippet = FlakyTestAnalysisSkill._parse_ai_response(response)
        assert "wall clock" in rc
        assert "freezegun" in sol
        assert "sleep" in al
        assert "freeze_time" in snippet

    def test_affected_line_empty_when_na(self):
        from skills.flaky_test_analysis.skill import FlakyTestAnalysisSkill
        response = (
            "**Root Cause:** Config problem.\n\n"
            "**Recommended Solution:** Fix config.\n\n"
            "**Affected Line:** N/A\n\n"
            "**Code Snippet:** N/A"
        )
        _rc, _sol, al, snippet = FlakyTestAnalysisSkill._parse_ai_response(response)
        assert al == ""
        assert snippet == ""

    def test_affected_line_empty_when_missing(self):
        from skills.flaky_test_analysis.skill import FlakyTestAnalysisSkill
        response = (
            "**Root Cause:** Network error.\n\n"
            "**Recommended Solution:** Add retry.\n\n"
            "**Code Snippet:** N/A"
        )
        _rc, _sol, al, snippet = FlakyTestAnalysisSkill._parse_ai_response(response)
        assert al == ""


# ===========================================================================
# Feature: prompt includes failing_test_name and Affected Line instruction
# ===========================================================================

class TestPromptFailingTestAndAffectedLine:
    """The AI prompt includes the failing test name and Affected Line section."""

    def _make_skill(self):
        from skills.flaky_test_analysis import FlakyTestAnalysisSkill
        return FlakyTestAnalysisSkill()

    def test_prompt_includes_failing_test_name(self):
        skill = self._make_skill()
        issue = {"key": "NCCF-1", "summary": "Test", "status": "Open",
                 "description": "", "comments": []}
        prompt = skill._build_root_cause_prompt(
            issue, [], [], [], failing_test_name="Verify 2FA Login"
        )
        assert "Verify 2FA Login" in prompt

    def test_prompt_includes_affected_line_instruction(self):
        skill = self._make_skill()
        issue = {"key": "NCCF-1", "summary": "Test", "status": "Open",
                 "description": "", "comments": []}
        prompt = skill._build_root_cause_prompt(issue, [], [], [])
        assert "Affected Line" in prompt

    def test_prompt_forbids_chain_of_thought(self):
        skill = self._make_skill()
        issue = {"key": "NCCF-1", "summary": "Test", "status": "Open",
                 "description": "", "comments": []}
        prompt = skill._build_root_cause_prompt(issue, [], [], [])
        # The prompt must explicitly forbid chain-of-thought / step numbering
        assert "chain-of-thought" in prompt.lower() or "reasoning" in prompt.lower()

    def test_prompt_source_includes_line_prefix_note(self):
        skill = self._make_skill()
        issue = {"key": "NCCF-1", "summary": "Test", "status": "Open",
                 "description": "", "comments": []}
        prompt = skill._build_root_cause_prompt(
            issue, [], [], [],
            robot_source_file="tests/login.robot",
            robot_source_snippet="5 │ Verify Login\n6 │     Open Browser",
        )
        assert "line number" in prompt.lower() or "│" in prompt


# ===========================================================================
# Feature: robot_source_file shown in report header; code-snippet file guidance
# ===========================================================================

class TestRobotTestFileInHeader:
    """robot_source_file filename appears in the Markdown report header."""

    def _make_skill(self):
        from skills.flaky_test_analysis import FlakyTestAnalysisSkill
        return FlakyTestAnalysisSkill()

    def _minimal_issue(self):
        return {
            "key": "NCCF-1",
            "summary": "Test",
            "status": "Open",
            "description": "",
            "comments": [],
        }

    def test_robot_test_file_shown_in_header_when_source_file_known(self):
        """When robot_source_file is set the filename appears in the header."""
        skill = self._make_skill()
        report = skill._format_ticket_report(
            self._minimal_issue(),
            attachments=[],
            robot_runs=[],
            flaky_metrics=[],
            root_cause="Timer drift.",
            recommended_solution="Fix it.",
            robot_source_file="tests/two_factor_authentication.robot",
            failing_test_name="Two Factor Authentication",
            use_ai=False,
        )
        assert "Robot Test File" in report
        assert "two_factor_authentication.robot" in report

    def test_robot_test_file_absent_from_header_when_not_set(self):
        """When robot_source_file is empty the 'Robot Test File' row is omitted."""
        skill = self._make_skill()
        report = skill._format_ticket_report(
            self._minimal_issue(),
            attachments=[],
            robot_runs=[],
            flaky_metrics=[],
            root_cause="Timer drift.",
            recommended_solution="Fix it.",
            robot_source_file="",
            failing_test_name="Verify Login",
            use_ai=False,
        )
        assert "Robot Test File" not in report

    def test_only_basename_shown_not_full_path(self):
        """Only the filename portion of the path is shown, not the full path."""
        skill = self._make_skill()
        report = skill._format_ticket_report(
            self._minimal_issue(),
            attachments=[],
            robot_runs=[],
            flaky_metrics=[],
            root_cause="x",
            recommended_solution="y",
            robot_source_file="src/tests/suites/login.robot",
            use_ai=False,
        )
        assert "login.robot" in report
        assert "src/tests/suites/login.robot" not in report


class TestCodeSnippetFileGuidance:
    """'Where to apply this' guidance is added above the code snippet."""

    def _make_skill(self):
        from skills.flaky_test_analysis import FlakyTestAnalysisSkill
        return FlakyTestAnalysisSkill()

    def _minimal_issue(self):
        return {
            "key": "NCCF-1", "summary": "Test", "status": "Open",
            "description": "", "comments": [],
        }

    def _format(self, **kwargs):
        skill = self._make_skill()
        defaults = dict(
            attachments=[], robot_runs=[], flaky_metrics=[],
            root_cause="Root.", recommended_solution="Fix.", use_ai=False,
        )
        defaults.update(kwargs)
        return skill._format_ticket_report(self._minimal_issue(), **defaults)

    def test_python_snippet_with_source_file_shows_library_guidance(self):
        """Python snippet + known source file → library/resource guidance mentioning the file."""
        report = self._format(
            code_snippet="```python\nimport time\nx = 1\n```",
            robot_source_file="tests/two_factor_authentication.robot",
            failing_test_name="Two Factor Authentication",
        )
        assert "Where to apply this" in report
        assert "two_factor_authentication.robot" in report
        assert "Library" in report or "library" in report

    def test_robot_snippet_with_source_file_shows_direct_file_guidance(self):
        """Robot snippet + known source file → direct 'apply in <file>' note."""
        report = self._format(
            code_snippet="```robot\nVerify Login\n    Open Browser\n```",
            robot_source_file="tests/login.robot",
            failing_test_name="Verify Login",
        )
        assert "Where to apply this" in report
        assert "login.robot" in report
        # Should NOT mention library imports for a .robot snippet
        assert "Library" not in report

    def test_python_snippet_without_source_file_infers_robot_filename(self):
        """Python snippet + no source file → guidance using {failing_test_name}.robot."""
        report = self._format(
            code_snippet="```python\nx = 1\n```",
            robot_source_file="",
            failing_test_name="Two Factor Authentication",
        )
        assert "Where to apply this" in report
        assert "Two Factor Authentication.robot" in report

    def test_no_guidance_when_no_file_info(self):
        """When neither robot_source_file nor failing_test_name is set, no guidance is added."""
        report = self._format(
            code_snippet="```python\nx = 1\n```",
            robot_source_file="",
            failing_test_name="",
        )
        # Section header is still present
        assert "Corrected Code Snippet" in report
        # But no "Where to apply this" noise
        assert "Where to apply this" not in report

    def test_na_snippet_produces_no_snippet_section(self):
        """'N/A' snippet must not generate a Corrected Code Snippet section."""
        report = self._format(
            code_snippet="N/A",
            robot_source_file="tests/login.robot",
            failing_test_name="Verify Login",
        )
        assert "Corrected Code Snippet" not in report


class TestHtmlRobotTestFileAndSnippetGuidance:
    """HTML report shows Robot Test File in meta table and file guidance for snippets."""

    def _make_report(self, robot_source_file="", failing_test_name="", code_snippet=""):
        from skills.flaky_test_analysis import TicketAnalysisReport
        return TicketAnalysisReport(
            issue_key="NCCF-1",
            summary="Test",
            status="Open",
            robot_source_file=robot_source_file,
            failing_test_name=failing_test_name,
            code_snippet=code_snippet,
            formatted_report="",
        )

    def test_html_shows_robot_test_file_row_when_set(self):
        from skills.flaky_test_analysis.html_report import render_html_report
        report = self._make_report(
            robot_source_file="tests/two_factor_authentication.robot"
        )
        html = render_html_report([report])
        assert "Robot Test File" in html
        assert "two_factor_authentication.robot" in html

    def test_html_omits_robot_test_file_row_when_empty(self):
        from skills.flaky_test_analysis.html_report import render_html_report
        report = self._make_report()
        html = render_html_report([report])
        assert "Robot Test File" not in html

    def test_html_python_snippet_with_source_file_shows_library_guidance(self):
        from skills.flaky_test_analysis.html_report import render_html_report
        report = self._make_report(
            robot_source_file="tests/login.robot",
            failing_test_name="Verify Login",
            code_snippet="```python\nimport time\n```",
        )
        html = render_html_report([report])
        assert "Where to apply this" in html
        assert "login.robot" in html
        assert "Library" in html or "library" in html

    def test_html_robot_snippet_with_source_file_shows_direct_guidance(self):
        from skills.flaky_test_analysis.html_report import render_html_report
        report = self._make_report(
            robot_source_file="tests/login.robot",
            failing_test_name="Verify Login",
            code_snippet="```robot\nVerify Login\n    Open Browser\n```",
        )
        html = render_html_report([report])
        assert "Where to apply this" in html
        assert "login.robot" in html

    def test_html_python_snippet_infers_robot_file_from_test_name(self):
        from skills.flaky_test_analysis.html_report import render_html_report
        report = self._make_report(
            robot_source_file="",
            failing_test_name="Two Factor Authentication",
            code_snippet="```python\nx = 1\n```",
        )
        html = render_html_report([report])
        assert "Where to apply this" in html
        assert "Two Factor Authentication.robot" in html

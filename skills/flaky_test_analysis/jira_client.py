"""
jira_client.py – Post flaky-test analysis results to Jira.

Supports two modes:
  1. REST API  – direct HTTPS calls to the Jira REST v2/v3 endpoint.
  2. MCP       – delegates to an MCP connector (stub; implement as needed).

Configuration is driven entirely by environment variables so that credentials
are never hard-coded.

Environment variables
---------------------
JIRA_BASE_URL       Base URL of the Jira instance (e.g. https://myorg.atlassian.net)
JIRA_USER_EMAIL     Atlassian account e-mail for basic auth
JIRA_API_TOKEN      Jira API token (https://id.atlassian.com/manage-profile/security)
JIRA_PROJECT_KEY    Default project key (e.g. OPS, QA)
JIRA_AUTH_MODE      "rest" (default) or "mcp"
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

try:
    import requests as _requests
    _REQUESTS_AVAILABLE = True
except ImportError:
    _REQUESTS_AVAILABLE = False


class JiraClient:
    """Post formatted flaky-test analysis as Jira comments."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        user_email: Optional[str] = None,
        api_token: Optional[str] = None,
        project_key: Optional[str] = None,
        auth_mode: str = "rest",
    ) -> None:
        self.base_url = (base_url or os.environ.get("JIRA_BASE_URL", "")).rstrip("/")
        self.user_email = user_email or os.environ.get("JIRA_USER_EMAIL", "")
        self.api_token = api_token or os.environ.get("JIRA_API_TOKEN", "")
        self.project_key = project_key or os.environ.get("JIRA_PROJECT_KEY", "")
        self.auth_mode = (auth_mode or os.environ.get("JIRA_AUTH_MODE", "rest")).lower()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def post_comment(self, issue_key: str, body: str) -> Dict[str, Any]:
        """
        Add *body* as a comment on the Jira issue identified by *issue_key*.

        Returns the Jira API response payload as a dict.
        Raises ``RuntimeError`` on misconfiguration or HTTP error.
        """
        if self.auth_mode == "mcp":
            return self._post_via_mcp(issue_key, body)
        return self._post_via_rest(issue_key, body)

    def post_analysis_report(
        self,
        issue_key: str,
        report: str,
    ) -> Dict[str, Any]:
        """
        Convenience wrapper that posts a pre-formatted analysis report string
        as a Jira comment.
        """
        return self.post_comment(issue_key, report)

    # ------------------------------------------------------------------
    # REST implementation
    # ------------------------------------------------------------------

    def _post_via_rest(self, issue_key: str, body: str) -> Dict[str, Any]:
        if not _REQUESTS_AVAILABLE:
            raise RuntimeError(
                "The 'requests' library is required for REST mode. "
                "Install it with: pip install requests"
            )
        self._validate_rest_config()

        url = f"{self.base_url}/rest/api/2/issue/{issue_key}/comment"
        payload = {"body": body}
        auth = (self.user_email, self.api_token)

        response = _requests.post(url, json=payload, auth=auth, timeout=30)
        try:
            response.raise_for_status()
        except Exception as exc:
            raise RuntimeError(
                f"Jira API error for issue {issue_key}: "
                f"{response.status_code} – {response.text}"
            ) from exc

        logger.info("Comment posted to Jira issue %s", issue_key)
        return response.json()

    def _validate_rest_config(self) -> None:
        missing = [
            name
            for name, value in [
                ("JIRA_BASE_URL", self.base_url),
                ("JIRA_USER_EMAIL", self.user_email),
                ("JIRA_API_TOKEN", self.api_token),
            ]
            if not value
        ]
        if missing:
            raise RuntimeError(
                "Missing Jira configuration. Set environment variables: "
                + ", ".join(missing)
            )

    # ------------------------------------------------------------------
    # MCP stub implementation
    # ------------------------------------------------------------------

    def _post_via_mcp(self, issue_key: str, body: str) -> Dict[str, Any]:
        """
        Stub for MCP connector integration.

        Replace this implementation with your organisation's MCP client call,
        for example:

            from mcp_client import MCPConnector
            connector = MCPConnector()
            return connector.call_tool(
                tool_name="jira_add_comment",
                params={"issue_key": issue_key, "body": body},
            )
        """
        logger.warning(
            "MCP mode is a stub. Implement _post_via_mcp() to integrate "
            "with your MCP connector. Would have posted comment to %s",
            issue_key,
        )
        return {"status": "stub", "issue_key": issue_key, "body_length": len(body)}

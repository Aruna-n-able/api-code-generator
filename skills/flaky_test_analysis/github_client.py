"""
github_client.py – Lightweight GitHub REST API client.

Used to fetch failing Robot Framework test source files from the n-central
repository (``nable-nc/n-central`` by default) so that the analysis report
can include the actual test code alongside the AI's suggested correction.

Authentication
--------------
Pass a GitHub personal-access token (PAT) via the ``token`` constructor
parameter or set the ``GITHUB_TOKEN`` environment variable.  Without a token
the GitHub Search API allows only 10 unauthenticated requests per minute;
with a token the limit rises to 30 searches per minute (and 5 000 general API
calls per hour).

GitHub username / password authentication is not supported by the GitHub API
since 2021; a token is the required mechanism.
"""

from __future__ import annotations

import base64
import logging
import os
import re
from typing import Optional, Tuple

import requests

logger = logging.getLogger(__name__)

_GITHUB_API_BASE = "https://api.github.com"
_DEFAULT_OWNER = "nable-nc"
_DEFAULT_REPO = "n-central"


class GitHubClient:
    """Minimal GitHub REST API client for fetching Robot Framework test files.

    Parameters
    ----------
    token:
        Personal access token (PAT) or GitHub Actions ``GITHUB_TOKEN``.
        Falls back to the ``GITHUB_TOKEN`` environment variable.
        When not set, requests are made unauthenticated (lower rate limit –
        10 Code Search calls per minute).
    owner:
        GitHub repository owner / organisation (default: ``nable-nc``).
    repo:
        GitHub repository name (default: ``n-central``).
    """

    def __init__(
        self,
        token: Optional[str] = None,
        owner: str = _DEFAULT_OWNER,
        repo: str = _DEFAULT_REPO,
    ) -> None:
        self._token = token or os.environ.get("GITHUB_TOKEN", "")
        self._owner = owner
        self._repo = repo
        self._session = requests.Session()
        self._session.headers.update(
            {
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            }
        )
        if self._token:
            self._session.headers["Authorization"] = f"Bearer {self._token}"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def search_robot_test(self, test_name: str) -> Tuple[str, str]:
        """Search the repository for a Robot Framework test by name.

        Uses the GitHub Code Search API to find ``.robot`` files in the
        configured repository that contain *test_name*, then fetches the
        best-matching file and extracts the relevant test-case block.

        Parameters
        ----------
        test_name:
            The Robot Framework test case name to search for (e.g.
            ``Verify Login With Valid Credentials``).

        Returns
        -------
        Tuple[str, str]
            ``(file_path, test_case_snippet)`` where *file_path* is the
            repository-relative path of the file (e.g.
            ``tests/login/login.robot``) and *test_case_snippet* is the
            extracted test-case block.  Both strings are empty when nothing
            is found or when the GitHub API is unreachable.
        """
        query = f'"{test_name}" repo:{self._owner}/{self._repo} extension:robot'
        url = f"{_GITHUB_API_BASE}/search/code"
        try:
            resp = self._session.get(url, params={"q": query}, timeout=15)
            resp.raise_for_status()
        except Exception as exc:
            logger.warning(
                "GitHub Code Search failed for test '%s': %s", test_name, exc
            )
            return "", ""

        data = resp.json()
        items = data.get("items", [])
        if not items:
            logger.info(
                "No .robot file found for test '%s' in %s/%s",
                test_name,
                self._owner,
                self._repo,
            )
            return "", ""

        # Take the first result (highest relevance per GitHub ranking)
        best = items[0]
        file_path: str = best.get("path", "")
        logger.info("Found Robot test in %s", file_path)

        content = self.get_file_content(file_path)
        if not content:
            return file_path, ""

        snippet = _extract_test_case(content, test_name)
        return file_path, snippet

    def get_file_content(self, path: str) -> str:
        """Fetch the raw text content of a file from the repository.

        Parameters
        ----------
        path:
            Repository-relative file path (e.g.
            ``tests/suite/mytest.robot``).

        Returns
        -------
        str
            The decoded file content, or an empty string on error.
        """
        url = (
            f"{_GITHUB_API_BASE}/repos/{self._owner}/{self._repo}/contents/{path}"
        )
        try:
            resp = self._session.get(url, timeout=15)
            resp.raise_for_status()
        except Exception as exc:
            logger.warning("GitHub file fetch failed for '%s': %s", path, exc)
            return ""

        data = resp.json()
        encoded = data.get("content", "")
        if not encoded:
            return ""

        try:
            return base64.b64decode(encoded).decode("utf-8", errors="replace")
        except Exception as exc:
            logger.warning("Failed to decode content of '%s': %s", path, exc)
            return ""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _extract_test_case(file_content: str, test_name: str) -> str:
    """Extract a single test-case block from a Robot Framework ``.robot`` file.

    Robot Framework test cases are defined under a ``*** Test Cases ***``
    section.  Each case starts at column 0 with its name (not preceded by
    whitespace) and its body is indented.  A test ends when the next
    non-indented line appears (another test name) or when a new section
    header (``*** … ***``) is encountered.

    The name match is case-insensitive and treats runs of underscores and
    spaces as equivalent, following Robot Framework's own convention.

    Parameters
    ----------
    file_content:
        Full text of the ``.robot`` file.
    test_name:
        The test case name to find.

    Returns
    -------
    str
        The extracted test-case block (name line + body).  When the specific
        test cannot be found by name, the first 3 000 characters of the file
        are returned as a fallback.
    """

    def _normalise(s: str) -> str:
        return re.sub(r"[\s_]+", " ", s).strip().lower()

    norm_name = _normalise(test_name)
    lines = file_content.splitlines(keepends=True)

    in_test_cases_section = False
    test_start: Optional[int] = None
    test_end: Optional[int] = None

    # Matches Robot section headers like  *** Test Cases ***
    section_re = re.compile(r"^\*+\s*([\w][\w\s]*?)\s*\*+")
    # A test-case name line is non-indented, not a comment, not a variable
    test_name_re = re.compile(r"^(?!\s)(?![*#$@&])(.+)")

    for i, line in enumerate(lines):
        stripped = line.rstrip("\n").rstrip()

        sec_match = section_re.match(stripped)
        if sec_match:
            section_label = sec_match.group(1).strip().lower()
            if "test case" in section_label:
                in_test_cases_section = True
                if test_start is not None:
                    test_end = i
                    break
            else:
                if test_start is not None:
                    test_end = i
                    break
                in_test_cases_section = False
            continue

        if not in_test_cases_section:
            continue

        tc_match = test_name_re.match(stripped)
        if tc_match:
            candidate = _normalise(tc_match.group(1))
            if candidate == norm_name:
                test_start = i
            elif test_start is not None:
                test_end = i
                break

    if test_start is None:
        logger.info(
            "Test case '%s' not found by name; returning file excerpt", test_name
        )
        return file_content[:3000]

    if test_end is None:
        test_end = len(lines)

    return "".join(lines[test_start:test_end]).rstrip()

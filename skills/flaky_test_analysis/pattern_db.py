"""
pattern_db.py – Load and query the flaky-test pattern knowledge base.

Patterns are stored in ``patterns/flaky_patterns.yaml``.  Each pattern
describes detection signals (keywords, error regexes) and a fix template.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Optional

import yaml

from .robot_parser import TestResult

# ---------------------------------------------------------------------------
# Default path to the bundled patterns file
# ---------------------------------------------------------------------------
_DEFAULT_PATTERNS_FILE = Path(__file__).parent / "patterns" / "flaky_patterns.yaml"


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

class Pattern:
    """A single flaky-test pattern definition."""

    def __init__(self, data: dict) -> None:
        self.id: str = data["id"]
        self.name: str = data["name"]
        self.description: str = data.get("description", "")
        self.keywords: List[str] = [k.lower() for k in data.get("keywords", [])]
        self.robot_keywords: List[str] = [k.lower() for k in data.get("robot_keywords", [])]
        self.error_patterns: List[re.Pattern] = [
            re.compile(p, re.IGNORECASE) for p in data.get("error_patterns", [])
        ]
        self.fix_template: str = data.get("fix_template", "")
        self.severity_weight: int = data.get("severity_weight", 1)

    def matches(self, test: TestResult) -> bool:
        """Return True if this pattern applies to the given test result."""
        haystack = (test.name + " " + test.message + " " + test.suite).lower()

        # Check plain keywords
        for kw in self.keywords:
            if kw in haystack:
                return True

        # Check Robot Framework keyword names
        for rkw in self.robot_keywords:
            if rkw in haystack:
                return True

        # Check regex error patterns against the failure message
        for pattern in self.error_patterns:
            if pattern.search(test.message):
                return True

        return False


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

class PatternDatabase:
    """Load patterns from YAML and match them against test results."""

    def __init__(self, patterns_file: str | Path = _DEFAULT_PATTERNS_FILE) -> None:
        self._patterns: List[Pattern] = self._load(Path(patterns_file))

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def match(self, test: TestResult) -> List[Pattern]:
        """Return all patterns that match the given (failed) test result."""
        return [p for p in self._patterns if p.matches(test)]

    def get_pattern(self, pattern_id: str) -> Optional[Pattern]:
        """Look up a pattern by its unique identifier."""
        for p in self._patterns:
            if p.id == pattern_id:
                return p
        return None

    @property
    def all_patterns(self) -> List[Pattern]:
        return list(self._patterns)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _load(path: Path) -> List[Pattern]:
        with path.open(encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        return [Pattern(entry) for entry in data.get("patterns", [])]

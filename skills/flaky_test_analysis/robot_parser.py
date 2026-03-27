"""
robot_parser.py – Parse Robot Framework output.xml artefacts.

Extracts per-test execution data (status, messages, duration, timestamps)
from one or more output.xml files and returns a normalised list of
TestResult objects that the rest of the pipeline can consume.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class TestResult:
    """Represents the outcome of a single Robot Framework test execution."""

    name: str
    suite: str
    status: str                   # PASS | FAIL | SKIP
    message: str                  # failure message, empty when passing
    start_time: Optional[datetime]
    end_time: Optional[datetime]
    elapsed_ms: float             # wall-clock duration in milliseconds
    tags: List[str] = field(default_factory=list)
    source_file: str = ""         # path to the originating output.xml


@dataclass
class ParsedRun:
    """All test results from a single output.xml file."""

    source_file: str
    generated: Optional[datetime]
    tests: List[TestResult] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

_DT_FORMAT = "%Y%m%d %H:%M:%S.%f"


def _parse_dt(value: Optional[str]) -> Optional[datetime]:
    """Parse a Robot Framework datetime string into a Python datetime."""
    if not value or value == "N/A":
        return None
    try:
        return datetime.strptime(value, _DT_FORMAT)
    except ValueError:
        # Some older RF versions omit milliseconds
        try:
            return datetime.strptime(value, "%Y%m%d %H:%M:%S")
        except ValueError:
            return None


def _elapsed(start: Optional[datetime], end: Optional[datetime]) -> float:
    """Return elapsed milliseconds between two datetimes, or 0.0."""
    if start and end:
        return (end - start).total_seconds() * 1000
    return 0.0


def _build_parent_map(root: ET.Element) -> Dict[int, ET.Element]:
    """Build and return a child-id to parent mapping for an element tree."""
    parent_map: Dict[int, ET.Element] = {}
    for parent in root.iter():
        for child in parent:
            parent_map[id(child)] = parent
    return parent_map


class RobotOutputParser:
    """Parse one or more Robot Framework ``output.xml`` files."""

    def parse_file(self, path: str | Path) -> ParsedRun:
        """Parse a single ``output.xml`` file and return a :class:`ParsedRun`."""
        path = Path(path)
        tree = ET.parse(path)
        root = tree.getroot()

        # Build the parent map once per file so each call is independent and
        # thread-safe (no shared mutable state at module level).
        parent_map = _build_parent_map(root)

        generated = _parse_dt(root.get("generated"))
        run = ParsedRun(source_file=str(path), generated=generated)

        for test_elem in root.iter("test"):
            result = self._parse_test(test_elem, parent_map, source_file=str(path))
            if result is not None:
                run.tests.append(result)

        return run

    def parse_files(self, paths: List[str | Path]) -> List[ParsedRun]:
        """Parse multiple ``output.xml`` files and return a list of runs."""
        return [self.parse_file(p) for p in paths]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _parse_test(
        self,
        elem: ET.Element,
        parent_map: Dict[int, ET.Element],
        source_file: str,
    ) -> Optional[TestResult]:
        """Extract a :class:`TestResult` from a ``<test>`` XML element."""
        name = elem.get("name", "")
        suite = self._find_suite_name(elem, parent_map)

        status_elem = elem.find("status")
        if status_elem is None:
            return None

        status = status_elem.get("status", "FAIL")
        message = (status_elem.text or "").strip()
        start_time = _parse_dt(status_elem.get("starttime") or status_elem.get("start"))
        end_time = _parse_dt(status_elem.get("endtime") or status_elem.get("end"))
        elapsed = _elapsed(start_time, end_time)

        tags: List[str] = []
        for tag_elem in elem.findall("tag"):
            if tag_elem.text:
                tags.append(tag_elem.text.strip())

        return TestResult(
            name=name,
            suite=suite,
            status=status,
            message=message,
            start_time=start_time,
            end_time=end_time,
            elapsed_ms=elapsed,
            tags=tags,
            source_file=source_file,
        )

    @staticmethod
    def _find_suite_name(
        elem: ET.Element,
        parent_map: Dict[int, ET.Element],
    ) -> str:
        """Walk up the element tree to build the suite path."""
        parts: List[str] = []
        current = elem
        while True:
            parent = parent_map.get(id(current))
            if parent is None:
                break
            if parent.tag == "suite":
                parts.insert(0, parent.get("name", ""))
            current = parent
        return " > ".join(filter(None, parts)) or "Unknown Suite"

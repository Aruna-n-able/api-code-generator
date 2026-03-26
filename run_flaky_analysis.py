#!/usr/bin/env python3
"""
run_flaky_analysis.py – Command-line entry point for the Flaky Test Analysis Skill.

Usage
-----
    python run_flaky_analysis.py --robot-output output.xml [output2.xml ...]
                                 [--jira-issue PROJ-123]
                                 [--no-ai]
                                 [--output-file report.md]

Examples
--------
    # Analyse a single run (no AI, no Jira)
    python run_flaky_analysis.py --robot-output tests/fixtures/sample_output.xml --no-ai

    # Analyse multiple historical runs
    python run_flaky_analysis.py \\
        --robot-output run1/output.xml run2/output.xml run3/output.xml

    # Full pipeline: AI summary + Jira comment
    python run_flaky_analysis.py \\
        --robot-output output.xml \\
        --jira-issue OPS-42

    # Save report to file
    python run_flaky_analysis.py \\
        --robot-output output.xml \\
        --no-ai \\
        --output-file flaky_report.md
"""

import argparse
import logging
import sys
from pathlib import Path

# Allow running as a top-level script without installing the package
sys.path.insert(0, str(Path(__file__).parent))

from skills.flaky_test_analysis import FlakyTestAnalysisSkill


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Flaky Test Analysis Skill for Robot Framework",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--robot-output",
        nargs="+",
        required=True,
        metavar="FILE",
        help="Path(s) to Robot Framework output.xml file(s). "
             "Provide multiple files from different CI runs to detect flakiness.",
    )
    parser.add_argument(
        "--jira-issue",
        metavar="KEY",
        default=None,
        help="Jira issue key to post the analysis report to (e.g. OPS-42). "
             "Requires JIRA_* environment variables to be set.",
    )
    parser.add_argument(
        "--no-ai",
        action="store_true",
        default=False,
        help="Skip the Claude AI summary step. "
             "Useful when ANTHROPIC_API_KEY is not set or for offline use.",
    )
    parser.add_argument(
        "--output-file",
        metavar="PATH",
        default=None,
        help="Write the formatted report to this file (Markdown). "
             "The report is always printed to stdout as well.",
    )
    parser.add_argument(
        "--model",
        default="claude-3-5-sonnet-20241022",
        help="Claude model to use for AI summarisation (default: claude-3-5-sonnet-20241022).",
    )
    parser.add_argument(
        "--patterns-file",
        metavar="PATH",
        default=None,
        help="Path to a custom flaky_patterns.yaml file. "
             "Uses the bundled patterns by default.",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        default=False,
        help="Enable verbose logging.",
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s – %(message)s",
    )

    # Validate that all provided paths exist
    missing = [p for p in args.robot_output if not Path(p).exists()]
    if missing:
        for p in missing:
            print(f"ERROR: File not found: {p}", file=sys.stderr)
        sys.exit(1)

    skill = FlakyTestAnalysisSkill(
        claude_model=args.model,
        patterns_file=args.patterns_file,
    )

    report = skill.run_analysis(
        output_xml_paths=args.robot_output,
        jira_issue_key=args.jira_issue,
        use_ai_summary=not args.no_ai,
    )

    print(report.formatted_report)

    if args.output_file:
        output_path = Path(args.output_file)
        output_path.write_text(report.formatted_report, encoding="utf-8")
        print(f"\nReport written to: {output_path}", file=sys.stderr)

    # Exit with non-zero code if flaky tests were found
    flaky_count = sum(
        1 for m in report.metrics if m.flakiness_score != "Stable"
    )
    sys.exit(1 if flaky_count > 0 else 0)


if __name__ == "__main__":
    main()

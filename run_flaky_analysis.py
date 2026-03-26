#!/usr/bin/env python3
"""
run_flaky_analysis.py – Command-line entry point for the Flaky Test Analysis Skill.

Two modes are available:

MODE 1 – Local file analysis (classic)
---------------------------------------
    python run_flaky_analysis.py --robot-output output.xml [output2.xml ...]
                                 [--jira-issue PROJ-123]
                                 [--no-ai]
                                 [--output-file report.md]

    Analyse one or more local Robot Framework output.xml files and (optionally)
    post the flakiness report to a Jira ticket.

MODE 2 – Jira ticket-driven analysis (new)
-------------------------------------------
    python run_flaky_analysis.py --jira-ticket NCCF-1593628
                                 [--no-ai]
                                 [--no-post]
                                 [--output-file report.md]

    Given a Jira ticket ID the skill will:
      1. Fetch the ticket (summary, description, comments).
      2. Download all attachments.
      3. Parse any Robot Framework output.xml files found.
      4. Extract and analyse log files (HTML tags are stripped automatically).
      5. Use Claude to identify the root cause and recommend a fix.
      6. Post the analysis back to the Jira ticket (unless --no-post is given).

Examples
--------
    # Classic mode – single run, no AI, no Jira
    python run_flaky_analysis.py --robot-output tests/fixtures/sample_output.xml --no-ai

    # Classic mode – multiple historical runs
    python run_flaky_analysis.py \\
        --robot-output run1/output.xml run2/output.xml run3/output.xml

    # Classic mode – with AI summary and Jira comment
    python run_flaky_analysis.py \\
        --robot-output output.xml --jira-issue OPS-42

    # Ticket-driven mode
    python run_flaky_analysis.py --jira-ticket NCCF-1593628

    # Ticket-driven mode – no AI, print report to stdout only
    python run_flaky_analysis.py --jira-ticket NCCF-1593628 --no-ai --no-post

    # Save report to file
    python run_flaky_analysis.py \\
        --robot-output output.xml --no-ai --output-file flaky_report.md
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

    # ----------------------------------------------------------------
    # Mode 1 – local file analysis
    # ----------------------------------------------------------------
    parser.add_argument(
        "--robot-output",
        nargs="+",
        metavar="FILE",
        default=None,
        help="Path(s) to Robot Framework output.xml file(s). "
             "Provide multiple files from different CI runs to detect flakiness. "
             "Mutually exclusive with --jira-ticket.",
    )
    parser.add_argument(
        "--jira-issue",
        metavar="KEY",
        default=None,
        help="Jira issue key to POST the analysis report to (e.g. OPS-42). "
             "Used in combination with --robot-output. "
             "Requires JIRA_* environment variables to be set.",
    )

    # ----------------------------------------------------------------
    # Mode 2 – Jira ticket-driven
    # ----------------------------------------------------------------
    parser.add_argument(
        "--jira-ticket",
        metavar="KEY",
        default=None,
        help="Jira ticket key to READ and analyse (e.g. NCCF-1593628). "
             "The skill fetches the ticket, downloads attachments, analyses logs, "
             "and posts the root-cause report back to the ticket. "
             "Mutually exclusive with --robot-output.",
    )
    parser.add_argument(
        "--no-post",
        action="store_true",
        default=False,
        help="(ticket-driven mode only) Do not post the analysis back to Jira.",
    )

    # ----------------------------------------------------------------
    # Shared options
    # ----------------------------------------------------------------
    parser.add_argument(
        "--no-ai",
        action="store_true",
        default=False,
        help="Skip the Claude AI analysis step. "
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
        help="Claude model to use (default: claude-3-5-sonnet-20241022).",
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

    # Validate: exactly one mode must be chosen
    if args.jira_ticket and args.robot_output:
        print(
            "ERROR: --jira-ticket and --robot-output are mutually exclusive. "
            "Use one or the other.",
            file=sys.stderr,
        )
        sys.exit(1)

    if not args.jira_ticket and not args.robot_output:
        print(
            "ERROR: Provide either --jira-ticket KEY or --robot-output FILE [FILE ...]",
            file=sys.stderr,
        )
        sys.exit(1)

    skill = FlakyTestAnalysisSkill(
        claude_model=args.model,
        patterns_file=args.patterns_file,
    )

    # ----------------------------------------------------------------
    # Mode 2 – Jira ticket-driven analysis
    # ----------------------------------------------------------------
    if args.jira_ticket:
        report = skill.analyze_ticket(
            jira_issue_key=args.jira_ticket,
            use_ai=not args.no_ai,
            post_comment=not args.no_post,
        )
        formatted = report.formatted_report
        flaky_count = len([m for m in report.flaky_metrics if m.flakiness_score != "Stable"])

    # ----------------------------------------------------------------
    # Mode 1 – local file analysis
    # ----------------------------------------------------------------
    else:
        # Validate that all provided paths exist
        missing = [p for p in args.robot_output if not Path(p).exists()]
        if missing:
            for p in missing:
                print(f"ERROR: File not found: {p}", file=sys.stderr)
            sys.exit(1)

        report = skill.run_analysis(
            output_xml_paths=args.robot_output,
            jira_issue_key=args.jira_issue,
            use_ai_summary=not args.no_ai,
        )
        formatted = report.formatted_report
        flaky_count = sum(1 for m in report.metrics if m.flakiness_score != "Stable")

    print(formatted)

    if args.output_file:
        output_path = Path(args.output_file)
        output_path.write_text(formatted, encoding="utf-8")
        print(f"\nReport written to: {output_path}", file=sys.stderr)

    # Exit with non-zero code if flaky tests were found
    sys.exit(1 if flaky_count > 0 else 0)


if __name__ == "__main__":
    main()

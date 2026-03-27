#!/usr/bin/env python3
"""
run_flaky_analysis.py – Command-line entry point for the Flaky Test Analysis Skill.

Three modes are available:

MODE 1 – Local file analysis (classic)
---------------------------------------
    python run_flaky_analysis.py --robot-output output.xml [output2.xml ...]
                                 [--jira-issue PROJ-123]
                                 [--no-ai]
                                 [--output-file report.md]
                                 [--html-report report.html]

    Analyse one or more local Robot Framework output.xml files and (optionally)
    post the flakiness report to a Jira ticket.

MODE 2 – Single Jira ticket-driven analysis
--------------------------------------------
    python run_flaky_analysis.py --jira-ticket NCCF-1593628
                                 [--no-ai]
                                 [--no-post]
                                 [--output-file report.md]
                                 [--html-report report.html]

    Given a Jira ticket ID the skill will:
      1. Fetch the ticket (summary, description, comments).
      2. Download all attachments.
      3. Parse any Robot Framework output.xml files found.
      4. Extract and analyse log files (HTML tags are stripped automatically).
      5. Use Claude, OpenAI, or Groq to identify the root cause, recommend a
         fix, and provide a corrective code snippet.
      6. Post the analysis back to the Jira ticket (unless --no-post is given).

MODE 3 – Batch Jira ticket analysis
-------------------------------------
    python run_flaky_analysis.py --jira-tickets KEY1 KEY2 KEY3 ...
                                 [--no-ai]
                                 [--no-post]
                                 [--html-report report.html]

    Analyse multiple Jira tickets in one run.  A combined HTML report is
    written when --html-report is provided.  Individual Markdown reports are
    printed to stdout separated by dividers.

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

    # Single ticket-driven mode
    python run_flaky_analysis.py --jira-ticket NCCF-1593628

    # Batch ticket-driven mode (multiple tickets)
    python run_flaky_analysis.py --jira-tickets NCCF-1 NCCF-2 NCCF-3

    # Batch mode – no AI, no Jira post, write HTML report
    python run_flaky_analysis.py \\
        --jira-tickets NCCF-1 NCCF-2 --no-ai --no-post --html-report report.html

    # Save single-ticket report to file
    python run_flaky_analysis.py \\
        --jira-ticket NCCF-1593628 --no-ai --output-file flaky_report.md \\
        --html-report flaky_report.html
"""

import argparse
import logging
import os
import sys
from pathlib import Path

# Allow running as a top-level script without installing the package
sys.path.insert(0, str(Path(__file__).parent))

try:
    # Catches hard import failures (e.g. a missing package that is imported at
    # module level).  Lazy-loaded dependencies (e.g. pyyaml, which is only
    # loaded when PatternDatabase is instantiated) are caught later during
    # skill construction.
    from skills.flaky_test_analysis import FlakyTestAnalysisSkill
    from skills.flaky_test_analysis.html_report import render_html_report, markdown_wrap
except ImportError as _import_exc:
    print(
        f"ERROR: A required dependency is missing: {_import_exc}\n"
        "\nInstall dependencies using the SAME Python that runs this script:\n"
        "  python -m pip install -r requirements.txt\n"
        "\nUsing 'pip' or 'pip3' directly can install into a different Python\n"
        "environment (e.g. a different conda env or system Python) and will not\n"
        "be visible to the interpreter running this script.\n"
        "If you use conda, activate the target environment first:\n"
        "  conda activate <your-env>\n"
        "  python -m pip install -r requirements.txt",
        file=sys.stderr,
    )
    sys.exit(1)


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
             "Mutually exclusive with --jira-ticket and --jira-tickets.",
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
    # Mode 2 – single Jira ticket-driven
    # ----------------------------------------------------------------
    parser.add_argument(
        "--jira-ticket",
        metavar="KEY",
        default=None,
        help="Jira ticket key to READ and analyse (e.g. NCCF-1593628). "
             "The skill fetches the ticket, downloads attachments, analyses logs, "
             "and posts the root-cause report back to the ticket. "
             "Mutually exclusive with --robot-output and --jira-tickets.",
    )

    # ----------------------------------------------------------------
    # Mode 3 – batch Jira ticket-driven
    # ----------------------------------------------------------------
    parser.add_argument(
        "--jira-tickets",
        nargs="+",
        metavar="KEY",
        default=None,
        help="One or more Jira ticket keys to analyse in batch "
             "(e.g. NCCF-1 NCCF-2 NCCF-3). "
             "Each ticket is analysed individually and a combined report is "
             "produced. Mutually exclusive with --robot-output and --jira-ticket.",
    )

    parser.add_argument(
        "--no-post",
        action="store_true",
        default=False,
        help="(ticket-driven modes only) Do not post the analysis back to Jira.",
    )

    # ----------------------------------------------------------------
    # Shared options
    # ----------------------------------------------------------------
    parser.add_argument(
        "--no-ai",
        action="store_true",
        default=False,
        help="Skip the AI analysis step (Claude, OpenAI, or Groq). "
             "Useful when no AI API key is set or for offline use.",
    )
    parser.add_argument(
        "--output-file",
        metavar="PATH",
        default=None,
        help="Write the formatted Markdown report to this file. "
             "The report is always printed to stdout as well. "
             "In batch mode the combined Markdown for all tickets is written.",
    )
    parser.add_argument(
        "--html-report",
        metavar="PATH",
        default=None,
        help="Write a self-contained HTML report to this file. "
             "Works with all three modes. In batch mode the HTML file contains "
             "a summary table plus a card for every analysed ticket.",
    )
    parser.add_argument(
        "--model",
        default="claude-sonnet-4-6",
        help="Anthropic Claude model to use (default: claude-sonnet-4-6).",
    )
    parser.add_argument(
        "--openai-model",
        default="gpt-4o-mini",
        help="OpenAI model to use when OPENAI_API_KEY is set "
             "(default: gpt-4o-mini). Anthropic is tried first; OpenAI is "
             "used as a fallback. If the chosen model is not available on your "
             "account, the skill automatically falls back to gpt-4o-mini and "
             "then gpt-3.5-turbo.",
    )
    parser.add_argument(
        "--groq-model",
        default="llama-3.3-70b-versatile",
        help="Groq model to use when GROQ_API_KEY is set "
             "(default: llama-3.3-70b-versatile). Groq offers a free tier – "
             "obtain a key at https://console.groq.com. "
             "Used as the last-resort AI fallback after Anthropic and OpenAI.",
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


def _check_jira_env() -> list[str]:
    """Return a list of missing Jira environment variable names."""
    required = ["JIRA_BASE_URL", "JIRA_USER_EMAIL", "JIRA_API_TOKEN"]
    return [v for v in required if not os.environ.get(v, "").strip()]


def _jira_env_error_and_exit() -> None:
    """Print a clear error message for missing Jira env vars and exit."""
    missing_vars = _check_jira_env()
    if not missing_vars:
        return
    print(
        "ERROR: The following environment variables are required to "
        "connect to Jira but are not set:\n",
        file=sys.stderr,
    )
    for var in missing_vars:
        print(f"  {var}", file=sys.stderr)
    print(
        "\nSet them and re-run, for example:\n"
        "\n"
        "  export JIRA_BASE_URL='https://your-org.atlassian.net'\n"
        "  export JIRA_USER_EMAIL='your-email@your-org.com'\n"
        "  export JIRA_API_TOKEN='<your-atlassian-api-token>'\n"
        "\n"
        "Create an API token at: https://id.atlassian.com/manage-profile/security/api-tokens\n"
        "\n"
        "Add --no-ai to skip the AI step if no AI API key is set.\n"
        "For a free AI option, set GROQ_API_KEY (see https://console.groq.com).",
        file=sys.stderr,
    )
    sys.exit(1)


def main(argv=None):
    args = parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s – %(message)s",
    )

    # Validate: exactly one mode must be chosen
    modes_chosen = sum([
        bool(args.robot_output),
        bool(args.jira_ticket),
        bool(args.jira_tickets),
    ])
    if modes_chosen > 1:
        print(
            "ERROR: --jira-ticket, --jira-tickets, and --robot-output are mutually exclusive. "
            "Use only one.",
            file=sys.stderr,
        )
        sys.exit(1)

    if modes_chosen == 0:
        print(
            "ERROR: Provide one of: --jira-ticket KEY, --jira-tickets KEY [KEY ...], "
            "or --robot-output FILE [FILE ...]",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        skill = FlakyTestAnalysisSkill(
            claude_model=args.model,
            openai_model=args.openai_model,
            groq_model=args.groq_model,
            patterns_file=args.patterns_file,
        )
    except ImportError as exc:
        # Catches lazy-loaded dependencies that are only resolved at
        # instantiation time (e.g. pyyaml, imported inside PatternDatabase).
        print(
            f"ERROR: A required dependency is missing: {exc}\n"
            "\nInstall dependencies using the SAME Python that runs this script:\n"
            "  python -m pip install -r requirements.txt\n"
            "\nUsing 'pip' or 'pip3' directly can install into a different Python\n"
            "environment (e.g. a different conda env or system Python) and will not\n"
            "be visible to the interpreter running this script.\n"
            "If you use conda, activate the target environment first:\n"
            "  conda activate <your-env>\n"
            "  python -m pip install -r requirements.txt",
            file=sys.stderr,
        )
        sys.exit(1)

    # ----------------------------------------------------------------
    # Mode 3 – Batch Jira ticket-driven analysis
    # ----------------------------------------------------------------
    if args.jira_tickets:
        if _check_jira_env():
            _jira_env_error_and_exit()

        ticket_reports = []
        all_formatted = []
        flaky_count = 0

        for key in args.jira_tickets:
            try:
                report = skill.analyze_ticket(
                    jira_issue_key=key,
                    use_ai=not args.no_ai,
                    post_comment=not args.no_post,
                )
                ticket_reports.append(report)
                all_formatted.append(report.formatted_report)
                flaky_count += len([m for m in report.flaky_metrics if m.flakiness_score != "Stable"])
            except RuntimeError as exc:
                print(f"ERROR [{key}]: {exc}", file=sys.stderr)
            except Exception as exc:  # noqa: BLE001
                print(f"ERROR [{key}]: Unexpected failure: {exc}", file=sys.stderr)
                if args.verbose:
                    import traceback
                    traceback.print_exc()

        combined_md = ("\n\n" + "─" * 60 + "\n\n").join(all_formatted)
        print(combined_md)

        if args.output_file:
            output_path = Path(args.output_file)
            output_path.write_text(combined_md, encoding="utf-8")
            print(f"\nReport written to: {output_path}", file=sys.stderr)

        if args.html_report and ticket_reports:
            html = render_html_report(
                ticket_reports,
                title=f"Flaky Test Analysis – {len(ticket_reports)} ticket(s)",
            )
            html_path = Path(args.html_report)
            html_path.write_text(html, encoding="utf-8")
            print(f"HTML report written to: {html_path}", file=sys.stderr)

        sys.exit(1 if flaky_count > 0 else 0)

    # ----------------------------------------------------------------
    # Mode 2 – Single Jira ticket-driven analysis
    # ----------------------------------------------------------------
    if args.jira_ticket:
        if _check_jira_env():
            _jira_env_error_and_exit()

        try:
            report = skill.analyze_ticket(
                jira_issue_key=args.jira_ticket,
                use_ai=not args.no_ai,
                post_comment=not args.no_post,
            )
        except RuntimeError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            sys.exit(1)
        except Exception as exc:  # noqa: BLE001
            print(f"ERROR: Unexpected failure analysing ticket {args.jira_ticket}: {exc}", file=sys.stderr)
            print(
                "Tip: if the error is AI-related, re-run with --no-ai to skip the AI step.",
                file=sys.stderr,
            )
            if args.verbose:
                import traceback
                traceback.print_exc()
            sys.exit(1)

        formatted = report.formatted_report
        flaky_count = len([m for m in report.flaky_metrics if m.flakiness_score != "Stable"])

        print(formatted)

        if args.output_file:
            output_path = Path(args.output_file)
            output_path.write_text(formatted, encoding="utf-8")
            print(f"\nReport written to: {output_path}", file=sys.stderr)

        if args.html_report:
            html = render_html_report([report], title=f"Flaky Test Analysis – {args.jira_ticket}")
            html_path = Path(args.html_report)
            html_path.write_text(html, encoding="utf-8")
            print(f"HTML report written to: {html_path}", file=sys.stderr)

        sys.exit(1 if flaky_count > 0 else 0)

    # ----------------------------------------------------------------
    # Mode 1 – local file analysis
    # ----------------------------------------------------------------
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

    if args.html_report:
        html = markdown_wrap(formatted, title="Flaky Test Analysis")
        html_path = Path(args.html_report)
        html_path.write_text(html, encoding="utf-8")
        print(f"HTML report written to: {html_path}", file=sys.stderr)

    # Exit with non-zero code if flaky tests were found
    sys.exit(1 if flaky_count > 0 else 0)


if __name__ == "__main__":
    main()

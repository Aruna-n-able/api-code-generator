"""
html_report.py – HTML report generation for the Flaky Test Analysis Skill.

Provides :func:`render_html_report` which converts one or more
:class:`~skills.flaky_test_analysis.skill.TicketAnalysisReport` objects into a
self-contained, styled HTML document, and :func:`markdown_wrap` which wraps a
plain Markdown string (from the local-file analysis mode) in the same shell.
"""

from __future__ import annotations

import html as _html_stdlib
import re
from pathlib import Path
from typing import List, TYPE_CHECKING

if TYPE_CHECKING:
    from .skill import TicketAnalysisReport

# ---------------------------------------------------------------------------
# Stylesheet
# ---------------------------------------------------------------------------

_CSS = """
* { box-sizing: border-box; }
body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    margin: 0; padding: 20px 40px; color: #212529; background: #f4f6f9;
    line-height: 1.65;
}
.container { max-width: 1100px; margin: 0 auto; }
h1 { color: #0d1b2a; border-bottom: 3px solid #4361ee; padding-bottom: 10px; }
h2 { color: #14213d; border-bottom: 1px solid #ced4da; padding-bottom: 6px;
     margin-top: 1.8em; }
h3 { color: #2d3a4a; margin-top: 1.4em; }
h4 { color: #495057; }
a { color: #4361ee; }
table { border-collapse: collapse; width: 100%; margin: 12px 0; font-size: .94em; }
th { background: #4361ee; color: #fff; padding: 8px 12px; text-align: left; }
td { border: 1px solid #dee2e6; padding: 8px 12px; vertical-align: top; }
tr:nth-child(even) td { background: #f8f9fa; }
code { background: #e8ecf0; padding: 2px 6px; border-radius: 3px;
       font-family: "Courier New", Courier, monospace; font-size: .88em; }
pre  { background: #1e2736; color: #c9d1d9; padding: 16px; border-radius: 6px;
       overflow-x: auto; margin: 12px 0; font-size: .88em; line-height: 1.5; }
pre code { background: none; color: inherit; padding: 0; font-size: inherit; }
blockquote { border-left: 4px solid #4361ee; margin: 8px 0; padding: 8px 16px;
             background: #eef0fb; color: #495057; border-radius: 0 4px 4px 0; }
ul, ol { padding-left: 22px; margin: 8px 0; }
li { margin: 3px 0; }
hr { border: none; border-top: 1px solid #dee2e6; margin: 20px 0; }
.badge { display: inline-block; padding: 2px 10px; border-radius: 20px;
         font-size: .78em; font-weight: 600; letter-spacing: .02em; }
.badge-open   { background: #d1fae5; color: #065f46; }
.badge-closed { background: #fee2e2; color: #991b1b; }
.badge-other  { background: #fef3c7; color: #92400e; }
.card { background: #fff; border: 1px solid #dee2e6; border-radius: 8px;
        margin: 28px 0; box-shadow: 0 2px 6px rgba(0,0,0,.06); overflow: hidden; }
.card-header { background: #4361ee; color: #fff; padding: 14px 20px; }
.card-header h2 { color: #fff; border: none; margin: 0; font-size: 1.15em; }
.card-body { padding: 20px 24px; }
.meta-tbl { width: auto; margin-bottom: 16px; }
.snippet-wrap { background: #1e2736; border-radius: 6px; margin: 12px 0; }
.snippet-wrap pre { margin: 0; }
.footer { color: #868e96; font-style: italic; font-size: .88em;
          margin-top: 40px; border-top: 1px solid #dee2e6; padding-top: 12px; }
"""

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _e(text: str) -> str:
    """HTML-escape a value."""
    return _html_stdlib.escape(str(text))


def _inline(text: str) -> str:
    """Apply inline Markdown formatting (bold, italic, code, links) to *text*.

    The function HTML-escapes the input first, then applies inline markup so
    that the Markdown syntax characters are never treated as raw HTML.
    """
    escaped = _html_stdlib.escape(text)
    # **bold**
    escaped = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
    # *italic* (single star that isn't part of **)
    escaped = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"<em>\1</em>", escaped)
    # _italic_ (single underscore)
    escaped = re.sub(r"(?<!_)_([^_\n]+)_(?!_)", r"<em>\1</em>", escaped)
    # `inline code`
    escaped = re.sub(r"`([^`\n]+)`", r"<code>\1</code>", escaped)
    # [link text](url)
    escaped = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', escaped)
    return escaped


def _para(text: str) -> str:
    """Wrap *text* in a ``<p>`` tag with inline formatting applied."""
    return f"<p>{_inline(text)}</p>"


def _pointwise_html(text: str) -> str:
    """Convert a bullet/numbered-list text block to an HTML list.

    Lines starting with ``- `` are rendered as ``<ul><li>…</li></ul>``.
    Lines starting with ``1. ``, ``2. `` etc. are rendered as
    ``<ol><li>…</li></ol>``.  Plain paragraph text falls back to ``<p>``.
    Any mix of the two is handled gracefully.
    """
    lines = text.strip().splitlines()
    ul_items: List[str] = []
    ol_items: List[str] = []
    plain_parts: List[str] = []
    out_parts: List[str] = []

    def _flush() -> None:
        if ul_items:
            out_parts.append(
                "<ul>" + "".join(f"<li>{_inline(i)}</li>" for i in ul_items) + "</ul>"
            )
            ul_items.clear()
        if ol_items:
            out_parts.append(
                "<ol>" + "".join(f"<li>{_inline(i)}</li>" for i in ol_items) + "</ol>"
            )
            ol_items.clear()
        if plain_parts:
            out_parts.append(f"<p>{_inline(' '.join(plain_parts))}</p>")
            plain_parts.clear()

    for line in lines:
        stripped = line.strip()
        if not stripped:
            _flush()
            continue
        if stripped.startswith("- "):
            if ol_items or plain_parts:
                _flush()
            ul_items.append(stripped[2:].strip())
        elif re.match(r"^\d+\.\s", stripped):
            if ul_items or plain_parts:
                _flush()
            ol_items.append(re.sub(r"^\d+\.\s*", "", stripped, count=1).strip())
        else:
            if ul_items or ol_items:
                _flush()
            plain_parts.append(stripped)

    _flush()
    return "\n".join(out_parts) if out_parts else _para(text)


def _badge(status: str) -> str:
    """Return a coloured status badge HTML snippet."""
    s = status.lower()
    css = (
        "badge-closed" if s in ("closed", "done", "resolved", "cancelled", "fixed")
        else "badge-open" if s in ("open", "in progress", "in-progress", "new", "reopened")
        else "badge-other"
    )
    return f'<span class="badge {css}">{_e(status)}</span>'


def _code_block(snippet: str, lang: str = "python") -> str:
    """Render *snippet* in a styled ``<pre><code>`` block.

    Strips Markdown fence markers (`` ``` ``) if present so the caller can pass
    either raw code or a fenced Markdown code block.
    """
    # Strip leading/trailing ``` markers
    snippet = re.sub(r"^```[a-z]*\n?", "", snippet.strip(), flags=re.MULTILINE)
    snippet = re.sub(r"```\s*$", "", snippet, flags=re.MULTILINE)
    return (
        f'<div class="snippet-wrap">'
        f'<pre><code class="language-{_e(lang)}">{_e(snippet.strip())}</code></pre>'
        f"</div>"
    )


# ---------------------------------------------------------------------------
# Markdown → HTML (lightweight converter for local-file mode)
# ---------------------------------------------------------------------------

def _md_to_html_body(md: str) -> str:
    """Convert a Markdown string (as produced by this skill) to an HTML body fragment.

    Only the patterns actually used by the skill's report formatter are
    handled; arbitrary Markdown is not supported.
    """
    lines = md.splitlines()
    out: List[str] = []
    in_code = False
    in_table = False
    in_ul = False
    i = 0

    def _close_open_blocks() -> None:
        nonlocal in_table, in_ul
        if in_table:
            out.append("</table>")
            in_table = False
        if in_ul:
            out.append("</ul>")
            in_ul = False

    while i < len(lines):
        line = lines[i]

        # ── fenced code blocks ───────────────────────────────────────
        if line.startswith("```"):
            if not in_code:
                _close_open_blocks()
                out.append("<pre><code>")
                in_code = True
            else:
                out.append("</code></pre>")
                in_code = False
            i += 1
            continue

        if in_code:
            out.append(_e(line))
            i += 1
            continue

        # ── tables ───────────────────────────────────────────────────
        if line.startswith("|"):
            if in_ul:
                out.append("</ul>")
                in_ul = False
            if not in_table:
                out.append("<table>")
                in_table = True
                # Check for header separator on next line
                if i + 1 < len(lines) and re.match(r"\|[-| :]+\|", lines[i + 1]):
                    cells = [c.strip() for c in line.strip("|").split("|")]
                    out.append(
                        "<tr>"
                        + "".join(f"<th>{_inline(c)}</th>" for c in cells)
                        + "</tr>"
                    )
                    i += 2  # skip the separator line
                    continue
                else:
                    cells = [c.strip() for c in line.strip("|").split("|")]
                    out.append(
                        "<tr>"
                        + "".join(f"<td>{_inline(c)}</td>" for c in cells)
                        + "</tr>"
                    )
            else:
                cells = [c.strip() for c in line.strip("|").split("|")]
                out.append(
                    "<tr>"
                    + "".join(f"<td>{_inline(c)}</td>" for c in cells)
                    + "</tr>"
                )
            i += 1
            continue
        elif in_table:
            out.append("</table>")
            in_table = False

        # ── headings ─────────────────────────────────────────────────
        if line.startswith("#### "):
            _close_open_blocks()
            out.append(f"<h4>{_inline(line[5:])}</h4>")
        elif line.startswith("### "):
            _close_open_blocks()
            out.append(f"<h3>{_inline(line[4:])}</h3>")
        elif line.startswith("## "):
            _close_open_blocks()
            out.append(f"<h2>{_inline(line[3:])}</h2>")
        elif line.startswith("# "):
            _close_open_blocks()
            out.append(f"<h1>{_inline(line[2:])}</h1>")
        # ── blockquote ───────────────────────────────────────────────
        elif line.startswith("> "):
            if in_ul:
                out.append("</ul>")
                in_ul = False
            out.append(f"<blockquote>{_inline(line[2:])}</blockquote>")
        # ── horizontal rule ──────────────────────────────────────────
        elif line.strip() == "---":
            _close_open_blocks()
            out.append("<hr>")
        # ── unordered list ───────────────────────────────────────────
        elif line.startswith("- "):
            if in_table:
                out.append("</table>")
                in_table = False
            if not in_ul:
                out.append("<ul>")
                in_ul = True
            out.append(f"<li>{_inline(line[2:])}</li>")
        # ── blank line ───────────────────────────────────────────────
        elif not line.strip():
            if in_ul:
                out.append("</ul>")
                in_ul = False
        # ── normal paragraph ─────────────────────────────────────────
        else:
            if in_ul:
                out.append("</ul>")
                in_ul = False
            out.append(f"<p>{_inline(line)}</p>")

        i += 1

    # Close any still-open blocks
    if in_code:
        out.append("</code></pre>")
    if in_table:
        out.append("</table>")
    if in_ul:
        out.append("</ul>")

    return "\n".join(out)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

_FOOTER = "_Analysis generated automatically by the Flaky Test Analysis Skill._"

_HTML_SHELL = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<style>{css}</style>
</head>
<body>
<div class="container">
<h1>🔍 {title_escaped}</h1>
{body}
<div class="footer"><em>{footer}</em></div>
</div>
</body>
</html>"""


def render_html_report(
    reports: "List[TicketAnalysisReport]",
    title: str = "Flaky Test Analysis Report",
) -> str:
    """Generate a self-contained HTML report from one or more
    :class:`~skills.flaky_test_analysis.skill.TicketAnalysisReport` objects.

    Parameters
    ----------
    reports:
        One or more analysis reports to include in the page.
    title:
        Document title and top-level ``<h1>`` heading.

    Returns
    -------
    str
        A complete, self-contained HTML document.
    """
    parts: List[str] = []

    # ── summary table ────────────────────────────────────────────────────────
    count_label = f"{len(reports)} ticket{'s' if len(reports) != 1 else ''} analysed"
    rows = []
    for r in reports:
        flaky_count = sum(1 for m in r.flaky_metrics if m.flakiness_score != "Stable")
        rows.append(
            f"<tr>"
            f'<td><a href="#{_e(r.issue_key)}">{_e(r.issue_key)}</a></td>'
            f"<td>{_e(r.summary)}</td>"
            f"<td>{_badge(r.status)}</td>"
            f'<td style="text-align:center">{len(r.attachments)}</td>'
            f'<td style="text-align:center">{flaky_count}</td>'
            f"</tr>"
        )
    parts.append(
        f"<h2>📋 Summary – {_e(count_label)}</h2>"
        "<table>"
        "<tr><th>Ticket</th><th>Summary</th><th>Status</th>"
        "<th>Attachments</th><th>Flaky Tests</th></tr>"
        + "".join(rows)
        + "</table>"
    )

    # ── individual ticket cards ───────────────────────────────────────────────
    for r in reports:
        parts.append(_render_ticket_card(r))

    body = "\n".join(parts)
    return _HTML_SHELL.format(
        title=_e(title),
        css=_CSS,
        title_escaped=_e(title),
        body=body,
        footer=_e(_FOOTER),
    )


def markdown_wrap(md: str, title: str = "Flaky Test Analysis Report") -> str:
    """Wrap a Markdown report string in a styled HTML document.

    Used for the ``--robot-output`` (local-file) analysis mode where there is
    no structured :class:`TicketAnalysisReport` to build from.

    Parameters
    ----------
    md:
        The Markdown text to convert.
    title:
        Document title.

    Returns
    -------
    str
        A complete, self-contained HTML document.
    """
    body = _md_to_html_body(md)
    return _HTML_SHELL.format(
        title=_e(title),
        css=_CSS,
        title_escaped=_e(title),
        body=body,
        footer=_e(_FOOTER),
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _render_ticket_card(r: "TicketAnalysisReport") -> str:
    """Render a single :class:`TicketAnalysisReport` as an HTML card."""
    failing_test = (getattr(r, "failing_test_name", "") or "").strip()
    src_file = (getattr(r, "robot_source_file", "") or "").strip()
    lines: List[str] = [
        f'<div class="card" id="{_e(r.issue_key)}">',
        '<div class="card-header">',
        f"<h2>{_e(r.issue_key)}: {_e(r.summary)} {_badge(r.status)}</h2>",
        "</div>",
        '<div class="card-body">',
        # meta table
        '<table class="meta-tbl">',
        f"<tr><td><strong>Ticket</strong></td><td>{_e(r.issue_key)}</td></tr>",
        f"<tr><td><strong>Status</strong></td><td>{_badge(r.status)}</td></tr>",
        f"<tr><td><strong>Attachments analysed</strong></td><td>{len(r.attachments)}</td></tr>",
    ]
    if failing_test:
        lines.append(
            f"<tr><td><strong>Failing Test</strong></td>"
            f"<td><code>{_e(failing_test)}</code></td></tr>"
        )
    if src_file:
        lines.append(
            f"<tr><td><strong>Robot Test File</strong></td>"
            f"<td><code>{_e(Path(src_file).name)}</code></td></tr>"
        )
    lines.append("</table>")

    # attachments
    if r.attachments:
        lines.append("<h2>📎 Attachments Found</h2><ul>")
        for att in r.attachments:
            if att.is_robot_xml:
                icon = "🤖"
            elif att.filename.lower().endswith(".zip") or "zip" in (att.mime_type or "").lower():
                icon = "📦"
            else:
                icon = "📄"
            lines.append(
                f"<li>{icon} <code>{_e(att.filename)}</code>"
                f" ({_e(att.mime_type or 'unknown')}, {att.size:,} bytes)</li>"
            )
        lines.append("</ul>")

    # robot test results
    if r.robot_runs:
        lines.append("<h2>🤖 Robot Framework Test Results</h2>")
        for run in r.robot_runs:
            failed = [t for t in run.tests if t.status == "FAIL"]
            passed = [t for t in run.tests if t.status == "PASS"]
            lines += [
                f"<h3>Run: <code>{_e(Path(run.source_file).name)}</code></h3>",
                f"<p>✅ Passed: {len(passed)} &nbsp;|&nbsp; ❌ Failed: {len(failed)}</p>",
            ]
            if failed:
                lines += [
                    "<table>",
                    "<tr><th>Test</th><th>Suite</th><th>Error</th></tr>",
                ]
                for t in failed[:20]:
                    msg = (t.message or "")[:120].replace("\n", " ")
                    lines.append(
                        f"<tr><td><code>{_e(t.name)}</code></td>"
                        f"<td><code>{_e(t.suite)}</code></td>"
                        f"<td>{_e(msg)}</td></tr>"
                    )
                lines.append("</table>")

    # flaky metrics
    flaky = [m for m in r.flaky_metrics if m.flakiness_score != "Stable"]
    if flaky:
        icons = {"High": "🔴", "Medium": "🟠", "Low": "🟡"}
        lines.append("<h2>⚡ Flaky Tests Detected</h2><ul>")
        for m in flaky:
            icon = icons.get(m.flakiness_score, "⚪")
            lines.append(
                f"<li>{icon} <code>{_e(m.name)}</code> — "
                f"<strong>{_e(m.flakiness_score)}</strong> ({_e(m.failure_rate_display)})</li>"
            )
        lines.append("</ul>")

    # failing test source from n-central
    src_snippet = (getattr(r, "robot_source_snippet", "") or "").strip()
    if src_snippet:
        lines += [
            "<h2>🤖 Failing Test Source</h2>",
            f'<p><em>Fetched from <code>{_e(src_file)}</code> in the n-central repository</em></p>',
            _code_block(src_snippet, lang="robot"),
        ]

    # pattern-based recommendations
    if r.recommendations:
        from .skill import FlakyTestAnalysisSkill as _Skill
        src_snippet_for_recs = (getattr(r, "robot_source_snippet", "") or "").strip()
        src_basename_for_recs = Path(src_file).name if src_file else ""
        lines.append("<h2>💡 Detected Patterns &amp; Recommendations</h2>")
        for test_name, recs in r.recommendations.items():
            lines.append(f"<h3><code>{_e(test_name)}</code></h3>")
            if src_basename_for_recs:
                test_line = _Skill._find_test_line_in_snippet(
                    test_name, src_snippet_for_recs
                )
                if test_line is not None:
                    loc_text = (
                        f"📍 <strong>File:</strong> "
                        f"<code>{_e(src_basename_for_recs)}</code>"
                        f" &middot; <strong>Line:</strong> {test_line}"
                    )
                else:
                    loc_text = (
                        f"📍 <strong>File:</strong> "
                        f"<code>{_e(src_basename_for_recs)}</code>"
                    )
                lines.append(f"<p>{loc_text}</p>")
            for rec in recs:
                lines += [
                    f"<h4>{_e(rec.pattern_name)}</h4>",
                    _para(rec.description.strip()),
                    f"<pre><code>{_e(rec.fix_template.strip())}</code></pre>",
                ]

    # root cause – rendered as bullet list
    if r.root_cause:
        lines.append("<h2>🔍 Root Cause</h2>")
        lines.append(_pointwise_html(r.root_cause))

    # affected line (AI-identified)
    al = (getattr(r, "affected_line", "") or "").strip()
    if al and al.upper() not in ("N/A", "NONE"):
        lines += [
            "<h2>📍 Affected Line</h2>",
            f"<p><code>{_e(al)}</code></p>",
        ]

    # recommended solution – rendered as ordered list
    if r.recommended_solution:
        lines.append("<h2>✅ Recommended Solution</h2>")
        lines.append(_pointwise_html(r.recommended_solution))

    # code snippet (AI-corrected version)
    snippet = (r.code_snippet or "").strip()
    if snippet and snippet.upper() not in ("N/A", "NONE"):
        lang_match = re.match(r"```([a-z]+)", snippet)
        lang = lang_match.group(1) if lang_match else "robot"
        is_python = lang == "python"
        lines.append("<h2>💻 Corrected Code Snippet</h2>")
        if is_python:
            from .skill import FlakyTestAnalysisSkill as _Skill
            src_snippet_text = (getattr(r, "robot_source_snippet", "") or "").strip()
            py_libs = _Skill._extract_python_libraries(src_snippet_text) if src_snippet_text else []
        else:
            py_libs = []
        if src_file:
            src_filename = Path(src_file).name
            if is_python:
                if py_libs:
                    lib_list = ", ".join(f"<code>{_e(lib)}</code>" for lib in py_libs)
                    guidance = (
                        f"⚠️ <strong>Where to apply this:</strong> This is Python code. "
                        f"Apply the changes to the Python library file(s) imported "
                        f"in <code>{_e(src_filename)}</code>: {lib_list}."
                    )
                else:
                    guidance = (
                        f"⚠️ <strong>Where to apply this:</strong> This is Python code for a library or "
                        f"keyword implementation. Open <code>{_e(src_filename)}</code>, find the "
                        f"<code>Library</code> or <code>Resource</code> imports, and apply the changes "
                        f"to the referenced Python file."
                    )
            else:
                guidance = (
                    f"📝 <strong>Where to apply this:</strong> Apply these changes in "
                    f"<code>{_e(src_filename)}</code>."
                )
            lines.append(f"<p>{guidance}</p>")
        elif failing_test:
            inferred_file = f"{failing_test}.robot"
            if is_python:
                if py_libs:
                    lib_list = ", ".join(f"<code>{_e(lib)}</code>" for lib in py_libs)
                    guidance = (
                        f"⚠️ <strong>Where to apply this:</strong> This is Python code. "
                        f"Apply the changes to the Python library file(s) imported "
                        f"in <code>{_e(inferred_file)}</code>: {lib_list}."
                    )
                else:
                    guidance = (
                        f"⚠️ <strong>Where to apply this:</strong> This is Python code for a library or "
                        f"keyword implementation. Open <code>{_e(inferred_file)}</code>, find the "
                        f"<code>Library</code> or <code>Resource</code> imports, and apply the changes "
                        f"to the referenced Python file."
                    )
            else:
                guidance = (
                    f"📝 <strong>Where to apply this:</strong> Apply these changes in "
                    f"<code>{_e(inferred_file)}</code>."
                )
            lines.append(f"<p>{guidance}</p>")
        lines.append(_code_block(snippet, lang=lang))

    lines += ["</div>", "</div>"]  # close card-body / card
    return "\n".join(lines)

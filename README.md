# api-code-generator

## Flaky Test Analysis AI Skill for Robot Framework

An AI-powered skill that detects, analyses, and provides remediation guidance for intermittent (flaky) test failures in Robot Framework test suites. It identifies failure patterns across multiple CI runs, computes reliability metrics, generates code-level fix recommendations, and can automatically post structured analysis to Jira.

---

## Table of Contents

- [Features](#features)
- [Project Structure](#project-structure)
- [Quick Start (Local Testing)](#quick-start-local-testing)
- [Configuration](#configuration)
- [Running Tests](#running-tests)
- [CLI Reference](#cli-reference)
- [Python API](#python-api)
- [Jira Integration](#jira-integration)
- [CI/CD Integration (Jenkins)](#cicd-integration-jenkins)
- [Extending the Pattern Database](#extending-the-pattern-database)
- [Architecture](#architecture)

---

## Features

| Capability | Description |
|---|---|
| **Flaky Test Detection** | Compares test results across multiple `output.xml` runs to identify genuinely intermittent failures (both pass and fail observed) |
| **Root Cause Classification** | Matches failures against 7 built-in patterns: timing issues, database contamination, external APIs, random data, race conditions, test-order dependencies, Flask context errors |
| **Reliability Metrics** | Failure rate, flakiness score (High / Medium / Low / Stable), duration variance, first / last seen timestamps |
| **Fix Recommendations** | Concrete, copy-paste ready code snippets for each detected pattern |
| **AI Executive Summary** | Optional Claude-powered natural-language summary of findings |
| **Jira Integration** | Post formatted Markdown reports as Jira comments via REST API or MCP connector |

---

## Project Structure

```
.
├── run_flaky_analysis.py           # CLI entry point
├── requirements.txt
├── skills/
│   └── flaky_test_analysis/
│       ├── __init__.py
│       ├── skill.py                # Top-level orchestrator (FlakyTestAnalysisSkill)
│       ├── robot_parser.py         # output.xml parser
│       ├── pattern_db.py           # Pattern knowledge base loader + matcher
│       ├── metrics.py              # Flakiness metrics computation
│       ├── recommender.py          # Fix recommendation generator
│       ├── jira_client.py          # Jira REST / MCP integration
│       └── patterns/
│           └── flaky_patterns.yaml # Built-in flaky pattern definitions
└── tests/
    ├── test_flaky_skill.py         # Unit + integration tests (35 tests)
    └── fixtures/
        ├── sample_output.xml       # Sample Robot Framework output (run 1)
        └── sample_output_run2.xml  # Sample Robot Framework output (run 2)
```

---

## Quick Start (Local Testing)

### Prerequisites

- Python 3.10+
- pip

### 1. Clone and install dependencies

```bash
git clone <repo-url>
cd api-code-generator
pip install -r requirements.txt
```

### 2. Run the skill against the bundled fixture files

The repo ships with two sample `output.xml` files that demonstrate flaky behaviour (some tests pass in one run and fail in the other).

```bash
python run_flaky_analysis.py \
    --robot-output tests/fixtures/sample_output.xml \
                   tests/fixtures/sample_output_run2.xml \
    --no-ai
```

You will see a Markdown report printed to stdout listing flaky tests, their metrics, detected patterns, and recommended code fixes.

### 3. Save the report to a file

```bash
python run_flaky_analysis.py \
    --robot-output tests/fixtures/sample_output.xml \
                   tests/fixtures/sample_output_run2.xml \
    --no-ai \
    --output-file flaky_report.md
```

### 4. Enable the Claude AI executive summary (optional)

Set your Anthropic API key and run without `--no-ai`:

```bash
export ANTHROPIC_API_KEY="sk-ant-..."

python run_flaky_analysis.py \
    --robot-output tests/fixtures/sample_output.xml \
                   tests/fixtures/sample_output_run2.xml
```

### 5. Analyse your own Robot Framework output

Collect `output.xml` files from several CI runs of the same suite, then pass them all at once. The more runs you provide, the more accurate the flakiness detection:

```bash
python run_flaky_analysis.py \
    --robot-output ci/run1/output.xml ci/run2/output.xml ci/run3/output.xml \
    --no-ai \
    --output-file report.md
```

> **Exit code**: The script exits with code `1` when flaky tests are detected, and `0` when all tests are stable. This makes it easy to fail a CI step on flakiness.

---

## Configuration

All sensitive settings are read from environment variables so that credentials are never stored in code.

| Variable | Required | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | Optional | Anthropic API key for the Claude AI summary |
| `JIRA_BASE_URL` | For Jira | e.g. `https://myorg.atlassian.net` |
| `JIRA_USER_EMAIL` | For Jira | Atlassian account e-mail |
| `JIRA_API_TOKEN` | For Jira | Jira API token (create at id.atlassian.com) |
| `JIRA_PROJECT_KEY` | Optional | Default Jira project key (e.g. `QA`) |
| `JIRA_AUTH_MODE` | Optional | `rest` (default) or `mcp` |

---

## Running Tests

```bash
# Run the full test suite
pytest tests/test_flaky_skill.py -v

# Run with coverage
pytest tests/test_flaky_skill.py -v --cov=skills --cov-report=term-missing
```

Expected output: **35 tests passed**.

---

## CLI Reference

```
usage: run_flaky_analysis.py [-h]
                             --robot-output FILE [FILE ...]
                             [--jira-issue KEY]
                             [--no-ai]
                             [--output-file PATH]
                             [--model MODEL]
                             [--patterns-file PATH]
                             [--verbose]

Flaky Test Analysis Skill for Robot Framework

options:
  --robot-output FILE [FILE ...]
                        Path(s) to Robot Framework output.xml file(s).
                        Provide multiple files to detect cross-run flakiness.
  --jira-issue KEY      Jira issue key to post the report to (e.g. OPS-42).
                        Requires JIRA_* environment variables.
  --no-ai               Skip Claude AI summary (useful without ANTHROPIC_API_KEY).
  --output-file PATH    Write the Markdown report to this file.
  --model MODEL         Claude model to use (default: claude-3-5-sonnet-20241022).
  --patterns-file PATH  Path to a custom flaky_patterns.yaml.
  --verbose, -v         Enable verbose logging.
```

---

## Python API

```python
from skills.flaky_test_analysis import FlakyTestAnalysisSkill

skill = FlakyTestAnalysisSkill(
    anthropic_api_key="sk-ant-...",   # or set ANTHROPIC_API_KEY env var
    claude_model="claude-3-5-sonnet-20241022",
)

report = skill.run_analysis(
    output_xml_paths=["run1/output.xml", "run2/output.xml"],
    jira_issue_key="OPS-42",          # optional: post to Jira
    use_ai_summary=True,
)

print(report.formatted_report)

for metrics in report.metrics:
    if metrics.flakiness_score != "Stable":
        print(f"{metrics.name}: {metrics.flakiness_score} ({metrics.failure_rate_display})")

for test_name, recs in report.recommendations.items():
    for rec in recs:
        print(f"  [{rec.pattern_name}] {rec.fix_template[:80]}...")
```

---

## Jira Integration

### REST API mode (default)

```bash
export JIRA_BASE_URL="https://myorg.atlassian.net"
export JIRA_USER_EMAIL="ci-bot@myorg.com"
export JIRA_API_TOKEN="<your-api-token>"

python run_flaky_analysis.py \
    --robot-output output.xml \
    --jira-issue QA-123 \
    --no-ai
```

### MCP connector mode

Set `JIRA_AUTH_MODE=mcp` and implement the `_post_via_mcp` method in
`skills/flaky_test_analysis/jira_client.py` with your organisation's MCP client.

---

## CI/CD Integration (Jenkins)

Add the following post-build steps to your `Jenkinsfile`:

```groovy
pipeline {
  stages {
    stage('Test') {
      steps {
        sh 'robot tests/'
      }
    }
  }
  post {
    always {
      archiveArtifacts artifacts: 'output.xml, log.html, report.html'
    }
    failure {
      sh '''
        pip install -r requirements.txt -q
        python run_flaky_analysis.py \
          --robot-output output.xml \
          --no-ai \
          --output-file flaky_report.md || true
      '''
      archiveArtifacts artifacts: 'flaky_report.md'
    }
    unstable {
      sh 'python run_flaky_analysis.py --robot-output output.xml --no-ai || true'
    }
  }
}
```

For cross-run flakiness detection, collect `output.xml` from multiple previous builds (e.g., using the Jenkins Copy Artifact plugin) and pass all files to `--robot-output`.

---

## Extending the Pattern Database

Add new patterns to `skills/flaky_test_analysis/patterns/flaky_patterns.yaml`:

```yaml
patterns:
  - id: my_custom_pattern
    name: "My Custom Pattern"
    description: >
      Brief description of what causes this flaky behaviour.
    keywords:
      - some_keyword
      - another_keyword
    robot_keywords:
      - My Robot Keyword
    error_patterns:
      - "SomeError.*message"
    fix_template: |
      Explanation of how to fix it:

      ```python
      # example fix code
      ```
    severity_weight: 2   # 1 (low) to 3 (high)
```

No code changes are required; the pattern is picked up automatically on the next run.

---

## Architecture

```
run_flaky_analysis.py (CLI)
        │
        ▼
FlakyTestAnalysisSkill.run_analysis()
        │
        ├─── RobotOutputParser  ──► ParsedRun[] (test results per file)
        │
        ├─── MetricsEngine      ──► TestMetrics[] (failure rate, score, timestamps)
        │
        ├─── PatternDatabase    ──► matched Pattern[] per failed test
        │
        ├─── Recommender        ──► Recommendation[] (fix templates)
        │
        ├─── Claude API         ──► ai_summary (optional)
        │
        └─── JiraClient         ──► POST comment (optional)
```

### Flakiness Score Definitions

| Score | Criteria |
|---|---|
| **High** | Test has both passing and failing runs; failure rate ≥ 50% |
| **Medium** | Test has both passing and failing runs; failure rate 20–49% |
| **Low** | Test has both passing and failing runs; failure rate < 20% |
| **Stable** | Test result is consistent (all pass or all fail) across all runs |

> A "consistently failing" test is **not** classified as flaky – it should be fixed or investigated separately.

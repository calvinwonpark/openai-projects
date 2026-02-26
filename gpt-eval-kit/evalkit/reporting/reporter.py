import json
from typing import Any, Dict, List


def make_markdown_report(manifest: Dict[str, Any], summary: Dict[str, Any], failures: List[Dict[str, Any]]) -> str:
    total = int(summary.get("total_cases", 0))
    passed = int(summary.get("passed_cases", 0))
    failed = int(summary.get("failed_cases", 0))
    lines = [
        "# Eval Run Report",
        "",
        f"- Run ID: `{manifest.get('run_id')}`",
        f"- Mode: `{manifest.get('mode')}`",
        f"- Suite: `{manifest.get('suite_path')}`",
        f"- Total: **{total}** | Passed: **{passed}** | Failed: **{failed}**",
        "",
        "## Performance Metrics",
        "",
        "```json",
        json.dumps(summary.get("metrics", {}), ensure_ascii=False, indent=2),
        "```",
    ]
    confusion = (summary.get("metrics") or {}).get("confusion_matrix") or {}
    if confusion:
        lines += [
            "",
            "## Routing Confusion Matrix",
            "",
            "```json",
            json.dumps(confusion, ensure_ascii=False, indent=2),
            "```",
        ]

    tool_summary = summary.get("tool_summary") or {}
    if tool_summary:
        lines += [
            "",
            "## Tool Metrics",
            "",
            f"- Precision mean: `{tool_summary.get('precision_mean')}`",
            f"- Recall mean: `{tool_summary.get('recall_mean')}`",
        ]
        mismatches = tool_summary.get("top_mismatches") or []
        if mismatches:
            lines += ["", "Top mismatches:"]
            for m in mismatches[:5]:
                lines.append(
                    f"- `{m.get('id')}` expected={m.get('expected_tools')} actual={m.get('actual_tools')}"
                )

    schema_errors = summary.get("schema_errors") or []
    if schema_errors:
        lines += ["", "## Schema Errors (first 3)", ""]
        for err in schema_errors[:3]:
            lines.append(f"- {str(err)[:180]}")

    if failures:
        lines += ["", "## Failures", ""]
        for f in failures[:50]:
            lines.append(f"- `{f.get('id')}`: {'; '.join(f.get('failures', []))}")
            schema_errors = f.get("schema_errors") or []
            if schema_errors:
                for err in schema_errors[:3]:
                    path = err.get("path", "$") if isinstance(err, dict) else "$"
                    msg = err.get("message", str(err)) if isinstance(err, dict) else str(err)
                    lines.append(f"  - schema: `{path}` {str(msg)[:180]}")
            parse_error = f.get("parse_error")
            if parse_error:
                lines.append(f"  - parse_error: {str(parse_error)[:200]}")
    return "\n".join(lines) + "\n"


def make_diff_markdown(run_id: str, baseline_path: str, regressions: List[str], failures: List[Dict[str, Any]] = None) -> str:
    lines = [
        "# Baseline Diff",
        "",
        f"- Run: `{run_id}`",
        f"- Baseline: `{baseline_path}`",
        "",
    ]
    if not regressions:
        lines += ["**Status:** PASS", ""]
    else:
        lines += ["**Status:** FAIL", "", "## Regressions", ""]
        for r in regressions:
            lines.append(f"- {r}")
        lines += ["", "## Top Regressions", ""]
        for r in regressions[:5]:
            lines.append(f"- {r}")
    failures = failures or []
    schema_related = [f for f in failures if f.get("schema_errors") or f.get("parse_error")]
    if schema_related:
        lines += ["", "## Schema/Parse Failures", ""]
        for f in schema_related[:10]:
            lines.append(f"- `{f.get('id')}`")
            for err in (f.get("schema_errors") or [])[:3]:
                path = err.get("path", "$") if isinstance(err, dict) else "$"
                msg = err.get("message", str(err)) if isinstance(err, dict) else str(err)
                lines.append(f"  - schema: `{path}` {str(msg)[:180]}")
            if f.get("parse_error"):
                lines.append(f"  - parse_error: {str(f.get('parse_error'))[:200]}")
    return "\n".join(lines) + "\n"

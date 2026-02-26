import argparse
import json
import os
import sys

from evalkit.reporting.reporter import make_diff_markdown, make_markdown_report
from evalkit.runners.runner import run_suite


def _load_json(path: str):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _cmd_run(args: argparse.Namespace) -> int:
    run_dir, out = run_suite(
        suite_path=args.suite,
        mode=args.mode,
        app_url=args.app_url,
        model=args.model,
        baseline_dir=args.baseline,
        update_baseline=args.update_baseline,
    )
    print(f"Run complete: {run_dir}")
    print(f"Summary: {run_dir}/summary.json")
    print(f"Report:  {run_dir}/report.md")
    print(f"Diff:    {run_dir}/diff.md")
    if out["failures"]:
        print(f"Case failures: {len(out['failures'])}")
        return 1
    if out["regressions"]:
        print("Regression failures:")
        for r in out["regressions"]:
            print(f" - {r}")
        return 1
    return 0


def _cmd_report(args: argparse.Namespace) -> int:
    run_dir = args.run
    manifest = _load_json(os.path.join(run_dir, "manifest.json"))
    summary = _load_json(os.path.join(run_dir, "summary.json"))
    failures = []
    if summary.get("failed_cases", 0):
        results_path = os.path.join(run_dir, "results.jsonl")
        with open(results_path, "r", encoding="utf-8") as f:
            for line in f:
                row = json.loads(line)
                if not row.get("passed"):
                    failures.append({"id": row.get("id"), "failures": row.get("failures", [])})

    if args.format == "md":
        text = make_markdown_report(manifest, summary, failures)
        out_path = os.path.join(run_dir, "report.md")
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(text)
        print(out_path)
        return 0

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def _cmd_diff(args: argparse.Namespace) -> int:
    baseline_path = os.path.join(args.baseline, "summary.json")
    run_summary_path = os.path.join(args.run, "summary.json")
    if not os.path.exists(baseline_path):
        print(f"baseline missing: {baseline_path}")
        return 1
    if not os.path.exists(run_summary_path):
        print(f"run summary missing: {run_summary_path}")
        return 1

    baseline = _load_json(baseline_path)
    run_summary = _load_json(run_summary_path)
    regressions = compare_metrics(run_summary.get("metrics", {}), baseline.get("metrics", {}))
    diff_md = make_diff_markdown(os.path.basename(args.run.rstrip("/")), baseline_path, regressions)
    out_path = os.path.join(args.run, "diff.md")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(diff_md)
    print(out_path)
    if regressions:
        for r in regressions:
            print(f"- {r}")
        return 1
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="evalkit", description="OpenAI-first deployment-grade eval framework.")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="Run an evaluation suite.")
    run.add_argument("--suite", required=True, help="Suite JSONL path.")
    run.add_argument("--mode", required=True, choices=["offline", "http_app", "openai"], help="Adapter mode.")
    run.add_argument("--app-url", default=os.getenv("EVALKIT_APP_URL", "http://localhost:8000"))
    run.add_argument("--model", default=os.getenv("OPENAI_MODEL", "gpt-4o-mini"))
    run.add_argument("--baseline", default=None)
    run.add_argument("--update-baseline", action="store_true")
    run.set_defaults(func=_cmd_run)

    report = sub.add_parser("report", help="Render report for an existing run.")
    report.add_argument("--run", required=True, help="Run directory, e.g. runs/<id>")
    report.add_argument("--format", choices=["md", "json"], default="md")
    report.set_defaults(func=_cmd_report)

    diff = sub.add_parser("diff", help="Diff run summary against baseline.")
    diff.add_argument("--baseline", required=True, help="Baseline directory, e.g. baselines/main")
    diff.add_argument("--run", required=True, help="Run directory, e.g. runs/<id>")
    diff.set_defaults(func=_cmd_diff)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    rc = args.func(args)
    sys.exit(rc)


if __name__ == "__main__":
    main()

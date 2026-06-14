#!/usr/bin/env python3
"""
Style Linter for academic report .md files.

Usage:
    python -m lint.lint content-md/report.md
    python -m lint.lint content-md/ --verbose
    python -m lint.lint content-md/report.md --level error,warning

Supports:
    --level    Comma-separated: error,warning,info (default: all)
    --rules    Path to rules directory (default: lint/rules/)
    --config   Path to config JSON (for placeholder checking)
    --verbose  Show rule metadata per issue
    --json     Output as JSON
"""
import argparse
import json
import sys
import os
from pathlib import Path

# Ensure the project root is in path
_script_dir = Path(__file__).resolve().parent.parent
if str(_script_dir) not in sys.path:
    sys.path.insert(0, str(_script_dir))

from lint.lint_engine import LintEngine, format_issues, format_checklist


def main():
    parser = argparse.ArgumentParser(
        description="Style Linter for academic report .md files",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m lint.lint content-md/report.md
  python -m lint.lint content-md/ --level error,warning
  python -m lint.lint content-md/report.md --json
        """)
    parser.add_argument("target", help="Path to .md file or directory")
    parser.add_argument("--level", default="error,warning,info",
                        help="Comma-separated levels to show (error,warning,info)")
    parser.add_argument("--rules", default=None,
                        help="Path to rules directory (default: lint/rules/)")
    parser.add_argument("--config", default=None,
                        help="Path to config JSON (for placeholder resolution)")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="Show full issue details")
    parser.add_argument("--json", action="store_true",
                        help="Output as JSON")
    parser.add_argument("--checklist", action="store_true",
                        help="Output as markdown checklist grouped by rule")
    parser.add_argument("--fix", action="store_true",
                        help="Auto-fix mechanical issues (em-dash, double-space) in-place")

    args = parser.parse_args()
    show_levels = set(args.level.split(","))

    # Resolve rules dir
    if args.rules:
        rules_dir = args.rules
    else:
        rules_dir = os.path.join(os.path.dirname(__file__), "rules")
    rules_dir = os.path.abspath(rules_dir)

    # Init engine
    engine = LintEngine(rules_dir=rules_dir, config_path=args.config)

    # Collect files
    target = args.target
    if os.path.isfile(target):
        files = [target]
    elif os.path.isdir(target):
        files = sorted(str(p) for p in Path(target).rglob("*.md"))
        if not files:
            print(f"No .md files found in {target}")
            sys.exit(1)
    else:
        print(f"ERROR: Target not found: {target}")
        sys.exit(1)

    # Auto-fix before linting if requested
    if args.fix:
        for fp in files:
            fixed = engine.fix_file(fp)
            if fixed:
                print(f"  [fix] Applied fixes to {os.path.basename(fp)}")

    # Run linter
    all_issues = []
    for fp in files:
        issues = engine.lint_file(fp)
        all_issues.extend(issues)

    # Output
    if args.json:
        output = {
            "files": files,
            "issues": all_issues,
            "summary": {
                "total": len(all_issues),
                "errors": sum(1 for i in all_issues if i["level"] == "error"),
                "warnings": sum(1 for i in all_issues if i["level"] == "warning"),
                "info": sum(1 for i in all_issues if i["level"] == "info"),
            }
        }
        print(json.dumps(output, ensure_ascii=False, indent=2))
    elif args.checklist:
        result = format_checklist(all_issues, show_levels)
        print(result)
    else:
        result = format_issues(all_issues, show_levels)
        if result:
            print(result)
        else:
            print("No issues found.")

    # Exit code
    error_count = sum(1 for i in all_issues if i["level"] == "error")
    sys.exit(1 if error_count > 0 else 0)


if __name__ == "__main__":
    main()

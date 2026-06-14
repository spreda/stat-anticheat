#!/usr/bin/env python3
"""
Lint Filter — stdin/stderr linter for .md, grep-compatible.

Reads markdown from stdin, writes issues to stderr, passes stdin through to stdout.
Can be used in a pipe:
    cat report.md | python utils/lint_filter.py 2>&1 | pandoc ...
    python utils/lint_filter.py < report.md --checklist

Options:
    --checklist  Output as markdown checklist instead of per-line list.
    --fix        Auto-fix mechanical issues in-place (reads file, not stdin).
    --file PATH  Lint a file instead of stdin.
    --level      Comma-separated: error,warning,info (default: all)
"""

import argparse
import sys
import os
from pathlib import Path

_script_dir = Path(__file__).resolve().parent.parent
if str(_script_dir) not in sys.path:
    sys.path.insert(0, str(_script_dir))

from lint.lint_engine import LintEngine, format_issues, format_checklist


def main():
    parser = argparse.ArgumentParser(description="Lint markdown via stdin or file mode.")
    parser.add_argument("--checklist", action="store_true", help="Output as markdown checklist instead of per-line issue list.")
    parser.add_argument("--fix", action="store_true", help="Auto-fix mechanical issues in-place when a file path is provided.")
    parser.add_argument("--file", help="Lint a file instead of stdin.")
    parser.add_argument("--level", default="error,warning,info", help="Comma-separated levels to show: error,warning,info.")
    args = parser.parse_args()

    checklist = args.checklist
    do_fix = args.fix
    file_path = args.file
    show_levels = set(args.level.split(","))

    if file_path:
        # File mode
        if not os.path.exists(file_path):
            print(f"ERROR: File not found: {file_path}", file=sys.stderr)
            sys.exit(1)
        engine = LintEngine()
        if do_fix:
            fixed = engine.fix_file(file_path, backup=True)
            if fixed:
                print(f"  [fix] Applied {fixed} fix(es)", file=sys.stderr)
        issues = engine.lint_file(file_path)
        if checklist:
            print(format_checklist(issues, show_levels), file=sys.stderr)
        else:
            print(format_issues(issues, show_levels), file=sys.stderr)
        sys.exit(1 if sum(1 for i in issues if i["level"] == "error") > 0 else 0)
    else:
        # Stdin mode: pass through to stdout, lint to stderr
        text = sys.stdin.buffer.read().decode("utf-8", errors="replace")

        # Write stdin to stdout, filtering through engine analysis
        print(text, end="")

        # Analyze
        engine = LintEngine()
        issues = engine._analyze_text(text, "<stdin>")
        if issues:
            if checklist:
                print(format_checklist(issues, show_levels), file=sys.stderr)
            else:
                print(format_issues(issues, show_levels), file=sys.stderr)
        sys.exit(0)


if __name__ == "__main__":
    main()
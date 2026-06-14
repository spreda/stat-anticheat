#!/usr/bin/env python3
"""
Dash Filter — stdin/stdout normalizer for .md dashes.

Purpose: .md source files use only '--' (two ASCII hyphens) to represent dashes.
Em-dash (—) and en-dash (–) are NOT allowed in source .md.
Pandoc converts '--' to en-dash and '---' to em-dash in .docx output.

Modes:
  1. expand: converts ' - ' (space-hyphen-space, natural typing)  → ' -- '
     Also normalizes — and – to --.
  2. normalize (default): converts — and – to --.

Usage:
    type content-md/report.md | python utils/dash_filter.py --expand > output.md
    python utils/dash_filter.py < content-md/report.md > output.md

Options:
    --expand   Also convert ' - ' to ' -- ' for manual editing convenience.
    --verbose  Print debug info to stderr.
"""

import argparse
import re
import sys


def normalize(text: str) -> str:
    """Convert all em-dash (—) and en-dash (–) to --."""
    text = text.replace("—", "--")
    text = text.replace("–", "--")
    return text


def expand(text: str) -> str:
    """Convert ' - ' (space-hyphen-space) to ' -- ' for natural typing.
    Avoids list markers ('- ' at line start) and already-normalized ' -- '."""
    # First normalize any existing —/–
    text = normalize(text)
    # Replace ' - ' but NOT line-start '- ' (list markers)
    text = re.sub(
        r"(?<=[\u0430-\u044f\u0451a-zA-Z0-9)])\s-\s(?=[\u0430-\u044f\u0451a-zA-Z0-9(«])",
        " -- ", text)
    return text


def main():
    parser = argparse.ArgumentParser(
        description="Normalize dashes in .md: —/– → --")
    parser.add_argument("--expand", action="store_true",
                        help="Convert ' - ' to ' -- ' for manual editing.")
    parser.add_argument("--verbose", action="store_true",
                        help="Print debug info to stderr.")
    args = parser.parse_args()

    text = sys.stdin.buffer.read().decode("utf-8", errors="replace")
    original = text

    if args.expand:
        text = expand(text)
    else:
        text = normalize(text)

    if args.verbose and text != original:
        changes = sum(1 for a, b in zip(original, text) if a != b)
        print(f"  [dash] {changes} char(s) changed", file=sys.stderr)

    sys.stdout.buffer.write(text.encode("utf-8"))


if __name__ == "__main__":
    main()

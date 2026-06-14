#!/usr/bin/env python3
"""
Calc Filter — stdin/stdout preprocessor for .md with calculations.

Reads markdown from stdin, resolves {placeholders}, evaluates $$/$$$/$var,
writes expanded markdown to stdout.

Usage:
    type content-md/report.md | python utils/calc_filter.py --config config_practice.json > output.md
    python utils/calc_filter.py --config config_practice.json < content-md/report.md > output.md
    python utils/generate_report.py   # thin orchestrator

Options:
    --config PATH   Required. Path to config JSON (for placeholders + data).
    --verbose       Print debug info to stderr.
    --quiet         Default. Only errors to stderr.
"""

import argparse
import sys
import json
import re
import math
from pathlib import Path

_script_dir = Path(__file__).resolve().parent.parent
QUIET = "--verbose" not in sys.argv


def log(msg):
    if not QUIET:
        print(msg, file=sys.stderr)


# ── Safe eval namespace ──

_SAFE_NS = {
    "__builtins__": {},
    "sin": math.sin, "cos": math.cos, "tan": math.tan,
    "asin": math.asin, "acos": math.acos, "atan": math.atan,
    "sqrt": math.sqrt, "abs": abs, "round": round,
    "ceil": math.ceil, "floor": math.floor,
    "exp": math.exp, "log": math.log, "log10": math.log10,
    "min": min, "max": max,
    "pi": math.pi, "e": math.e,
    "True": True, "False": False,
}


# ── Russian number formatting ──

def _fmt_num(val, fmt_spec=None):
    """Format number with Russian locale (space = thousand sep, comma = decimal).
    
    Exception: version numbers like 3.14 are kept with dot (not converted to comma).
    """
    if isinstance(val, bool):
        return "Да" if val else "Нет"
    if isinstance(val, str):
        # Keep version numbers with dot: 3.14, 2.1, etc.
        if re.match(r'^\d+\.\d+(\.\d+)*$', val):
            return val
        return val
    if isinstance(val, (int, float)):
        if fmt_spec:
            try:
                s = format(val, fmt_spec)
            except Exception:
                s = str(val)
            s = s.replace(",", " ").replace(".", ",")
            return s
        if isinstance(val, int) or val == int(val):
            return f"{int(val):,}".replace(",", " ")
        s = f"{val:.10f}".rstrip("0").rstrip(".")
        if "." in s:
            whole, frac = s.split(".")
            whole = f"{int(whole):,}".replace(",", " ")
            return f"{whole},{frac}"
        return f"{int(s):,}".replace(",", " ")
    return str(val)


# ── Placeholder map ──

_SYSTEM_KEYS = {"gost", "style", "paths", "cover_page",
                "report_type", "report_type_label", "template",
                "_calc", "_placeholders", "_linter_issues"}


def _build_placeholder_map(config):
    """Build {placeholder} → str from config."""
    pmap = {}

    def _register_value(parts, value):
        pmap[".".join(parts)] = str(value)
        if len(parts) >= 2:
            for i in range(2, len(parts) + 1):
                pmap["_".join(parts[-i:])] = str(value)
        if len(parts) >= 1:
            pmap[parts[-1]] = str(value)

    def _flatten(obj, prefix_parts):
        for k, v in obj.items():
            parts = prefix_parts + [k]
            if isinstance(v, dict):
                _flatten(v, parts)
            else:
                _register_value(parts, v)

    for key, val in config.items():
        if key in _SYSTEM_KEYS:
            continue
        if isinstance(val, dict):
            _flatten(val, [key])
        else:
            pmap[key] = str(val)
    return pmap


def _yaml_scalar(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return json.dumps(str(value), ensure_ascii=False)


def _dump_yaml(obj, indent=0):
    lines = []
    prefix = " " * indent
    if isinstance(obj, dict):
        for key, value in obj.items():
            if isinstance(value, (dict, list)):
                lines.append(f"{prefix}{key}:")
                lines.extend(_dump_yaml(value, indent + 2))
            else:
                lines.append(f"{prefix}{key}: {_yaml_scalar(value)}")
    elif isinstance(obj, list):
        for item in obj:
            if isinstance(item, (dict, list)):
                lines.append(f"{prefix}-")
                lines.extend(_dump_yaml(item, indent + 2))
            else:
                lines.append(f"{prefix}- {_yaml_scalar(item)}")
    else:
        lines.append(f"{prefix}{_yaml_scalar(obj)}")
    return lines


def _resolve_placeholders_in_obj(obj, pmap):
    if isinstance(obj, dict):
        return {key: _resolve_placeholders_in_obj(value, pmap) for key, value in obj.items()}
    if isinstance(obj, list):
        return [_resolve_placeholders_in_obj(item, pmap) for item in obj]
    if isinstance(obj, str):
        for key, val in pmap.items():
            obj = obj.replace("{" + key + "}", val)
        return obj
    return obj


def load_template(template_name):
    if not template_name:
        return {}
    tpl_path = _script_dir / "templates" / f"{template_name}.json"
    if not tpl_path.exists():
        log(f"  [calc] WARNING: template not found: {tpl_path}")
        return {}
    with tpl_path.open(encoding="utf-8") as f:
        return json.load(f)


def load_json_file(path):
    with Path(path).open(encoding="utf-8") as f:
        return json.load(f)


def load_config(config_path):
    config_path = Path(config_path)
    with config_path.open(encoding="utf-8") as f:
        cfg = json.load(f)

    full = {}
    data_refs = cfg.get("data", {})
    for key, path in data_refs.items():
        fp = Path(path)
        if not fp.is_absolute():
            fp = _script_dir / path
        if fp.exists():
            full[key] = load_json_file(fp)
        else:
            log(f"  [calc] WARNING: data file not found: {fp}")

    full["paths"] = cfg.get("paths", {})
    student = full.get("student", {})
    full["project"] = student.get("project", {})
    full["gost"] = full.get("style", {})

    for key in ["report_type", "report_type_label", "template"]:
        if key in cfg:
            full[key] = cfg[key]

    return full


def build_yaml_frontmatter(config):
    student = config.get("student", {})
    author = student.get("author", {})
    advisor = student.get("advisor", {})
    institution = student.get("institution", {})

    yaml_meta = {
        "title": student.get("theme", ""),
        "author": author.get("full_name", ""),
        "date": student.get("year", "2026"),
        "institution": institution.get("full", ""),
        "institution_short": institution.get("short", ""),
        "group": author.get("group", ""),
        "specialty": student.get("specialty", ""),
        "advisor_name": advisor.get("name", ""),
        "advisor_position": advisor.get("position", ""),
        "report_label": config.get("report_type_label", "Отчёт"),
    }
    if config.get("cover_page"):
        yaml_meta["cover_page"] = config["cover_page"]
    lines = ["---\n"] + [line + "\n" for line in _dump_yaml(yaml_meta)] + ["...\n", "\n"]
    return lines


def process_markdown(text, config, template):
    if template.get("cover_page"):
        config["cover_page"] = template["cover_page"]

    pmap = _build_placeholder_map(config)
    if config.get("cover_page"):
        config["cover_page"] = _resolve_placeholders_in_obj(config["cover_page"], pmap)

    calc = CalcEngine()
    text = calc.extract_inline_defs(text)
    out_lines = build_yaml_frontmatter(config)
    table_counter = 0

    for line in text.splitlines(keepends=True):
        stripped = line.strip()

        if stripped.startswith("$$") or stripped.startswith("$$$"):
            rendered, _ = calc.process_line(stripped)
            if rendered:
                out_lines.append(f"{rendered}\n")
            continue

        for key, val in sorted(pmap.items(), key=lambda kv: -len(kv[0])):
            line = line.replace("{" + key + "}", val)

        if line.strip().lower().startswith("table:"):
            table_counter += 1
            caption_raw = line.strip()[6:].strip()
            caption_clean = re.sub(r"^Таблица\s+\d+[\.\s]*", "", caption_raw, flags=re.IGNORECASE).strip()
            line = f"Таблица {table_counter}. {caption_clean}\n\n"

        line = calc.resolve_inline(line)

        def _fb(m):
            name = m.group(1)
            if name in calc.variables:
                return _fmt_num(calc.variables[name], m.group(2))
            if name in pmap:
                return pmap[name]
            return m.group(0)

        line = re.sub(r"(?<!\$)\$([a-zA-Z_а-яА-ЯёЁ][a-zA-Z_а-яА-ЯёЁ0-9]*)(?::([^ ]+))?", _fb, line)
        out_lines.append(line)

    return "".join(out_lines)


# ── CalcEngine (lightweight, no verbose baggage) ──

class CalcEngine:
    """Holds variables, evaluates $$/$$$ expressions."""

    def __init__(self):
        self.variables = {}

    def extract_inline_defs(self, text):
        """Replace {var=val} with val, store var."""
        def _replacer(m):
            name = m.group(1)
            raw = m.group(2).strip()
            try:
                val = float(raw.replace(",", ".")) if "." in raw or "," in raw else int(raw)
            except ValueError:
                val = raw
            self.variables[name] = val
            return raw
        return re.sub(r"\{([a-zA-Z_а-яА-ЯёЁ][a-zA-Z_а-яА-ЯёЁ0-9]*)=([^}]+)\}", _replacer, text)

    def evaluate(self, expr_str):
        ns = dict(_SAFE_NS)
        ns.update(self.variables)
        try:
            return float(eval(expr_str, ns))
        except Exception as e:
            raise ValueError(f"Calc error in '{expr_str}': {e}")

    def process_line(self, line):
        """Process one $$/$$$ line. Returns (rendered_text_or_None, is_sanity)."""
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            return None, False
        mode = None
        if stripped.startswith("$$?"):
            mode, rest = "sanity", stripped[3:].strip()
        elif stripped.startswith("$$$"):
            mode, rest = "hidden", stripped[3:].strip()
        elif stripped.startswith("$$"):
            mode, rest = "visible", stripped[2:].strip()
        else:
            return None, False
        if not rest:
            return None, False

        unit, msg = "", ""
        if "#" in rest:
            idx = rest.index("#")
            tail = rest[idx + 1:].strip()
            rest = rest[:idx].strip()
            if mode == "sanity":
                msg = tail
            else:
                unit = tail
        if not rest:
            return None, False

        if mode == "sanity":
            ns = dict(_SAFE_NS)
            ns.update(self.variables)
            try:
                ok = bool(eval(rest, ns))
            except Exception as e:
                ok = False
            if not ok:
                print(f"  WARNING: Sanity check FAILED — {rest}  ({msg})", file=sys.stderr)
            return None, True

        if "=" not in rest:
            return None, False
        eq_idx = rest.index("=")
        var_name = rest[:eq_idx].strip()
        after_eq = rest[eq_idx + 1:].strip()
        if not var_name or not after_eq:
            return None, False

        fmt_spec = None
        expr_str = after_eq
        if ":" in after_eq:
            col_idx = after_eq.rfind(":")
            pf = after_eq[col_idx + 1:].strip()
            if pf and (pf[0].isalpha() or pf[0] in ".,0"):
                fmt_spec = pf
                expr_str = after_eq[:col_idx].strip()
        if not expr_str:
            return None, False

        result = self.evaluate(expr_str)
        self.variables[var_name] = result
        if mode == "hidden":
            return None, False
        return f"{var_name} = {expr_str} = {_fmt_num(result, fmt_spec)} {unit}".strip(), True

    def resolve_inline(self, text):
        """Replace $var / $var:fmt / $$ in text."""
        def _replacer(m):
            if m.group(0) == "$$":
                return "$"
            name, fmt = m.group(1), m.group(2)
            if name in self.variables:
                return _fmt_num(self.variables[name], fmt)
            return m.group(0)
        return re.sub(r"\$\$|\$([a-zA-Z_а-яА-ЯёЁ][a-zA-Z_а-яА-ЯёЁ0-9]*)(?::([^ ]+))?", _replacer, text)


# ── Main filter ──

def main():
    parser = argparse.ArgumentParser(description="Preprocess markdown with placeholders and inline calculations.")
    parser.add_argument("--config", required=True, help="Path to the config JSON.")
    parser.add_argument("--verbose", action="store_true", help="Print debug info to stderr.")
    parser.add_argument("--quiet", action="store_true", help="Suppress progress output; only errors are printed.")
    args = parser.parse_args()

    global QUIET
    if args.quiet:
        QUIET = True
    elif args.verbose:
        QUIET = False
    else:
        QUIET = True

    try:
        config = load_config(args.config)
    except Exception as e:
        print(f"ERROR: loading config: {e}", file=sys.stderr)
        sys.exit(1)

    template = load_template(config.get("template", ""))
    markdown = sys.stdin.read()
    output = process_markdown(markdown, config, template)
    sys.stdout.write(output)


if __name__ == "__main__":
    main()
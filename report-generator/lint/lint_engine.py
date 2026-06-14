"""
Style linter engine for .md report files.

Loads rule sets from lint/rules/*.json, applies regex and structural checks,
produces formatted results with file:line references.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any


# ── DOCX namespace (used by DOCX checkers) ──
_W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


# ── Shared exclude patterns (used by all regex checks) ──

_EXCLUDES_GLOBAL = [
    r"\{[^}]+=[^}]+\}",         # inline var defs: {var=val}
    r"^\s*\$\$\$?.*$",          # calc lines: $$, $$$
    r"```[\s\S]*?```",          # code blocks
    r"`[^`\n]+`",               # inline code
]

_EXCLUDES_INTEXT = [
    r"^#{1,6}\s.*$",            # headings
    r"^\s*[-*]\s.*$",           # bullet list items
    r"^\s*\d+\.\s.*$",          # numbered list items
    r"^\|.*\|$",                # table rows
    r"^Table:.*$",             # table captions
    r"^!\[.*\]\(.*\)$",        # images
]


def _load_all_rules(rules_dir: str) -> list[dict]:
    """Load and merge all rule files from rules_dir, sorted by filename."""
    rules: list[dict] = []
    if not os.path.isdir(rules_dir):
        print(f"WARNING: Rules directory not found: {rules_dir}")
        return rules
    for fn in sorted(os.listdir(rules_dir)):
        if not fn.endswith(".json"):
            continue
        fp = os.path.join(rules_dir, fn)
        try:
            with open(fp, encoding="utf-8") as f:
                rules.extend(json.load(f))
        except Exception as e:
            print(f"  [lint] Error loading {fn}: {e}")
    return rules


def _find_line(text: str, pos: int) -> int:
    """Return 1-based line number for a character position."""
    return text[:pos].count("\n") + 1


def _build_excluded_ranges(text: str, rule: dict) -> list[tuple[int, int]]:
    """Collect (start, end) ranges to skip from rule exclude_patterns + globals + exclude_headings."""
    ranges: list[tuple[int, int]] = []
    flags = re.MULTILINE
    for ep in rule.get("exclude_patterns", []):
        for m in re.finditer(ep, text, flags=flags):
            ranges.append((m.start(), m.end()))
    for ep in _EXCLUDES_GLOBAL:
        for m in re.finditer(ep, text, flags=re.MULTILINE):
            ranges.append((m.start(), m.end()))
    if rule.get("context") == "intext":
        for ep in _EXCLUDES_INTEXT:
            for m in re.finditer(ep, text, flags=re.MULTILINE):
                ranges.append((m.start(), m.end()))
    # exclude_headings: skip entire sections under matching headings
    exclude_heads = rule.get("exclude_headings", [])
    if exclude_heads:
        lines = text.splitlines(keepends=True)
        heading_line_nums = []
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith("#"):
                h_text = stripped.lstrip("#").strip()
                if any(re.search(pat, h_text) for pat in exclude_heads):
                    heading_line_nums.append(i)
        for h_line in heading_line_nums:
            start_pos = sum(len(lines[j]) for j in range(h_line))
            end_pos = len(text)
            for next_h in [n for n in heading_line_nums if n > h_line]:
                next_pos = sum(len(lines[j]) for j in range(next_h))
                end_pos = min(end_pos, next_pos)
            ranges.append((start_pos, end_pos))
    return ranges


class LintEngine:
    """Main linter — loads rules, runs checks, returns issues."""

    def __init__(self, rules_dir: str | None = None, config_path: str | None = None) -> None:
        self.rules_dir = rules_dir or str(Path(__file__).parent / "rules")
        self.rules = _load_all_rules(self.rules_dir)
        self.config: dict[str, Any] = {}
        if config_path:
            try:
                with open(config_path, encoding="utf-8") as f:
                    self.config = json.load(f)
            except Exception as e:
                print(f"  [lint] WARNING: Could not load config: {e}")

    def lint_file(self, md_path: str) -> list[dict]:
        """Run all checks on a single .md file. Returns list of issues."""
        if not os.path.exists(md_path):
            return [{"file": md_path, "line": 0, "level": "error",
                     "rule": "file-not-found", "message": f"File not found: {md_path}"}]

        with open(md_path, encoding="utf-8") as f:
            text = f.read()

        issues: list[dict] = []
        lines = text.splitlines()
        md_dir = os.path.dirname(md_path)

        for rule in self.rules:
            try:
                if rule.get("type") == "regex":
                    issues.extend(self._check_regex(rule, text, md_path))
                elif rule.get("type") == "structural":
                    fn_name = f"_check_{rule.get('kind', '')}"
                    checker = getattr(self, fn_name, None)
                    if checker:
                        issues.extend(checker(rule, text, lines, md_path, md_dir))
            except Exception as e:
                issues.append(self._make_issue(md_path, 0, "error", rule.get("id", "unknown"),
                                                f"Checker {fn_name} failed: {e}"))
        return issues

    def _analyze_text(self, text: str, label: str = "<stdin>") -> list[dict]:
        """Analyze raw text (not from file) — used by stdin-based lint_filter."""
        issues: list[dict] = []
        lines = text.splitlines()
        for rule in self.rules:
            try:
                if rule.get("type") == "regex":
                    issues.extend(self._check_regex(rule, text, label))
                elif rule.get("type") == "structural":
                    fn_name = f"_check_{rule.get('kind', '')}"
                    checker = getattr(self, fn_name, None)
                    if checker:
                        issues.extend(checker(rule, text, lines, label, ""))
            except Exception as e:
                issues.append(self._make_issue(label, 0, "error", rule.get("id", "unknown"),
                                                f"Checker {fn_name} failed: {e}"))
        return issues

    def lint_docx(self, docx_path: str) -> list[dict]:
        """Run DOCX-specific checks on a generated .docx file.
        Validates paragraph styles: first-line indent, font, spacing, etc."""
        issues: list[dict] = []
        if not os.path.exists(docx_path):
            return [self._make_issue(docx_path, 0, "error", "file-not-found",
                                     f"DOCX not found: {docx_path}")]

        try:
            from docx import Document
            from docx.shared import Cm, Pt
            from docx.enum.text import WD_ALIGN_PARAGRAPH
        except ImportError:
            return [self._make_issue(docx_path, 0, "error", "import-error",
                                     "python-docx not installed — cannot validate DOCX")]

        doc = Document(docx_path)

        for rule in self.rules:
            if rule.get("type") != "docx":
                continue
            kind = rule.get("kind", "")
            try:
                fn_name = f"_docx_check_{kind}"
                checker = getattr(self, fn_name, None)
                if checker:
                    issues.extend(checker(rule, doc, docx_path))
            except Exception as e:
                issues.append(self._make_issue(
                    docx_path, 0, "error", rule.get("id", "unknown"),
                    f"DOCX checker {fn_name} failed: {e}"))

        return issues

    # ── DOCX checkers ──

    def _docx_check_paragraph_indents(self, rule, doc, docx_path):
        """Check that body paragraph styles have GOST first-line indent (1.25 cm).
        Body Text chain must inherit from Normal (indent=None) or have 1.25cm."""
        issues = []
        expected_indent = rule.get("expected_indent_cm", 1.25)
        # Styles that should have indent (inherit from Normal or explicit)
        body_chain = ["Body Text", "First Paragraph", "Compact"]
        # Styles that should have zero indent
        no_indent = ["List Bullet", "List Number", "Caption",
                     "Title", "Author", "Date", "Source Code"]

        style_names = [s.name for s in doc.styles]

        for sn in body_chain:
            if sn not in style_names:
                continue
            s = doc.styles[sn]
            val = s.paragraph_format.first_line_indent
            val_cm = None
            if val is not None:
                val_cm = val / 914400 * 2.54 if isinstance(val, (int, float)) else None
            # Body Text chain should NOT have explicit 0 — must inherit Normal's indent
            if val is not None and val_cm is not None and val_cm == 0:
                issues.append(self._make_issue(
                    docx_path, 0, rule.get("level", "error"),
                    rule["id"],
                    f"Body Text chain style '{sn}': first_line_indent={val_cm:.2f}cm (explicit 0). "
                    f"Must inherit Normal's {expected_indent}cm — remove explicit first_line_indent."))
            elif val is not None and val_cm is not None and abs(val_cm - expected_indent) > 0.01:
                issues.append(self._make_issue(
                    docx_path, 0, rule.get("level", "error"),
                    rule["id"],
                    f"Body Text chain style '{sn}': first_line_indent={val_cm:.2f}cm. "
                    f"Expected ~{expected_indent}cm."))

        # Check Normal itself
        if "Normal" in style_names:
            n = doc.styles["Normal"]
            nv = n.paragraph_format.first_line_indent
            if nv is None:
                issues.append(self._make_issue(
                    docx_path, 0, rule.get("level", "error"),
                    rule["id"],
                    f"Normal style: first_line_indent=None (not set). Expected {expected_indent}cm."))
            else:
                nv_cm = nv / 914400 * 2.54 if isinstance(nv, (int, float)) else None
                if nv_cm is not None and abs(nv_cm - expected_indent) > 0.01:
                    issues.append(self._make_issue(
                        docx_path, 0, rule.get("level", "error"),
                        rule["id"],
                        f"Normal style: first_line_indent={nv_cm:.2f}cm. Expected {expected_indent}cm."))

        # Check that no_indent styles have zero or None
        for sn in no_indent:
            if sn not in style_names:
                continue
            s = doc.styles[sn]
            val = s.paragraph_format.first_line_indent
            if val is not None:
                val_cm = val / 914400 * 2.54 if isinstance(val, (int, float)) else None
                if val_cm is not None and abs(val_cm) > 0.01:
                    issues.append(self._make_issue(
                        docx_path, 0, rule.get("level", "warning"),
                        rule["id"],
                        f"Style '{sn}': first_line_indent={val_cm:.2f}cm (should be 0)."))

        return issues

    def _docx_check_heading_indents(self, rule, doc, docx_path):
        """Check that heading styles have the expected first-line indent (1.25 cm)."""
        issues = []
        expected_indent = rule.get("expected_indent_cm", 1.25)
        for sn in ["Heading 1", "Heading 2", "Heading 3"]:
            if sn not in [s.name for s in doc.styles]:
                continue
            s = doc.styles[sn]
            val = s.paragraph_format.first_line_indent
            if val is None:
                issues.append(self._make_issue(
                    docx_path, 0, rule.get("level", "error"),
                    rule["id"],
                    f"Heading style '{sn}': first_line_indent=None (not set). Must be {expected_indent}cm."))
            else:
                val_cm = val / 914400 * 2.54 if isinstance(val, (int, float)) else None
                if val_cm is not None and abs(val_cm - expected_indent) > 0.01:
                    issues.append(self._make_issue(
                        docx_path, 0, rule.get("level", "error"),
                        rule["id"],
                        f"Heading style '{sn}': first_line_indent={val_cm:.2f}cm (should be {expected_indent}cm)."))
            # Also check XML: must have ind firstLine=expected
            pPr = s.element.find(f"{{{_W_NS}}}pPr")
            if pPr is not None:
                ind = pPr.find(f"{{{_W_NS}}}ind")
                if ind is None or ind.get(f"{{{_W_NS}}}firstLine") is None:
                    issues.append(self._make_issue(
                        docx_path, 0, rule.get("level", "error"),
                        rule["id"],
                        f"Heading style '{sn}': missing <w:ind w:firstLine=\"{int(expected_indent*567)}\"/> XML element."))
        return issues

    def _docx_check_list_indents(self, rule, doc, docx_path):
        """Check that list numbering: left=expected_left_cm,
        hanging=expected_hanging_cm, tab pos=expected_tab_pos_cm.
        Number sticks out by hanging amount, continuation lines align at left."""
        issues = []
        try:
            import zipfile
            from lxml import etree
        except ImportError:
            return issues

        expected_left = rule.get("expected_left_cm", 1.25)
        expected_hanging = rule.get("expected_hanging_cm", 0.75)
        expected_tab = rule.get("expected_tab_pos_cm", expected_left - expected_hanging)
        expected_left_twips = int(expected_left * 567)
        expected_hanging_twips = int(expected_hanging * 567)
        expected_tab_twips = int(expected_tab * 567)

        import io
        try:
            z = zipfile.ZipFile(docx_path)
            xml = z.read('word/numbering.xml')
            z.close()
        except Exception:
            issues.append(self._make_issue(
                docx_path, 0, "warning", rule["id"],
                "Could not read word/numbering.xml from DOCX."))
            return issues

        root = etree.fromstring(xml)
        ns = _W_NS

        for anum in root.findall(f'{{{ns}}}abstractNum'):
            for lvl in anum.findall(f'{{{ns}}}lvl'):
                ilvl = lvl.get(f'{{{ns}}}ilvl')
                if ilvl != '0' and ilvl != '1':
                    continue
                ppr = lvl.find(f'{{{ns}}}pPr')
                if ppr is None:
                    continue
                ind = ppr.find(f'{{{ns}}}ind')
                if ind is None:
                    issues.append(self._make_issue(
                        docx_path, 0, rule.get("level", "error"),
                        rule["id"],
                        f"Missing <ind> in numbering level {ilvl}."))
                    continue
                left = int(ind.get(f'{{{ns}}}left', '0'))
                hanging = int(ind.get(f'{{{ns}}}hanging', '0'))

                if abs(left - expected_left_twips) > 20:
                    issues.append(self._make_issue(
                        docx_path, 0, rule.get("level", "error"),
                        rule["id"],
                        f"Level {ilvl}: left={left} ({left/567:.2f}cm). "
                        f"Expected {expected_left_twips} ({expected_left:.2f}cm)."))

                if hanging != expected_hanging_twips:
                    issues.append(self._make_issue(
                        docx_path, 0, rule.get("level", "error"),
                        rule["id"],
                        f"Level {ilvl}: hanging={hanging} ({hanging/567:.2f}cm). "
                        f"Expected {expected_hanging_twips} ({expected_hanging_twips/567:.2f}cm) (left={expected_left}cm, выступ)."))

                # Check tab position (inside pPr)
                tabs = ppr.find(f'{{{ns}}}tabs') if ppr is not None else None
                found_tab = False
                if tabs is not None:
                    for t in tabs.findall(f'{{{ns}}}tab'):
                        if t.get(f'{{{ns}}}val') == 'num':
                            found_tab = True
                            tab_pos = int(t.get(f'{{{ns}}}pos', '0'))
                            if abs(tab_pos - expected_tab_twips) > 20:
                                issues.append(self._make_issue(
                                    docx_path, 0, rule.get("level", "error"),
                                    rule["id"],
                                    f"Level {ilvl}: tab pos={tab_pos} ({tab_pos/567:.2f}cm). "
                                    f"Expected {expected_tab_twips} ({expected_tab:.2f}cm)."))
                if not found_tab:
                    issues.append(self._make_issue(
                        docx_path, 0, rule.get("level", "error"),
                        rule["id"],
                        f"Level {ilvl}: missing num tab stop."))

        return issues

    def _docx_check_table_style(self, rule, doc, docx_path):
        """Check that Table style has font_size=12, alignment=JUSTIFY, first_line_indent=0."""
        from docx.enum.text import WD_ALIGN_PARAGRAPH
        issues = []
        expected_font = rule.get("expected_font_size", 12)
        expected_align = rule.get("expected_alignment", "JUSTIFY")
        expected_indent = rule.get("expected_first_indent_cm", 0)

        if "Table" not in [s.name for s in doc.styles]:
            return issues

        tbl = doc.styles["Table"]
        # Font size
        if tbl.font.size:
            fs = tbl.font.size
            fs_pt = fs / 12700  # EMU to pt
            if abs(fs_pt - expected_font) > 0.5:
                issues.append(self._make_issue(
                    docx_path, 0, rule.get("level", "error"),
                    rule["id"],
                    f"Table style: font_size={fs_pt:.0f}pt. Expected {expected_font}pt."))
        else:
            issues.append(self._make_issue(
                docx_path, 0, rule.get("level", "error"),
                rule["id"],
                f"Table style: font_size not set. Expected {expected_font}pt."))

        # Alignment
        pf = tbl.paragraph_format
        align_map = {
            None: "None",
            WD_ALIGN_PARAGRAPH.LEFT: "LEFT",
            WD_ALIGN_PARAGRAPH.CENTER: "CENTER",
            WD_ALIGN_PARAGRAPH.RIGHT: "RIGHT",
            WD_ALIGN_PARAGRAPH.JUSTIFY: "JUSTIFY",
        }
        actual_align = align_map.get(pf.alignment, str(pf.alignment))
        if actual_align != expected_align:
            issues.append(self._make_issue(
                docx_path, 0, rule.get("level", "error"),
                rule["id"],
                f"Table style: alignment={actual_align}. Expected {expected_align}."))

        # First-line indent
        if pf.first_line_indent is not None:
            indent_val = pf.first_line_indent
            indent_cm = indent_val / 914400 * 2.54 if isinstance(indent_val, (int, float)) else None
            if indent_cm is not None and abs(indent_cm - expected_indent) > 0.01:
                issues.append(self._make_issue(
                    docx_path, 0, rule.get("level", "error"),
                    rule["id"],
                    f"Table style: first_line_indent={indent_cm:.2f}cm. Expected {expected_indent}cm."))

        return issues

    def _docx_check_no_italic_in_heading(self, rule, doc, docx_path):
        """Check that no heading style has <w:i> or <w:iCs> in styles.xml."""
        return self._check_italic_in_styles(rule, docx_path, style_filter=lambda sid: sid.startswith("Heading") or sid.startswith("heading"))

    def _docx_check_no_italic_in_caption(self, rule, doc, docx_path):
        """Check that Caption style has no <w:i> or <w:iCs> in styles.xml."""
        issues = []
        try:
            import zipfile
            from lxml import etree
        except ImportError:
            return issues
        z = zipfile.ZipFile(docx_path)
        x = etree.fromstring(z.read("word/styles.xml"))
        ns = _W_NS
        for s in x.findall(f".{{{ns}}}style"):
            sid = s.get(f"{{{ns}}}styleId", "")
            if sid != "Caption":
                continue
            rp = s.find(f"{{{ns}}}rPr")
            if rp is not None:
                for tag in ("i", "iCs"):
                    if rp.find(f"{{{ns}}}{tag}") is not None:
                        issues.append(self._make_issue(
                            docx_path, 0, rule.get("level", "warning"),
                            rule["id"], rule["message"]))
                        break
        z.close()
        return issues

    def _check_italic_in_styles(self, rule, docx_path, style_filter):
        """Shared checker: find italic in styles matching style_filter."""
        issues = []
        try:
            import zipfile
            from lxml import etree
        except ImportError:
            return issues
        z = zipfile.ZipFile(docx_path)
        x = etree.fromstring(z.read("word/styles.xml"))
        ns = _W_NS
        for s in x.findall(f".{{{ns}}}style"):
            sid = s.get(f"{{{ns}}}styleId", "")
            if not style_filter(sid):
                continue
            rp = s.find(f"{{{ns}}}rPr")
            if rp is not None:
                for tag in ("i", "iCs"):
                    if rp.find(f"{{{ns}}}{tag}") is not None:
                        msg = rule["message"].replace("{style_id}", sid)
                        issues.append(self._make_issue(
                            docx_path, 0, rule.get("level", "error"),
                            rule["id"], msg))
                        break
        z.close()
        return issues

    def _docx_check_intro_one_page(self, rule, doc, docx_path):
        """Check that introduction text fits on one page by computing the
        estimated page number of the next Heading1 after 'ВВЕДЕНИЕ'.

        Uses actual text height (font size × line spacing × wrapping) and
        compares it to the available page content area. Reports the page
        number where the next section heading would land."""
        issues = []
        try:
            import zipfile
            from lxml import etree
        except ImportError:
            return issues

        char_factor = rule.get("char_width_factor", 0.45)

        z = zipfile.ZipFile(docx_path)
        doc_xml = etree.fromstring(z.read("word/document.xml"))
        styles_xml = etree.fromstring(z.read("word/styles.xml"))
        z.close()
        ns = _W_NS

        # ── 1. Page dimensions from sectPr ──
        body = doc_xml.find(f"{{{ns}}}body")
        sectPr = body.find(f"{{{ns}}}sectPr") if body is not None else None
        if sectPr is None:
            pg_h = 16838; pg_w = 11906
            margin_top = 1134; margin_bottom = 1134
            margin_left = 1701; margin_right = 850
        else:
            pgSz = sectPr.find(f"{{{ns}}}pgSz")
            pg_w = int(pgSz.get(f"{{{ns}}}w", "11906"))
            pg_h = int(pgSz.get(f"{{{ns}}}h", "16838"))
            pgMar = sectPr.find(f"{{{ns}}}pgMar")
            margin_top = int(pgMar.get(f"{{{ns}}}top", "1134"))
            margin_bottom = int(pgMar.get(f"{{{ns}}}bottom", "1134"))
            margin_left = int(pgMar.get(f"{{{ns}}}left", "1701"))
            margin_right = int(pgMar.get(f"{{{ns}}}right", "850"))
        usable_w = pg_w - margin_left - margin_right
        usable_h = pg_h - margin_top - margin_bottom

        # ── 2. Style defaults from Normal ──
        default_sz_half = 28
        default_line = 360
        for sty in styles_xml.findall(f"{{{ns}}}style"):
            sid = sty.get(f"{{{ns}}}styleId", "")
            if sid == "Normal":
                pPr = sty.find(f"{{{ns}}}pPr")
                if pPr is not None:
                    sp = pPr.find(f"{{{ns}}}spacing")
                    if sp is not None:
                        lv = sp.get(f"{{{ns}}}line")
                        if lv is not None:
                            default_line = int(lv)
                rPr = sty.find(f"{{{ns}}}rPr")
                if rPr is not None:
                    sz = rPr.find(f"{{{ns}}}sz")
                    if sz is not None:
                        default_sz_half = int(sz.get(f"{{{ns}}}val", "28"))
                break

        style_map = {sty.get(f"{{{ns}}}styleId"): sty
                     for sty in styles_xml.findall(f"{{{ns}}}style")
                     if sty.get(f"{{{ns}}}styleId")}

        def _sty_sz(style_id):
            sty = style_map.get(style_id)
            if sty is not None:
                rp = sty.find(f"{{{ns}}}rPr")
                if rp is not None:
                    e = rp.find(f"{{{ns}}}sz")
                    if e is not None:
                        return int(e.get(f"{{{ns}}}val"))
                bo = sty.find(f"{{{ns}}}basedOn")
                if bo is not None:
                    return _sty_sz(bo.get(f"{{{ns}}}val"))
            return default_sz_half

        def _sty_line(style_id):
            sty = style_map.get(style_id)
            if sty is not None:
                pPr = sty.find(f"{{{ns}}}pPr")
                if pPr is not None:
                    sp = pPr.find(f"{{{ns}}}spacing")
                    if sp is not None:
                        lv = sp.get(f"{{{ns}}}line")
                        if lv is not None:
                            return int(lv)
                bo = sty.find(f"{{{ns}}}basedOn")
                if bo is not None:
                    return _sty_line(bo.get(f"{{{ns}}}val"))
            return default_line

        def _eff_sz(ppr, style_id):
            if ppr is not None:
                r = ppr.find(f"{{{ns}}}rPr")
                if r is not None:
                    e = r.find(f"{{{ns}}}sz")
                    if e is not None:
                        return int(e.get(f"{{{ns}}}val"))
            return _sty_sz(style_id)

        def _eff_line(ppr, style_id):
            if ppr is not None:
                sp = ppr.find(f"{{{ns}}}spacing")
                if sp is not None:
                    lv = sp.get(f"{{{ns}}}line")
                    if lv is not None:
                        return int(lv)
            return _sty_line(style_id)

        def _sp_before(ppr):
            if ppr is None: return 0
            sp = ppr.find(f"{{{ns}}}spacing")
            if sp is not None:
                v = sp.get(f"{{{ns}}}before")
                return int(v) if v is not None else 0
            return 0

        def _sp_after(ppr):
            if ppr is None: return 0
            sp = ppr.find(f"{{{ns}}}spacing")
            if sp is not None:
                v = sp.get(f"{{{ns}}}after")
                return int(v) if v is not None else 0
            return 0

        # ── 3. Collect intro paragraphs (from 'ВВЕДЕНИЕ' to next Heading1) ──
        intro_paras = []
        in_intro = False
        next_heading = ""  # title of the next Heading1 after intro
        for p in doc_xml.findall(f".//{{{ns}}}p"):
            ppr = p.find(f"{{{ns}}}pPr")
            ps = ppr.find(f"{{{ns}}}pStyle") if ppr is not None else None
            sid = ps.get(f"{{{ns}}}val") if ps is not None else None
            txt = "".join(t.text or "" for t in p.findall(f".//{{{ns}}}t"))
            if not in_intro:
                if sid == "Heading1" and "ВВЕДЕНИЕ" in txt.upper():
                    in_intro = True
                    intro_paras.append((sid, txt, ppr))
                continue
            if sid == "Heading1":
                next_heading = txt
                break
            if txt.strip():
                intro_paras.append((sid, txt, ppr))

        if not intro_paras:
            return issues

        # ── 4. Compute total height in twips ──
        total_h = 0
        for sid, txt, ppr in intro_paras:
            sz_half = _eff_sz(ppr, sid)
            sz_pt = sz_half / 2.0
            line_ratio = _eff_line(ppr, sid) / 240.0
            line_h = int(round(sz_pt * 20 * line_ratio))
            before = _sp_before(ppr)
            after = _sp_after(ppr)

            # heading inside intro (the "ВВЕДЕНИЕ" itself) — one line + spacing
            if sid == "Heading1":
                total_h += line_h + before + after
                continue

            if not txt:
                total_h += line_h + before + after
                continue

            # chars per line: sz_pt * 20 = twips per pt, factor accounts for avg char width
            cpl = max(1, int(usable_w / (sz_pt * 20 * char_factor)))
            nlines = -(-len(txt) // cpl)  # ceil division
            total_h += nlines * line_h + before + after

        # ── 5. Compute estimated page number ──
        page = (-(-total_h // usable_h))  # ceil division
        next_name = next_heading or "следующего раздела"

        if page > 1:
            msg = (
                f"Введение не умещается на одной странице (заголовок "
                f"«{next_name}» на странице {page}). Сократи текст введения."
            )
            issues.append(self._make_issue(
                docx_path, 0, rule.get("level", "error"),
                rule["id"], msg))
        else:
            pct = int(100 * total_h / usable_h)
            msg = (
                f"Введение умещается на одной странице (занимает {total_h} "
                f"twips = {pct}% страницы)."
            )
            issues.append(self._make_issue(
                docx_path, 0, "info",
                "intro-page-count", msg))
        return issues

    def fix_file(self, md_path: str, backup: bool = True) -> int:
        """Auto-fix mechanical issues (em-dash, double-space).
        Applies all rules with 'fix' field, respecting exclude_patterns and exclude_headings.
        Returns count of fixes applied. Creates .bak backup if backup=True."""
        if not os.path.exists(md_path):
            print(f"  [fix] ERROR: File not found: {md_path}")
            return 0

        with open(md_path, encoding="utf-8") as f:
            text = f.read()

        original = text
        fixable = [r for r in self.rules if "fix" in r and r.get("type") == "regex"]

        for rule in fixable:
            fix = rule["fix"]
            pattern = rule.get("pattern", "")
            if not pattern:
                continue
            excluded = _build_excluded_ranges(text, rule)

            # Build list of (start, end, new_text) replacements, right-to-left
            matches = list(re.finditer(pattern, text, flags=re.MULTILINE))
            replacements = []
            for m in matches:
                if any(rs <= m.start() < re for rs, re in excluded):
                    continue
                old = fix["old"]
                new = fix["new"]
                is_regex_fix = fix.get("is_regex", False)
                matched = text[m.start():m.end()]
                if is_regex_fix:
                    # For regex-based fixes, replace matched text with new string
                    replacements.append((m.start(), m.end(), new))
                elif matched == old:
                    replacements.append((m.start(), m.end(), new))
            # Deduplicate overlapping matches (keep first/longest)
            replacements.sort(key=lambda x: x[0])
            deduped = []
            for start, end, newtxt in replacements:
                if deduped and start < deduped[-1][1]:
                    continue  # overlap — skip
                deduped.append((start, end, newtxt))
            # Apply right-to-left
            for start, end, newtxt in reversed(deduped):
                text = text[:start] + newtxt + text[end:]

        if text == original:
            return 0

        if backup:
            bak = md_path + ".bak"
            with open(bak, "w", encoding="utf-8") as f:
                f.write(original)
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(text)
        return 1

    def _make_issue(self, filepath: str, line: int, level: str, rule_id: str, message: str) -> dict:
        return {"file": filepath, "line": line, "level": level,
                "rule": rule_id, "message": message}

    def _check_regex(self, rule: dict, text: str, md_path: str) -> list[dict]:
        """Apply a regex pattern check with exclusion handling."""
        pattern = rule.get("pattern", "")
        if not pattern:
            return []
        excluded = _build_excluded_ranges(text, rule)
        issues: list[dict] = []
        for m in re.finditer(pattern, text, flags=re.MULTILINE):
            if any(rs <= m.start() < re for rs, re in excluded):
                continue
            msg = rule.get("message", f"Pattern match: {pattern}")
            if "{ref}" in msg:
                msg = msg.replace("{ref}", m.group(0).strip())
            issues.append(self._make_issue(md_path, _find_line(text, m.start()),
                                           rule.get("level", "warning"),
                                           rule.get("id", "unknown"), msg))
        return issues

    # ── Structural checkers ──

    def _check_single_item_list(self, rule, text, lines, md_path, md_dir):
        """Detect lists with only one item. Also catch last list at EOF."""
        issues = []
        in_list = False
        count = 0
        list_start_line = 0
        for i, line in enumerate(lines):
            stripped = line.strip()
            is_bullet = stripped.startswith("- ") and not stripped.startswith("--")
            is_numbered = re.match(r"^\d+\.\s", stripped)
            if is_bullet or is_numbered:
                if not in_list:
                    in_list = True
                    count = 1
                    list_start_line = i + 1
                else:
                    count += 1
            else:
                if in_list and count == 1:
                    issues.append(self._make_issue(md_path, list_start_line, rule.get("level", "error"),
                                                    rule["id"], rule["message"]))
                in_list = False
                count = 0
            # If last line and in single-item list
            if i == len(lines) - 1 and in_list and count == 1:
                issues.append(self._make_issue(md_path, list_start_line, rule.get("level", "error"),
                                                rule["id"], rule["message"]))
        return issues

    def _check_list_no_intro(self, rule, text, lines, md_path, md_dir):
        """Check that lists have an introductory paragraph before them.
        Emits ONE warning per list (at the first item), not per item.
        Skips lists under headings matching exclude_headings patterns."""
        issues = []
        in_list = False
        exclude_heads = rule.get("exclude_headings", [])

        def is_list_item(stripped):
            return (stripped.startswith("- ") and not stripped.startswith("--")) or \
                   re.match(r"^\d+\.\s", stripped)

        for i, line in enumerate(lines):
            stripped = line.strip()

            if is_list_item(stripped):
                if not in_list:
                    in_list = True
                    # Find the nearest preceding heading
                    heading = None
                    for j in range(i - 1, -1, -1):
                        if lines[j].strip().startswith("#"):
                            heading = lines[j].strip().lstrip("#").strip()
                            break
                    # Skip if heading matches any exclude pattern
                    if heading and any(re.search(pat, heading) for pat in exclude_heads):
                        continue
                    # Check previous non-empty line for intro
                    prev = i - 1
                    while prev >= 0 and not lines[prev].strip():
                        prev -= 1
                    if prev >= 0:
                        prev_stripped = lines[prev].strip()
                        if (prev_stripped.startswith("#") or
                            is_list_item(prev_stripped) or
                            prev_stripped.startswith("|") or
                            prev_stripped.startswith(">")):
                            issues.append(self._make_issue(md_path, i + 1,
                                                            rule.get("level", "warning"),
                                                            rule["id"], rule["message"]))
                # else: still same list — don't re-warn
            else:
                in_list = False
        return issues

    def _check_code_block_length(self, rule, text, lines, md_path, md_dir):
        """Warn on code blocks longer than max_lines."""
        issues = []
        max_lines = rule.get("max_lines", 10)
        in_block = False
        block_start = 0
        block_lines = 0
        for i, line in enumerate(lines):
            if line.strip().startswith("```"):
                if in_block:
                    # Closing
                    if block_lines > max_lines:
                        issues.append(self._make_issue(md_path, block_start,
                                                        rule.get("level", "warning"),
                                                        rule["id"],
                                                        rule["message"].replace("{max_lines}", str(max_lines))))
                    in_block = False
                else:
                    in_block = True
                    block_start = i + 1
                    block_lines = 0
            elif in_block:
                block_lines += 1
        return issues

    def _check_empty_heading(self, rule, text, lines, md_path, md_dir):
        """Check for headings with no text after them before next heading or end."""
        issues = []
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith("#") and not stripped.startswith("##"):
                # H1
                h_level = 1
                h_text = stripped.lstrip("#").strip()
            elif stripped.startswith("##") and not stripped.startswith("###"):
                h_level = 2
                h_text = stripped.lstrip("#").strip()
            elif stripped.startswith("###"):
                h_level = 3
                h_text = stripped.lstrip("#").strip()
            else:
                continue

            if not h_text:
                issues.append(self._make_issue(md_path, i + 1,
                                                rule.get("level", "info"),
                                                rule["id"], rule["message"]))
        return issues

    def _check_section_no_text(self, rule, text, lines, md_path, md_dir):
        """Section followed by another heading (no body text)."""
        issues = []
        headings = []
        for i, line in enumerate(lines):
            if line.strip().startswith("#"):
                headings.append(i)

        for idx, h_idx in enumerate(headings):
            # If next heading is immediate next line (or there's only blank lines between)
            next_h_idx = headings[idx + 1] if idx + 1 < len(headings) else len(lines)
            gap = next_h_idx - h_idx - 1
            if gap <= 0:
                issues.append(self._make_issue(md_path, h_idx + 1,
                                                rule.get("level", "info"),
                                                rule["id"], rule["message"]))
            else:
                # Check if gap only has blank lines
                all_blank = True
                for j in range(h_idx + 1, next_h_idx if idx + 1 < len(headings) else len(lines)):
                    if lines[j].strip() and not lines[j].strip().startswith("#"):
                        all_blank = False
                        break
                if all_blank and gap > 0:
                    issues.append(self._make_issue(md_path, h_idx + 1,
                                                    rule.get("level", "info"),
                                                    rule["id"], rule["message"]))
        return issues

    def _check_intro_too_long(self, rule, text, lines, md_path, md_dir):
        """Warn if the introduction section ('# ВВЕДЕНИЕ') exceeds max_lines.
        The introduction should fit on one page (~30 lines)."""
        max_lines = rule.get("max_lines", 30)
        issues = []
        in_intro = False
        intro_line_count = 0
        intro_start_line = 0
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith("# ") and "введение" in stripped.lower():
                in_intro = True
                intro_line_count = 0
                intro_start_line = i + 1
                continue
            if in_intro:
                if stripped.startswith("#"):
                    # Next heading — intro is over
                    break
                if stripped:
                    intro_line_count += 1
        if in_intro and intro_line_count > max_lines:
            issues.append(self._make_issue(
                md_path, intro_start_line, rule.get("level", "warning"),
                rule["id"],
                rule["message"].replace("{max_lines}", str(max_lines))))
        return issues

    def _check_lowercase_after_colon(self, rule, text, lines, md_path, md_dir):
        """Check that words after : or ; (including with newline) start with uppercase.
        Exceptions: proper names and abbreviations that have mixed case (e.g. Unity, C#, DirectX).
        Skips code blocks, tables, headings, images."""
        issues = []
        # Exceptions: common proper names and abbreviations in this document
        exceptions = {
            "unity", "directx", "windows", "visual", "studio", "git", "steam", "itch",
            "intel", "pentium", "ram", "hdd", "escape", "boat", "c#",
            "stdin", "stdout", "stderr", "input", "output",
        }

        in_code_block = False
        for i, line in enumerate(lines):
            stripped = line.strip()
            # Skip code blocks
            if stripped.startswith("```"):
                in_code_block = not in_code_block
                continue
            if in_code_block:
                continue
            # Skip headings, tables, images, var defs, calc lines
            if (stripped.startswith("#") or stripped.startswith("|") or
                stripped.startswith("!") or stripped.startswith("{") or
                stripped.startswith("$$")):
                continue

            # Check if line ends with : or ;
            if stripped.rstrip().endswith((":", ";")):
                marker = stripped.rstrip()[-1]
                # Find next non-empty line
                for j in range(i + 1, len(lines)):
                    nxt = lines[j].strip()
                    if not nxt:
                        continue
                    # Skip if next is code block, table, heading, image
                    if (nxt.startswith("```") or nxt.startswith("|") or
                        nxt.startswith("#") or nxt.startswith("{") or
                        nxt.startswith("$$")):
                        break
                    # Strip leading numbers like "1. " or "1) "
                    nxt_clean = re.sub(r"^\d+[\.\)]\s*", "", nxt)
                    # If next line is a list item (numbered or bullet), skip check
                    if re.match(r"^\d+[\.\)]\s", nxt) or nxt.startswith("- ") or nxt.startswith("* "):
                        break
                    # If next line is indented (list item without marker), skip check
                    if nxt.startswith("  ") or nxt.startswith("\t"):
                        break
                    # If previous line ends with colon and next line starts with lowercase,
                    # it's likely a list item without marker -- skip check
                    if stripped.rstrip().endswith(":") and nxt[0].islower():
                        break
                    # If next line starts with lowercase and contains ' -- ' (definition term),
                    # it's a term definition -- lowercase is intentional (e.g. "водомётный движитель -- ...")
                    if re.match(r"^[а-яё].* -- ", nxt) or re.match(r"^[а-яё][^–]*–", nxt):
                        break
                    # Find first word
                    m = re.search(r"[а-яёa-z][а-яёa-z]*", nxt_clean, re.IGNORECASE)
                    if m:
                        word = m.group()
                        if word[0].islower():
                            # Check if it's an exception
                            if word.lower() not in exceptions:
                                # Check if it has internal uppercase (proper name)
                                if not any(c.isupper() for c in word[1:]):
                                    msg = rule["message"].replace("{marker}", marker).replace("{word}", word)
                                    issues.append(self._make_issue(
                                        md_path, j + 1, rule.get("level", "error"),
                                        rule["id"], msg))
                    break
        return issues

    def _check_body_text_semicolon(self, rule, text, lines, md_path, md_dir):
        """Check that semicolons (;) appear only in lists, term definitions, and code blocks."""
        issues = []
        in_code_block = False
        for i, line in enumerate(lines):
            stripped = line.rstrip()
            if stripped.startswith("```"):
                in_code_block = not in_code_block
                continue
            if in_code_block:
                continue
            if not stripped.strip():
                continue
            # Skip headings, table rows, table captions, calc lines, var defs, images
            if (stripped.startswith("#") or
                (stripped.startswith("|") and stripped.endswith("|")) or
                stripped.startswith("Table:") or
                stripped.startswith("!") or
                stripped.startswith("{") or
                stripped.startswith("$$")):
                continue
            # Check if this is a list item — ; allowed
            if re.match(r"^\s*\d+[\.\)]\s", stripped):
                continue
            if stripped.startswith("- ") or stripped.startswith("* "):
                continue
            # Check if this is a term definition (термин -- ...;)
            if re.match(r"^[а-яёА-ЯЁA-Z].*--.*;$", stripped):
                continue
            # Remaining lines with ; are violations
            if ";" in stripped:
                context = stripped[:80]
                msg = rule["message"]
                issues.append(self._make_issue(
                    md_path, i + 1, rule.get("level", "error"),
                    rule["id"], msg))
        return issues

    def _check_mixed_list_types(self, rule, text, lines, md_path, md_dir):
        """Warn if both bullet (-) and numbered (1.) lists appear."""
        has_bullet = False
        has_numbered = False
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("- ") and not stripped.startswith("--"):
                has_bullet = True
            elif re.match(r"^\d+\.\s", stripped):
                has_numbered = True
        if has_bullet and has_numbered:
            issues = [self._make_issue(md_path, 1, rule.get("level", "warning"),
                                        rule["id"], rule["message"])]
            return issues
        return []

    def _check_list_item_uppercase(self, rule, text, lines, md_path, md_dir):
        """Check that list items start with lowercase letter.
        Exceptions: proper names (ГОСТ, Unity, Windows, DirectX, C#) and established abbreviations.
        Skips list items under headings matching exclude_headings patterns."""
        issues = []
        # Common proper names that stay uppercase at list start
        proper_exceptions = {
            "гост", "unity", "directx", "windows", "visual", "studio", "git",
            "steam", "intel", "pentium", "escape", "c#", "санпин",
        }

        exclude_heads = rule.get("exclude_headings", [])

        in_code_block = False
        for i, line in enumerate(lines):
            stripped = line.strip()

            # Skip code blocks
            if stripped.startswith("```"):
                in_code_block = not in_code_block
                continue
            if in_code_block:
                continue

            # Check if this line is a numbered list item
            m = re.match(r"^(\s*)(\d+\.)\s+(.*)", line)
            matched = False
            if m:
                matched = True
                rest = m.group(3).strip()
            else:
                # Check if this line is a bullet list item
                bm = re.match(r"^(\s*)([-*])\s+(.*)", line)
                if bm:
                    matched = True
                    rest = bm.group(3).strip()

            if not matched or not rest:
                continue

            # Skip headings, tables, var defs, calc lines, images
            if (stripped.startswith("#") or stripped.startswith("|") or
                stripped.startswith("Table:") or stripped.startswith("!") or
                stripped.startswith("{") or stripped.startswith("$$")):
                continue

            # Find the nearest preceding heading to check exclude_headings
            if exclude_heads:
                heading = None
                for j in range(i - 1, -1, -1):
                    if lines[j].strip().startswith("#"):
                        heading = lines[j].strip().lstrip("#").strip()
                        break
                if heading and any(re.search(pat, heading) for pat in exclude_heads):
                    continue

            first_word = rest.split()[0] if rest.split() else ""
            if first_word and first_word[0].isupper() and first_word.isalpha():
                if first_word.lower() not in proper_exceptions:
                    msg = rule["message"].replace("{text}", rest[:50])
                    issues.append(self._make_issue(
                        md_path, i + 1, rule.get("level", "error"),
                        rule["id"], msg))

        return issues

    def _check_table_ref_exists(self, rule, text, lines, md_path, md_dir):
        """Check that 'таблица N' in text has a corresponding 'Table: Таблица N.' caption."""
        # Collect all table captions
        table_captions = set()
        for line in lines:
            m = re.match(r"Table:\s*(.*)", line)
            if m:
                table_captions.add(m.group(1).strip().lower())

        issues = []
        for i, line in enumerate(lines):
            # Look for "таблица N" in text lines (not in table markup, not in heading)
            for m in re.finditer(r"(таблица\s+\d+)", line, re.IGNORECASE):
                ref = m.group(1).strip().lower()
                # Check if any caption starts with or contains this ref
                found = any(ref in cap for cap in table_captions)
                if not found:
                    issues.append(self._make_issue(md_path, i + 1,
                                                    rule.get("level", "warning"),
                                                    rule["id"],
                                                    rule["message"].replace("{ref}", m.group(1).strip())))
        return issues

    def _check_figure_ref_exists(self, rule, text, lines, md_path, md_dir):
        """Check that 'рисунок N' in text has a corresponding image."""
        issues = []
        # Find all image references in text (e.g. "рисунок 1", "рис. 2")
        image_refs_in_text = []
        for i, line in enumerate(lines):
            for m in re.finditer(r"(?:рис(?:унок)?\.?\s*|Рис(?:унок)?\.?\s*)(\d+)", line):
                image_refs_in_text.append((i + 1, int(m.group(1))))

        # Find all image markup
        img_count = 0
        for line in lines:
            for m in re.finditer(r"!\[.*?\]\(.*?\)", line):
                img_count += 1

        for line_no, ref_num in image_refs_in_text:
            if ref_num > img_count:
                issues.append(self._make_issue(md_path, line_no,
                                                rule.get("level", "warning"),
                                                rule["id"],
                                                rule["message"].replace("{ref}", f"Рисунок {ref_num}")))
        return issues

    def _check_broken_image_path(self, rule, text, lines, md_path, md_dir):
        """Check that image paths in ![alt](path) exist on disk."""
        issues = []
        for i, line in enumerate(lines):
            for m in re.finditer(r"!\[.*?\]\(([^)]+)\)", line):
                img_path = m.group(1)
                full_path = os.path.join(md_dir, img_path) if not os.path.isabs(img_path) else img_path
                if not os.path.exists(full_path):
                    issues.append(self._make_issue(md_path, i + 1,
                                                    rule.get("level", "warning"),
                                                    rule["id"],
                                                    rule["message"].replace("{path}", img_path)))
        return issues

    def _check_undefined_placeholder(self, rule, text, lines, md_path, md_dir):
        """Check that all {placeholders} in text have definitions somewhere.
        Uses generate_report config/data if available."""
        known = set()

        def _register_key(key):
            known.add(key)
            if "." in key:
                parts = key.split(".")
                known.add(parts[-1])
                if len(parts) >= 2:
                    known.add("_".join(parts[-2:]))
                if len(parts) >= 3:
                    known.add("_".join(parts[-3:]))

        def _flatten(d, prefix=""):
            for k, v in d.items():
                pk = f"{prefix}.{k}" if prefix else k
                if isinstance(v, dict):
                    _flatten(v, pk)
                else:
                    _register_key(pk)

        # Load JSON data files referenced from config, if present
        if isinstance(self.config, dict):
            data_refs = self.config.get("data", {})
            root = os.path.join(md_dir, "..")
            for key, path in data_refs.items():
                full_path = os.path.join(root, path)
                if os.path.exists(full_path):
                    try:
                        with open(full_path, "r", encoding="utf-8") as f:
                            data_obj = json.load(f)
                        _flatten({key: data_obj})
                    except Exception:
                        pass
            # Also flatten top-level config keys for generic placeholders
            _flatten({k: v for k, v in self.config.items() if k != "data"})

        # Fallback: student.json from the project structure
        student_path = os.path.join(md_dir, "..", "data", "student.json")
        if os.path.exists(student_path):
            try:
                with open(student_path, "r", encoding="utf-8") as f:
                    sd = json.load(f)
                _flatten(sd)
            except Exception:
                pass

        issues = []
        for i, line in enumerate(lines):
            for m in re.finditer(r"\{([^}=]+)\}", line):
                ph = m.group(1).strip()
                if ph not in known and not line.strip().startswith("Table:"):
                    issues.append(self._make_issue(md_path, i + 1,
                                                    rule.get("level", "error"),
                                                    rule["id"],
                                                    rule["message"].replace("{ph}", ph)))
        return issues

    # ── Sentence structure checkers ──

    def _check_sentence_length(self, rule, text, lines, md_path, md_dir):
        """Check sentences that exceed max_words."""
        issues = []
        max_words = rule.get("max_words", 20)
        level = rule.get("level", "info")
        body = _get_body_text(lines)
        for line_no, sentence in _split_sentences(body):
            words = sentence.split()
            if len(words) > max_words:
                issues.append(self._make_issue(
                    md_path, line_no, level, rule["id"],
                    rule["message"].replace("{max_words}", str(max_words))
                                    .replace("{count}", str(len(words)))))
        return issues

    def _check_clause_chain(self, rule, text, lines, md_path, md_dir):
        """Detect sentences with multiple subordinate clauses."""
        issues = []
        body = _get_body_text(lines)
        for line_no, sentence in _split_sentences(body):
            # Count subordinating conjunctions
            subs = re.findall(r'\b(?:который|которая|которое|которые|где|куда|откуда|что\b(?!\s+касается)|так\s+как|поскольку|чтобы|если|хотя|несмотря|благодаря|вследствие|при\s+помощи|при\s+этом)\s', sentence, re.IGNORECASE)
            if len(subs) >= 2:
                issues.append(self._make_issue(
                    md_path, line_no, rule.get("level", "warning"),
                    rule["id"], rule["message"]))
        return issues

    def _check_run_on(self, rule, text, lines, md_path, md_dir):
        """Detect run-on sentences with too many independent clauses."""
        issues = []
        body = _get_body_text(lines)
        for line_no, sentence in _split_sentences(body):
            # Count commas separating likely independent clauses
            clauses = [c.strip() for c in sentence.split(",") if c.strip()]
            if len(clauses) >= 4:
                issues.append(self._make_issue(
                    md_path, line_no, rule.get("level", "warning"),
                    rule["id"], rule["message"]))
        return issues

    def _check_consecutive_short(self, rule, text, lines, md_path, md_dir):
        """Detect runs of consecutive very short sentences."""
        issues = []
        max_conc = rule.get("max_consecutive", 3)
        body = _get_body_text(lines)
        sentences = list(_split_sentences(body))
        short_run = 0
        for line_no, sentence in sentences:
            words = sentence.split()
            if len(words) <= 4:
                short_run += 1
            else:
                short_run = 0
            if short_run == max_conc + 1:
                issues.append(self._make_issue(
                    md_path, line_no, rule.get("level", "info"),
                    rule["id"], rule["message"]))
                break  # one warning per block
        return issues


def _get_body_text(lines):
    """Extract only body paragraph lines for sentence checks.
    Returns continuous text with \n as sentence separators."""
    body_lines = []
    in_code = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            continue
        if not stripped:
            body_lines.append("")
            continue
        if stripped.startswith("#"):
            continue
        if stripped.startswith("- ") or stripped.startswith("* "):
            continue
        if re.match(r"^\d+\.\s", stripped):
            continue
        if stripped.startswith("|") and stripped.endswith("|"):
            continue
        if stripped.startswith(">"):
            continue
        if re.match(r"^\s*\$\$", stripped):
            continue
        if stripped.startswith("Table:"):
            continue
        body_lines.append(stripped)
    return "\n".join(body_lines)


def _split_sentences(text):
    """Split body text into (line_no, sentence) tuples.
    Uses paragraph breaks + sentence-ending punctuation."""
    sentences = []
    # First split by paragraph boundaries (blank lines)
    paragraphs = re.split(r"\n{2,}", text)
    para_line = 1
    for para in paragraphs:
        if not para.strip():
            continue
        # Within a paragraph, split by sentence-ending punctuation
        buf = para.strip()
        while buf:
            # Look for .?! followed by space+uppercase or end
            m = re.search(r"[.?!](?:\s+(?=[А-ЯA-Z\d«]|$)|$)", buf)
            if m:
                sent = buf[:m.end()].strip()
                if sent:
                    sentences.append((para_line, sent))
                buf = buf[m.end():].strip()
            else:
                # Last sentence in paragraph
                if buf.strip():
                    sentences.append((para_line, buf.strip()))
                break
        para_line += 1
    return sentences


def format_issues(issues, show_levels=None):
    """Format issues for display. show_levels: set of levels to show."""
    if show_levels is None:
        show_levels = {"error", "warning", "info"}
    if not issues:
        return ""

    lines_out = []
    # Group by file
    by_file = {}
    for iss in issues:
        by_file.setdefault(iss["file"], []).append(iss)

    total = len(issues)
    error_count = sum(1 for i in issues if i["level"] == "error")
    warning_count = sum(1 for i in issues if i["level"] == "warning")
    info_count = sum(1 for i in issues if i["level"] == "info")

    for filepath, file_issues in sorted(by_file.items()):
        filename = os.path.basename(filepath)
        lines_out.append(f"── {filename} ──")
        for iss in sorted(file_issues, key=lambda x: x.get("line", 0)):
            level = iss.get("level", "info")
            if level not in show_levels:
                continue
            line = iss.get("line", 0)
            rid = iss.get("rule", "?")
            msg = iss.get("message", "")
            prefix = {"error": "E", "warning": "W", "info": "I"}.get(level, "?")
            lines_out.append(f"  [{prefix}] L{line:>4} ({rid}) {msg}")
        lines_out.append("")

    lines_out.append(f"Summary: {total} issues ({error_count} errors, {warning_count} warnings, {info_count} info)")
    return "\n".join(lines_out)


def format_checklist(issues, show_levels=None):
    """Format issues as a markdown checklist grouped by rule.
    Useful when agent debugging is not needed — just track what to fix.

    Output:
        ## Линтер: N issues
        ### 🔴 Errors (N)
        - [ ] `rule-id` — N occurrences
        ### 🟠 Warnings (N)
        ...
        ### 🔵 Info (N)
        ...
    """
    if show_levels is None:
        show_levels = {"error", "warning", "info"}
    if not issues:
        return "_No issues found._"

    _LEVEL_EMOJI = {"error": "🔴", "warning": "🟠", "info": "🔵"}
    _LEVEL_LABEL = {"error": "Errors", "warning": "Warnings", "info": "Info"}

    total = len(issues)
    error_count = sum(1 for i in issues if i["level"] == "error")
    warning_count = sum(1 for i in issues if i["level"] == "warning")
    info_count = sum(1 for i in issues if i["level"] == "info")

    # Group by level → rule_id
    by_level: dict[str, dict[str, list[dict]]] = {}
    for iss in issues:
        lvl = iss.get("level", "info")
        if lvl not in show_levels:
            continue
        by_level.setdefault(lvl, {})
        rid = iss.get("rule", "?")
        by_level[lvl].setdefault(rid, []).append(iss)

    lines = [f"## Линтер: {total} issues"]
    lines.append("")

    for lvl in ("error", "warning", "info"):
        if lvl not in by_level:
            continue
        rules = by_level[lvl]
        count = sum(len(v) for v in rules.values())
        emoji = _LEVEL_EMOJI.get(lvl, "")
        label = _LEVEL_LABEL.get(lvl, lvl)
        lines.append(f"### {emoji} {label} ({count})")
        for rid in sorted(rules):
            occ = rules[rid]
            lines.append(f"- [ ] `{rid}` — {len(occ)} occurrence{'' if len(occ) == 1 else 's'}")
        lines.append("")

    lines.append(f"---")
    lines.append(f"Total: {total} ({error_count} 🔴, {warning_count} 🟠, {info_count} 🔵)")
    return "\n".join(lines)

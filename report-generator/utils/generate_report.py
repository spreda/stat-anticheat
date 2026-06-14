#!/usr/bin/env python3
"""
Report Generator — thin orchestrator over Pandoc + calc_filter + linter.

Pipeline:
    config.json → calc_filter (stdin/stdout .md) → pandoc (reference.docx) → .docx

Each stage is a standalone script:
    utils/calc_filter.py     — stdin→stdout, resolves {placeholders} + $$/$$$/$var
    utils/lint_filter.py     — stdin→stderr, grep-like linter (optional)
    utils/make_reference.py  — generates reference.docx with GOST styles
    pandoc                   — .md → .docx conversion

Usage:
    python utils/generate_report.py
    python utils/generate_report.py --verbose   (show linter + calc debug)
    python utils/generate_report.py --checklist  (linter as markdown checklist)
    python utils/generate_report.py --fix        (auto-fix em-dash, double-space)
"""

import argparse
import sys
import os
import json
import subprocess
import time
import hashlib
from pathlib import Path

_script_dir = Path(__file__).resolve().parent.parent

# Ensure project root on path for sibling module imports
if str(_script_dir) not in sys.path:
    sys.path.insert(0, str(_script_dir))

QUIET = True


def log(msg):
    if not QUIET:
        print(msg, file=sys.stderr)


def load_config(config_path):
    config_path = Path(config_path)
    if not config_path.exists():
        print(f"ERROR: Config not found: {config_path}", file=sys.stderr)
        sys.exit(1)
    with config_path.open(encoding="utf-8") as f:
        return json.load(f)


def load_json(path):
    candidate = Path(path)
    full_path = candidate if candidate.is_absolute() else _script_dir / path
    if not full_path.exists():
        log(f"WARNING: {full_path} not found")
        return {}
    with full_path.open(encoding="utf-8") as f:
        return json.load(f)


def auto_output_path(config):
    student = config.get("student", {})
    author = student.get("author", {})
    surname = author.get("full_name", "Unknown").split()[0]
    initials = author.get("initials", "").replace(".", "").replace(" ", "")
    label = config.get("report_type_label", "Отчёт").replace(" ", "_")
    out_dir = Path(config.get("paths", {}).get("output_dir", "output"))
    if not out_dir.is_absolute():
        out_dir = _script_dir / out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    return str(out_dir / f"{label}_{surname}_{initials}.docx")


def _check_not_locked(path):
    """Verify the output file is not locked by another process.

    Tries to open the path for writing. If it's locked (Word open, etc.),
    prints a clear error and exits."""
    p = Path(path)
    if not p.exists():
        return
    try:
        with p.open("ab") as f:
            f.truncate()  # no-op, just tests writability
    except PermissionError:
        print(f"ERROR: Output file is locked by another process:", file=sys.stderr)
        print(f"  {p.resolve()}", file=sys.stderr)
        print(f"Close the file in Word / other editor and re-run.", file=sys.stderr)
        sys.exit(1)


def _safe_prepare_output(path):
    """Remove existing output file if present, after checking it's not locked.

    Prevents silent failure when Pandoc tries to write to a .docx
    that is currently open in Word, Explorer preview pane, etc."""
    _check_not_locked(path)
    p = Path(path)
    if p.exists():
        p.unlink()
        log(f"  [clean] Removed stale output: {p.name}")


def build_flat_config(config):
    """Merge config + data files into one flat dict."""
    full = {}
    for key, path in config.get("data", {}).items():
        full[key] = load_json(path)
    full["paths"] = config.get("paths", {})
    student = full.get("student", {})
    full["project"] = student.get("project", {})
    full["gost"] = full.get("style", {})
    for key in ["report_type", "report_type_label", "template"]:
        if key in config:
            full[key] = config[key]
    return full


def run_calc_filter(source_md, expanded_md, config_path):
    """Run calc_filter.py: stdin=source .md → stdout=expanded .md."""
    calc_py = _script_dir / "utils" / "calc_filter.py"
    with source_md.open("r", encoding="utf-8") as fin, \
         expanded_md.open("w", encoding="utf-8") as fout:
        r = subprocess.run(
            [sys.executable, str(calc_py), "--config", str(config_path)],
            stdin=fin, stdout=fout, stderr=subprocess.PIPE,
            text=True, encoding="utf-8",
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
    if r.returncode != 0:
        print(f"  [calc] ERROR: {r.stderr}", file=sys.stderr)
        return False
    for line in r.stderr.splitlines():
        if line.strip():
            print(line, file=sys.stderr)
    return True


def run_linter(source_md, checklist=False, fix=False, config_path=None):
    """Run LintEngine, print to stderr. Returns issue count."""
    sys.path.insert(0, str(_script_dir))
    from lint.lint_engine import LintEngine, format_issues, format_checklist

    engine = LintEngine(config_path=config_path)
    md_path = str(source_md)

    if fix:
        fixed = engine.fix_file(md_path)
        if fixed:
            log(f"  [fix] Applied fixes to {os.path.basename(md_path)}")

    issues = engine.lint_file(md_path)
    if issues:
        if checklist:
            print(format_checklist(issues), file=sys.stderr)
        elif not QUIET:
            print(format_issues(issues), file=sys.stderr)
    return len(issues)


def _fix_output_numbering(docx_path, config):
    """Fix numbering XML in the final DOCX so list indents are correct.
    Pandoc creates its own numbering in the output, ignoring reference.docx numbering.xml."""
    try:
        from lxml import etree
        import zipfile, io

        # Read list indent + tab from config (style section with defaults)
        style = config.get("style", {})
        indent_cm = style.get("list_indent_cm", 2.00)
        hanging_cm = style.get("list_hanging_cm", 0.75)
        tab_cm = style.get("list_tab_pos_cm", indent_cm - hanging_cm)
        left_twips = int(indent_cm * 567)
        hanging_twips = int(hanging_cm * 567)
        tab_twips = int(tab_cm * 567)
        ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
        changed = False

        # Read
        with zipfile.ZipFile(docx_path, "r") as z:
            xml = z.read("word/numbering.xml")
        root = etree.fromstring(xml)

        # Fix all abstractNum levels
        for anum in root.findall(f"{{{ns}}}abstractNum"):
            for lvl in anum.findall(f"{{{ns}}}lvl"):
                ppr = lvl.find(f"{{{ns}}}pPr")
                if ppr is None:
                    continue
                ind = ppr.find(f"{{{ns}}}ind")
                if ind is None:
                    continue
                if ind.get(f"{{{ns}}}left") is None:
                    continue
                ind.set(f"{{{ns}}}left", str(left_twips))
                ind.set(f"{{{ns}}}hanging", str(hanging_twips))
                # Fix/set tab stop
                tabs = lvl.find(f"{{{ns}}}tabs")
                if tabs is None:
                    tabs = etree.SubElement(ppr, f"{{{ns}}}tabs")
                for t in list(tabs):
                    if t.get(f"{{{ns}}}val") == "num":
                        tabs.remove(t)
                tab_el = etree.SubElement(tabs, f"{{{ns}}}tab")
                tab_el.set(f"{{{ns}}}val", "num")
                tab_el.set(f"{{{ns}}}pos", str(tab_twips))
                changed = True

        if changed:
            new_xml = etree.tostring(root, xml_declaration=True,
                                     encoding="UTF-8", standalone=True)
            buf = io.BytesIO()
            with zipfile.ZipFile(docx_path, "r") as src:
                with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as out:
                    for item in src.infolist():
                        if item.filename == "word/numbering.xml":
                            out.writestr(item, new_xml)
                        else:
                            out.writestr(item, src.read(item.filename))
            with open(docx_path, "wb") as f:
                f.write(buf.getvalue())
    except Exception as e:
        log(f"  [fix] WARNING: Output numbering fix failed: {e}")


def set_style_rpr(sty, ns, sz_halfpts, line_twips, jc_val="left"):
    """Helper: set rPr + pPr (sz, rFonts=TNR, single spacing, no indent, alignment) on a style element."""
    from lxml import etree
    rPr = sty.find(f"{{{ns}}}rPr")
    if rPr is None:
        rPr = etree.SubElement(sty, f"{{{ns}}}rPr")
    # rFonts: TNR
    rFonts = rPr.find(f"{{{ns}}}rFonts")
    if rFonts is None:
        rFonts = etree.SubElement(rPr, f"{{{ns}}}rFonts")
    for attr in list(rFonts.attrib):
        del rFonts.attrib[attr]
    rFonts.set(f"{{{ns}}}ascii", "Times New Roman")
    rFonts.set(f"{{{ns}}}hAnsi", "Times New Roman")
    rFonts.set(f"{{{ns}}}cs", "Times New Roman")
    rFonts.set(f"{{{ns}}}eastAsia", "Times New Roman")
    # sz
    sz = rPr.find(f"{{{ns}}}sz")
    if sz is None:
        sz = etree.SubElement(rPr, f"{{{ns}}}sz")
    sz.set(f"{{{ns}}}val", sz_halfpts)
    szCs = rPr.find(f"{{{ns}}}szCs")
    if szCs is None:
        szCs = etree.SubElement(rPr, f"{{{ns}}}szCs")
    szCs.set(f"{{{ns}}}val", sz_halfpts)
    # pPr: single spacing, no indent, alignment
    pPr = sty.find(f"{{{ns}}}pPr")
    if pPr is None:
        pPr = etree.SubElement(sty, f"{{{ns}}}pPr")
    spacing = pPr.find(f"{{{ns}}}spacing")
    if spacing is None:
        spacing = etree.SubElement(pPr, f"{{{ns}}}spacing")
    spacing.set(f"{{{ns}}}line", line_twips)
    spacing.set(f"{{{ns}}}lineRule", "auto")
    # indent: 0
    ind = pPr.find(f"{{{ns}}}ind")
    if ind is None:
        ind = etree.SubElement(pPr, f"{{{ns}}}ind")
    ind.set(f"{{{ns}}}firstLine", "0")
    ind.set(f"{{{ns}}}left", "0")
    # alignment (jc)
    jc = pPr.find(f"{{{ns}}}jc")
    if jc is None:
        jc = etree.SubElement(pPr, f"{{{ns}}}jc")
    jc.set(f"{{{ns}}}val", jc_val)


def _fix_docx_postprocess(docx_path):
    """Post-process the DOCX after Pandoc generation.

    - Table captions: right-aligned
    - Table headers: bold + justify
    - Image paragraphs: justify, no first-line indent
    - Source Code / Verbatim Char: TNR 14pt, line_spacing=1
    """
    try:
        from lxml import etree
        import zipfile, io

        ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
        w = ns

        with zipfile.ZipFile(docx_path, "r") as z:
            doc_xml = z.read("word/document.xml")
            styles_xml = z.read("word/styles.xml")

        root = etree.fromstring(doc_xml)
        body = root.find(f"{{{ns}}}body")
        if body is None:
            return

        # ── Fix styles.xml: Source Code + Verbatim Char → TNR 14pt, single spacing ──
        styles_root = etree.fromstring(styles_xml)
        for sty in styles_root.findall(f"{{{ns}}}style"):
            sid = sty.get(f"{{{ns}}}styleId")
            if sid in ("SourceCode", "VerbatimChar"):
                new_sz = "28"  # 14pt
                set_style_rpr(sty, ns, new_sz, "240", "left")

        # ── Strip italic from all heading, caption, title, TOC styles ──
        for sty in styles_root.findall(f"{{{ns}}}style"):
            sid = sty.get(f"{{{ns}}}styleId", "")
            # Heading 1-9, Caption, Title, TOC styles — any style that shouldn't be italic
            if (sid.startswith("Heading") or sid.startswith("heading") or
                sid == "Caption" or sid == "Title" or
                sid.startswith("TOC") or sid.startswith("toc")):
                rPr = sty.find(f"{{{ns}}}rPr")
                if rPr is not None:
                    for tag in ("i", "iCs"):
                        elem = rPr.find(f"{{{ns}}}{tag}")
                        if elem is not None:
                            rPr.remove(elem)
                            log(f"  [fix] stripped <w:{tag}> from style '{sid}'")

        # ── Create Table Body (12pt, justify) and Table Header (12pt, center, bold) styles ──
        for style_id, props in {
            "Table Body": {"sz": "24", "jc": "both", "bold": False},
            "Table Header": {"sz": "24", "jc": "center", "bold": True},
        }.items():
            # Remove existing style with same id (rebuild from scratch)
            for s in list(styles_root.findall(f"{{{ns}}}style")):
                if s.get(f"{{{ns}}}styleId") == style_id:
                    styles_root.remove(s)
                    break
            sty = etree.SubElement(styles_root, f"{{{ns}}}style")
            sty.set(f"{{{ns}}}styleId", style_id)
            sty.set(f"{{{ns}}}type", "paragraph")
            rPr = etree.SubElement(sty, f"{{{ns}}}rPr")
            # Set rPr: TNR 12pt, bold for header
            rFonts = etree.SubElement(rPr, f"{{{ns}}}rFonts")
            rFonts.set(f"{{{ns}}}ascii", "Times New Roman")
            rFonts.set(f"{{{ns}}}hAnsi", "Times New Roman")
            rFonts.set(f"{{{ns}}}cs", "Times New Roman")
            rFonts.set(f"{{{ns}}}eastAsia", "Times New Roman")
            sz = etree.SubElement(rPr, f"{{{ns}}}sz")
            sz.set(f"{{{ns}}}val", props["sz"])
            szCs = etree.SubElement(rPr, f"{{{ns}}}szCs")
            szCs.set(f"{{{ns}}}val", props["sz"])
            if props["bold"]:
                b = etree.SubElement(rPr, f"{{{ns}}}b")
                b.set(f"{{{ns}}}val", "1")
                bCs = etree.SubElement(rPr, f"{{{ns}}}bCs")
                bCs.set(f"{{{ns}}}val", "1")
            # pPr: single spacing, no indent, alignment
            pPr = sty.find(f"{{{ns}}}pPr")
            if pPr is not None: sty.remove(pPr)
            pPr = etree.SubElement(sty, f"{{{ns}}}pPr")
            jc = etree.SubElement(pPr, f"{{{ns}}}jc")
            jc.set(f"{{{ns}}}val", props["jc"])
            spacing = etree.SubElement(pPr, f"{{{ns}}}spacing")
            spacing.set(f"{{{ns}}}line", "240")
            spacing.set(f"{{{ns}}}lineRule", "auto")
            ind = etree.SubElement(pPr, f"{{{ns}}}ind")
            ind.set(f"{{{ns}}}firstLine", "0")
            ind.set(f"{{{ns}}}left", "0")

        changed = False

        # ── Pass 1: add table borders, assign Table Body/Header styles, set column widths ──
        for tbl in body.findall(f"{{{ns}}}tbl"):
            tblPr = tbl.find(f"{{{ns}}}tblPr")
            if tblPr is None:
                tblPr = etree.Element(f"{{{ns}}}tblPr")
                tbl.insert(0, tblPr)

            # Add grid borders (if missing)
            tblBorders = tblPr.find(f"{{{ns}}}tblBorders")
            if tblBorders is None:
                tblBorders = etree.SubElement(tblPr, f"{{{ns}}}tblBorders")
                for edge in ('top', 'left', 'bottom', 'right', 'insideH', 'insideV'):
                    el = etree.SubElement(tblBorders, f"{{{ns}}}{edge}")
                    el.set(f"{{{ns}}}val", "single")
                    el.set(f"{{{ns}}}sz", "4")
                    el.set(f"{{{ns}}}space", "0")
                    el.set(f"{{{ns}}}color", "000000")
                changed = True

            # Set table width to 100% of page
            tblW = tblPr.find(f"{{{ns}}}tblW")
            if tblW is None:
                tblW = etree.SubElement(tblPr, f"{{{ns}}}tblW")
            tblW.set(f"{{{ns}}}w", "9072")  # ~16cm in twips (A4 minus 2.5cm margins)
            tblW.set(f"{{{ns}}}type", "dxa")

            # ── Calculate column widths: weighted combination of 3 metrics ──
            tblGrid = tbl.find(f"{{{ns}}}tblGrid")
            if tblGrid is not None:
                grid_cols = tblGrid.findall(f"{{{ns}}}gridCol")
                num_cols = len(grid_cols)
                if num_cols > 1:
                    # Collect all cell texts per column (including header row)
                    col_texts: list[list[str]] = [[] for _ in range(num_cols)]
                    for tr in tbl.findall(f"{{{ns}}}tr"):
                        for ci, tc in enumerate(tr.findall(f"{{{ns}}}tc")):
                            if ci >= num_cols:
                                break
                            texts = []
                            for t in tc.findall(f".//{{{ns}}}t"):
                                texts.append(t.text or "")
                            col_texts[ci].append("".join(texts))

                    # Metric 1: average character length per column
                    # Metric 3: maximum word length per column (longest word across all cells)
                    col_avg: list[float] = []
                    col_maxword: list[float] = []
                    for ct in col_texts:
                        if ct:
                            avg = sum(len(t) for t in ct) / len(ct)
                            maxw = 1
                            for t in ct:
                                words = t.split()
                                if words:
                                    maxw = max(maxw, max(len(w) for w in words))
                        else:
                            avg = 1
                            maxw = 1
                        col_avg.append(max(avg, 1))
                        col_maxword.append(float(max(maxw, 1)))

                    # Normalise each metric to sum = 1 across columns
                    sum_avg = sum(col_avg)
                    sum_maxword = sum(col_maxword)
                    norm_avg   = [a / sum_avg for a in col_avg]
                    norm_equal = [1.0 / num_cols] * num_cols  # Metric 2: equilibrium
                    norm_maxword = [m / sum_maxword for m in col_maxword]

                    # Weighted combination (default equal weights ⅓ each)
                    w_avg, w_equal, w_maxword = 1/3, 1/3, 1/3
                    scores = [
                        w_avg * na + w_equal * ne + w_maxword * nm
                        for na, ne, nm in zip(norm_avg, norm_equal, norm_maxword)
                    ]

                    # Distribute total width proportionally to scores, minimum 400 twips
                    total_width = 9072
                    min_width = 400
                    col_widths: list[int] = []
                    remaining = total_width
                    for i in range(num_cols):
                        if i == num_cols - 1:
                            w = remaining  # last column gets remainder
                        else:
                            w = max(min_width, int(total_width * scores[i]))
                            max_take = remaining - min_width * (num_cols - i - 1)
                            w = min(w, max_take)
                        w = max(min_width, min(w, remaining))
                        col_widths.append(w)
                        remaining -= w

                    # Update gridCol widths
                    for ci, gc in enumerate(grid_cols):
                        gc.set(f"{{{ns}}}w", str(col_widths[ci]))
                    changed = True

            # Assign Table Body / Table Header pStyle + fallback formatting
            for tr in tbl.findall(f"{{{ns}}}tr"):
                trPr = tr.find(f"{{{ns}}}trPr")
                is_header = trPr is not None and trPr.find(f"{{{ns}}}tblHeader") is not None
                for tc in tr.findall(f"{{{ns}}}tc"):
                    for tc_p in tc.findall(f"{{{ns}}}p"):
                        tc_pPr = tc_p.find(f"{{{ns}}}pPr")
                        if tc_pPr is None:
                            tc_pPr = etree.SubElement(tc_p, f"{{{ns}}}pPr")
                        # Set pStyle to Table Body or Table Header
                        for old_ps in tc_pPr.findall(f"{{{ns}}}pStyle"):
                            tc_pPr.remove(old_ps)
                        ps = etree.SubElement(tc_pPr, f"{{{ns}}}pStyle")
                        ps.set(f"{{{ns}}}val", "Table Header" if is_header else "Table Body")
                        # Remove explicit jc (style handles it)
                        for old_jc in tc_pPr.findall(f"{{{ns}}}jc"):
                            tc_pPr.remove(old_jc)
                        # Keep spacing and indent as fallback
                        spacing = tc_pPr.find(f"{{{ns}}}spacing")
                        if spacing is None:
                            spacing = etree.SubElement(tc_pPr, f"{{{ns}}}spacing")
                        spacing.set(f"{{{ns}}}line", "240")
                        spacing.set(f"{{{ns}}}lineRule", "auto")
                        ind = tc_pPr.find(f"{{{ns}}}ind")
                        if ind is None:
                            ind = etree.SubElement(tc_pPr, f"{{{ns}}}ind")
                        ind.set(f"{{{ns}}}firstLine", "0")
                        ind.set(f"{{{ns}}}left", "0")
                        # Keep run-level font properties as fallback
                        for r in tc_p.findall(f"{{{ns}}}r"):
                            rPr = r.find(f"{{{ns}}}rPr")
                            if rPr is None:
                                rPr = etree.SubElement(r, f"{{{ns}}}rPr")
                            rFonts = rPr.find(f"{{{ns}}}rFonts")
                            if rFonts is None:
                                rFonts = etree.SubElement(rPr, f"{{{ns}}}rFonts")
                            rFonts.set(f"{{{ns}}}ascii", "Times New Roman")
                            rFonts.set(f"{{{ns}}}hAnsi", "Times New Roman")
                            rFonts.set(f"{{{ns}}}cs", "Times New Roman")
                            rFonts.set(f"{{{ns}}}eastAsia", "Times New Roman")
                            sz = rPr.find(f"{{{ns}}}sz")
                            if sz is None:
                                sz = etree.SubElement(rPr, f"{{{ns}}}sz")
                            sz.set(f"{{{ns}}}val", "24")
                            szCs = rPr.find(f"{{{ns}}}szCs")
                            if szCs is None:
                                szCs = etree.SubElement(rPr, f"{{{ns}}}szCs")
                            szCs.set(f"{{{ns}}}val", "24")
                            if is_header:
                                b = rPr.find(f"{{{ns}}}b")
                                if b is None:
                                    b = etree.SubElement(rPr, f"{{{ns}}}b")
                                b.set(f"{{{ns}}}val", "1")
                                bCs = rPr.find(f"{{{ns}}}bCs")
                                if bCs is None:
                                    bCs = etree.SubElement(rPr, f"{{{ns}}}bCs")
                                bCs.set(f"{{{ns}}}val", "1")
                changed = True

        # ── Pass 3: process paragraphs (caption alignment, images, code) ──
        for para in body.findall(f"{{{ns}}}p"):
            pPr = para.find(f"{{{ns}}}pPr")
            if pPr is None:
                pPr = etree.SubElement(para, f"{{{ns}}}pPr")

            pStyle = pPr.find(f"{{{ns}}}pStyle")
            runs = para.findall(f"{{{ns}}}r")

            # ── SourceCode paragraphs: left-aligned, remove explicit jc ──
            if pStyle is not None and pStyle.get(f"{{{ns}}}val") in ("SourceCode", "VerbatimChar"):
                for old_jc in pPr.findall(f"{{{ns}}}jc"):
                    pPr.remove(old_jc)
                changed = True
                continue

            # ── Table captions: any paragraph containing "Таблица" → right-aligned ──
            texts = []
            for r in runs:
                for t in r.findall(f".//{{{ns}}}t"):
                    texts.append(t.text or "")
            full_text = "".join(texts)
            if "Таблица" in full_text:
                for old_jc in pPr.findall(f"{{{ns}}}jc"):
                    pPr.remove(old_jc)
                jc = etree.SubElement(pPr, f"{{{ns}}}jc")
                jc.set(f"{{{ns}}}val", "right")
                changed = True
                continue  # skip image check for caption lines

            # ── Image paragraphs: contain drawing → justify, no indent ──
            has_drawing = para.find(f".//{{{ns}}}drawing") is not None
            if has_drawing:
                for old_jc in pPr.findall(f"{{{ns}}}jc"):
                    pPr.remove(old_jc)
                jc = etree.SubElement(pPr, f"{{{ns}}}jc")
                jc.set(f"{{{ns}}}val", "both")
                ind = pPr.find(f"{{{ns}}}ind")
                if ind is None:
                    ind = etree.SubElement(pPr, f"{{{ns}}}ind")
                ind.set(f"{{{ns}}}firstLine", "0")
                ind.set(f"{{{ns}}}left", "0")
                changed = True

        if changed:
            new_xml = etree.tostring(root, xml_declaration=True,
                                     encoding="UTF-8", standalone=True)
        new_styles_xml = etree.tostring(styles_root, xml_declaration=True,
                                         encoding="UTF-8", standalone=True)
        # Debug: verify new styles exist
        debug_root = etree.fromstring(new_styles_xml)
        debug_ids = {s.get(f"{{{ns}}}styleId") for s in debug_root.findall(f"{{{ns}}}style")}
        has_tb = "Table Body" in debug_ids
        has_th = "Table Header" in debug_ids
        if not has_tb or not has_th:
            log(f"  [fix] WARNING: Table styles missing! TB={has_tb} TH={has_th}")
        else:
            log(f"  [fix] Table styles created: TB={has_tb} TH={has_th}")

        if changed or True:  # always write both (styles.xml always modified)
            buf = io.BytesIO()
            with zipfile.ZipFile(docx_path, "r") as src:
                with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as out:
                    for item in src.infolist():
                        if item.filename == "word/document.xml" and changed:
                            out.writestr(item, new_xml)
                        elif item.filename == "word/styles.xml":
                            out.writestr(item, new_styles_xml)
                        else:
                            out.writestr(item, src.read(item.filename))
            with open(docx_path, "wb") as f:
                f.write(buf.getvalue())
    except Exception as e:
        log(f"  [fix] WARNING: DOCX postprocessing failed: {e}")


def generate_report(config_path="config_practice.json", verbose=False, checklist=False, fix=False):
    """Main orchestrator — quiet by default, --verbose for details."""
    global QUIET
    QUIET = not verbose

    config_path = Path(config_path)
    config = load_config(str(config_path))
    flat = build_flat_config(config)
    template = load_json(f"templates/{flat.get('template', 'practice_report')}.json")

    source_file = template.get("source", "report.md")
    source_md = _script_dir / "content-md" / source_file
    expanded_md = _script_dir / "output" / "expanded.md"
    output_path = auto_output_path(flat)
    ref_docx = _script_dir / "data" / "reference.docx"

    (_script_dir / "output").mkdir(parents=True, exist_ok=True)
    _times = {}

    def _t(label):
        _times[label] = time.perf_counter()
        if verbose:
            print(f"  [{label}] start", file=sys.stderr)

    def _pt(label):
        if not verbose:
            return
        elapsed = time.perf_counter() - _times.get(label, 0)
        print(f"  [{label}] {elapsed:.2f}s", file=sys.stderr)

    _t("total")
    # ── Step 0: Rebuild reference.docx from style config ──
    _t("ref")
    make_ref_py = _script_dir / "utils" / "make_reference.py"
    if ref_docx.exists():
        # Compute hash of all inputs that affect reference.docx output
        hash_inputs = []
        # (a) the config file itself
        hash_inputs.append(config_path.read_bytes())
        # (b) style data file(s) referenced in config
        for key, rel_path in config.get("data", {}).items():
            data_file = _script_dir / rel_path
            if data_file.exists():
                hash_inputs.append(data_file.read_bytes())
        # (c) make_reference.py itself
        if make_ref_py.exists():
            hash_inputs.append(make_ref_py.read_bytes())
        current_hash = hashlib.sha256(b"".join(hash_inputs)).hexdigest()

        # Sidecar: data/reference.docx.sha256
        hash_file = ref_docx.with_suffix(ref_docx.suffix + ".sha256")
        cached_hash = hash_file.read_text(encoding="utf-8").strip() if hash_file.exists() else ""

        if current_hash == cached_hash:
            log(f"  [ref] Cache HIT — reference.docx unchanged, skipping")
        else:
            r0 = subprocess.run(
                [sys.executable, str(make_ref_py), str(ref_docx), "--config", str(config_path)],
                capture_output=True, text=False,
            )
            if r0.returncode != 0:
                err0 = r0.stderr.decode("utf-8", errors="replace").strip() if r0.stderr else ""
                print(f"  [ref] WARNING: make_reference failed: {err0}", file=sys.stderr)
            elif not QUIET:
                out0 = r0.stdout.decode("utf-8", errors="replace").strip() if r0.stdout else ""
                print(out0, file=sys.stderr)
            # Write hash sidecar on success
            hash_file.write_text(current_hash, encoding="utf-8")
            log(f"  [ref] Cache MISS — rebuilt reference.docx")
    _pt("ref")

    # ── Step 1: Run linter (always, errors shown in summary) ──
    _t("linter")
    issue_count = 0
    error_count = 0
    show_linter = checklist or fix or not QUIET
    issue_count = run_linter(
        source_md,
        checklist=checklist,
        fix=fix,
        config_path=str(config_path),
    )
    if issue_count > 0:
        # Re-run silently to count ERROR-level issues for exit code
        from lint.lint_engine import LintEngine
        _engine = LintEngine(config_path=str(config_path))
        _all_issues = _engine.lint_file(str(source_md))
        error_count = sum(1 for i in _all_issues if i.get("level") == "error")
    _pt("linter")

    # ── Step 2: Run calc_filter — expand .md ──
    _t("calc_filter")
    ok = run_calc_filter(source_md, expanded_md, config_path)
    if not ok:
        print("ERROR: calc_filter failed", file=sys.stderr)
        sys.exit(1)
    _pt("calc_filter")

    # ── Step 2.5: Run dash_filter — normalize dashes (—/– → --) ──
    _t("dash_filter")
    dash_py = _script_dir / "utils" / "dash_filter.py"
    with expanded_md.open("rb") as fin:
        data = fin.read()
    r = subprocess.run(
        [sys.executable, str(dash_py)],
        input=data, capture_output=True,
    )
    if r.returncode == 0 and r.stdout:
        expanded_md.write_bytes(r.stdout)
        log(f"  [dash] dashes normalized")
    _pt("dash_filter")

    # ── Step 2.75: Remove existing output file (prevent locked-file errors) ──
    _t("clean_output")
    _safe_prepare_output(output_path)
    _pt("clean_output")

    # ── Step 3: Run pandoc — .md → .docx (with Lua filter for cover + figures) ──
    _t("pandoc")
    lua_filter = _script_dir / "utils" / "gost_filter.lua"
    cmd = ["pandoc", str(expanded_md), "--lua-filter", str(lua_filter),
           "-f", "markdown", "-t", "docx", "-o", output_path]
    if ref_docx.exists():
        cmd.extend(["--reference-doc", str(ref_docx)])

    r = subprocess.run(cmd, capture_output=True, text=False)
    if r.returncode != 0:
        try:
            err = r.stderr.decode("utf-8", errors="replace")
        except Exception:
            err = str(r.stderr)
        print(f"ERROR: Pandoc failed: {err}", file=sys.stderr)
        sys.exit(1)
    _pt("pandoc")

    # Check output is still writable (pandoc may have created it)
    _check_not_locked(output_path)

    # ── Step 4: Fix numbering in output DOCX (Pandoc creates its own numbering) ──
    _t("fix_numbering")
    _fix_output_numbering(output_path, config)
    _pt("fix_numbering")

    # ── Step 5: Post-process DOCX (table captions, headers, images) ──
    _t("postprocess")
    _check_not_locked(output_path)
    _fix_docx_postprocess(output_path)
    _pt("postprocess")

    # ── Step 6: Lint generated DOCX ──
    _t("lint_docx")
    docx_issue_count = 0
    if show_linter:
        from lint.lint_engine import LintEngine, format_issues
        engine = LintEngine(config_path=str(config_path))
        docx_issues = engine.lint_docx(output_path)
        if docx_issues:
            docx_issue_count = len(docx_issues)
            if not QUIET:
                print(file=sys.stderr)
                print("── DOCX validation ──", file=sys.stderr)
                print(format_issues(docx_issues, set()), file=sys.stderr)
    _pt("lint_docx")

    # ── Summary ──
    if not QUIET:
        print(file=sys.stderr)
        print(f"=== Report Generation Complete ===", file=sys.stderr)
        print(f"Output: {output_path}", file=sys.stderr)
        if issue_count > 0:
            print(f"Linter (MD): {issue_count} issues ({error_count} errors)", file=sys.stderr)
        if docx_issue_count > 0:
            print(f"Linter (DOCX): {docx_issue_count} issues", file=sys.stderr)
        _pt("total")
    else:
        print(output_path)

    # Exit with error if linter found ERROR-level issues
    if error_count > 0:
        print(f"ERROR: {error_count} linter error(s) — fix before commit", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate a DOCX report from markdown templates.")
    parser.add_argument("--config", default="config_practice.json", help="Path to the report config JSON.")
    parser.add_argument("--verbose", action="store_true", help="Show linter and calc_filter details on stderr.")
    parser.add_argument("--quiet", action="store_true", help="Suppress progress output; prints only the output path.")
    parser.add_argument("--checklist", action="store_true", help="Show linter output as a markdown checklist.")
    parser.add_argument("--fix", action="store_true", help="Auto-fix mechanical linter issues in place.")
    parser.add_argument("--strict", action="store_true", help="Fail on any linter issue (warning or error).")
    args = parser.parse_args()

    if args.quiet and args.verbose:
        parser.error("--quiet and --verbose cannot be used together")

    generate_report(
        config_path=args.config,
        verbose=args.verbose,
        checklist=args.checklist,
        fix=args.fix,
    )
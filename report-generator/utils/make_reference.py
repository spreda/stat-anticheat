#!/usr/bin/env python3
"""
Generate a Pandoc reference.docx with GOST-compatible styles.

Usage:
    python utils/make_reference.py data/reference.docx --config config_practice.json

Opens existing reference.docx (from pandoc --print-default-data-file), tweaks styles.
If run without --config, applies sensible defaults.
"""

import sys, os, json
from pathlib import Path
from docx import Document
from docx.shared import Pt, Cm, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH

_script_dir = Path(__file__).resolve().parent.parent


def load_style_config(config_path=None):
    """Load style settings from config or return defaults."""
    defaults = {
        "font_name": "Times New Roman",
        "font_size": 14,
        "line_spacing": 1.5,
        "first_indent_cm": 1.25,
        "list_indent_cm": 1.25,
        "list_hanging_cm": 0.75,
        # list_tab_pos_cm is computed: indent - hanging
        "top_margin_cm": 2,
        "bottom_margin_cm": 2,
        "left_margin_cm": 3,
        "right_margin_cm": 1.5,
        "heading_levels": {
            "1": {"size": 14, "page_break": True},
            "2": {"size": 14, "page_break": False},
            "3": {"size": 14, "page_break": False},
            "4": {"size": 14, "page_break": False},
        },
    }
    if config_path:
        cfg_path = Path(config_path)
        if not cfg_path.is_absolute():
            cfg_path = _script_dir / config_path
        if cfg_path.exists():
            with open(cfg_path, encoding="utf-8") as f:
                cfg = json.load(f)
            style = cfg.get("style", {})
            for k, v in style.items():
                defaults[k] = v
    return defaults


def set_style(style, cfg, size_pt=None, bold=None, italic=None, font_name=None,
              alignment=None, first_indent=None, space_before=None, space_after=None,
              line_spacing=None, color=None, keep_with_next=False):
    """Helper to set paragraph + font properties on a style."""
    font = style.font
    if font_name:
        font.name = font_name
    if size_pt:
        font.size = Pt(size_pt)
    if bold is not None:
        font.bold = bold
    if italic is not None:
        font.italic = italic
    if color:
        font.color.rgb = color

    pf = style.paragraph_format
    if alignment:
        pf.alignment = alignment
    if first_indent is not None:
        pf.first_line_indent = Cm(first_indent) if first_indent else Cm(0)
    if space_before is not None:
        pf.space_before = Pt(space_before)
    if space_after is not None:
        pf.space_after = Pt(space_after)
    if line_spacing:
        pf.line_spacing = line_spacing
    if keep_with_next:
        pf.keep_with_next = True


# ── XML helpers for Cyrillic font support ──
_W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _set_cs_font(style_or_run, font_name, size_halfpt):
    """Set Complex Script (Cyrillic) font name + size at XML level.
    Also strips *Theme attributes from rFonts — they override explicit font in Word."""
    rPr = style_or_run.element.find(f"{{{_W_NS}}}rPr")
    if rPr is None:
        rPr = _make_child(style_or_run.element, _W_NS, "rPr")
    rFonts = rPr.find(f"{{{_W_NS}}}rFonts")
    if rFonts is None:
        rFonts = _make_child(rPr, _W_NS, "rFonts")
    # Strip *Theme attributes — they override explicit font in Word
    to_drop = [a for a in rFonts.attrib if "Theme" in a]
    for a in to_drop:
        del rFonts.attrib[a]
    rFonts.set(f"{{{_W_NS}}}cs", font_name)
    rFonts.set(f"{{{_W_NS}}}ascii", font_name)
    rFonts.set(f"{{{_W_NS}}}hAnsi", font_name)
    rFonts.set(f"{{{_W_NS}}}eastAsia", font_name)
    szCs = rPr.find(f"{{{_W_NS}}}szCs")
    if szCs is None:
        szCs = _make_child(rPr, _W_NS, "szCs")
    szCs.set(f"{{{_W_NS}}}val", str(size_halfpt))


def _make_child(parent, ns, tag):
    """Create a child element, insert in canonical order."""
    from lxml import etree
    child = etree.SubElement(parent, f"{{{ns}}}{tag}")
    return child


def _fix_numbering_indent(docx_path, cfg):
    """Fix list numbering XML: text at list_indent, number at list_tab_pos,
    first line pulled left by list_hanging_cm so number sticks out.

    Pandoc default: left=480 (0.85cm), hanging=480 (0.85cm).
    GOST: left=list_indent_cm*567, hanging=list_hanging_cm*567,
          tab = (list_indent_cm - list_hanging_cm) * 567.
    """
    from lxml import etree
    import zipfile
    import os

    indent_cm = cfg.get("list_indent_cm", 2.00)
    hanging_cm = cfg.get("list_hanging_cm", 0.75)
    tab_cm = cfg.get("list_tab_pos_cm", indent_cm - hanging_cm)
    left_twips = int(indent_cm * 567)  # 1cm = 567 twips
    hanging_twips = int(hanging_cm * 567)
    tab_twips = int(tab_cm * 567)

    ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"

    # Read numbering.xml
    z = zipfile.ZipFile(docx_path, "r")
    xml = z.read("word/numbering.xml")
    z.close()

    root = etree.fromstring(xml)
    changed = False

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
            # Fix indent: left=list_indent, hanging=0.75cm, tab=left-hanging
            ind.set(f"{{{ns}}}left", str(left_twips))
            ind.set(f"{{{ns}}}hanging", str(hanging_twips))
            # Fix/set tab stop for number
            tabs = lvl.find(f"{{{ns}}}tabs")
            if tabs is None:
                tabs = etree.SubElement(ppr, f"{{{ns}}}tabs")
            # Remove existing num tabs
            for t in list(tabs):
                if t.get(f"{{{ns}}}val") == "num":
                    tabs.remove(t)
            # Add new num tab at list_tab_pos_cm
            tab_el = etree.SubElement(tabs, f"{{{ns}}}tab")
            tab_el.set(f"{{{ns}}}val", "num")
            tab_el.set(f"{{{ns}}}pos", str(tab_twips))
            changed = True
        # Write back
        new_xml = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)
        import io, zipfile as zfmod
        buf = io.BytesIO()
        with open(docx_path, "rb") as f:
            src = zfmod.ZipFile(io.BytesIO(f.read()), "r")
        with zfmod.ZipFile(buf, "w", zfmod.ZIP_DEFLATED) as out:
            for item in src.infolist():
                if item.filename == "word/numbering.xml":
                    out.writestr(item, new_xml)
                else:
                    out.writestr(item, src.read(item.filename))
        src.close()
        with open(docx_path, "wb") as f:
            f.write(buf.getvalue())


def customize_reference(docx_path, config_path=None):
    """Modify pandoc reference.docx in-place with GOST-compatible styles."""
    cfg = load_style_config(config_path)
    fn = cfg["font_name"]
    fs = cfg["font_size"]
    ls = cfg["line_spacing"]
    indent = cfg["first_indent_cm"]
    hl = cfg["heading_levels"]

    doc = Document(docx_path)

    # ── Section — A4 + GOST margins ──
    for sec in doc.sections:
        sec.page_width = Cm(21.0)
        sec.page_height = Cm(29.7)
        sec.top_margin = Cm(cfg["top_margin_cm"])
        sec.bottom_margin = Cm(cfg["bottom_margin_cm"])
        sec.left_margin = Cm(cfg["left_margin_cm"])
        sec.right_margin = Cm(cfg["right_margin_cm"])

    def _fix_style(sn, size_pt, szCs_pt=None):
        """Apply font+spacing to a style, including Cyrillic CS fix."""
        sty = doc.styles[sn]
        sty.font.name = fn
        sty.font.size = Pt(size_pt)
        _set_cs_font(sty, fn, int(size_pt * 2))  # half-points
        return sty

    # ── Normal ──
    _fix_style("Normal", fs)
    normal = doc.styles["Normal"]
    normal.paragraph_format.line_spacing = ls
    normal.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    normal.paragraph_format.first_line_indent = Cm(indent)
    normal.paragraph_format.space_before = Pt(0)
    normal.paragraph_format.space_after = Pt(0)

    # ── Body Text chain (Body Text → First Paragraph, Compact) ──
    # GOST: no spacing between paragraphs (before=0, after=0).
    # FIRST-LINE INDENT: inherit from Normal (1.25 cm) — remove explicit indent XML.
    for sn in ["Body Text", "First Paragraph", "Compact"]:
        if sn in [s.name for s in doc.styles]:
            sty = _fix_style(sn, fs)
            sty.paragraph_format.line_spacing = ls
            sty.paragraph_format.space_before = Pt(0)
            sty.paragraph_format.space_after = Pt(0)
            # Remove explicit first_line_indent XML so it inherits from Normal
            pPr = sty.element.find(f"{{{_W_NS}}}pPr")
            if pPr is not None:
                ind = pPr.find(f"{{{_W_NS}}}ind")
                if ind is not None:
                    pPr.remove(ind)

    # ── Source Code ──
    if "Source Code" in [s.name for s in doc.styles]:
        sty = _fix_style("Source Code", 14)
        sty.paragraph_format.space_before = Pt(0)
        sty.paragraph_format.space_after = Pt(0)
        sty.paragraph_format.first_line_indent = Cm(0)
        sty.paragraph_format.line_spacing = 1.0

    # ── Title / Author / Date (cover page) ──
    if "Title" in [s.name for s in doc.styles]:
        _fix_style("Title", 28)
        doc.styles["Title"].paragraph_format.line_spacing = 1.0
        doc.styles["Title"].paragraph_format.alignment = WD_ALIGN_PARAGRAPH.CENTER
    if "Author" in [s.name for s in doc.styles]:
        _fix_style("Author", 12)
        doc.styles["Author"].paragraph_format.line_spacing = 1.0
    if "Date" in [s.name for s in doc.styles]:
        _fix_style("Date", 12)
        doc.styles["Date"].paragraph_format.line_spacing = 1.0

    # ── Headings 1–4 ──
    for level in [1, 2, 3, 4]:
        sn = f"Heading {level}"
        if sn not in [s.name for s in doc.styles]:
            continue
        lc = hl.get(str(level), {})
        sz = lc.get("size", fs)
        sty = _fix_style(sn, sz)
        sty.font.bold = True
        sty.font.italic = False  # clear Pandoc default italic from Heading 4/6/8
        sty.font.color.rgb = RGBColor(0, 0, 0)
        sty.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.LEFT
        sty.paragraph_format.first_line_indent = Cm(indent)
        sty.paragraph_format.line_spacing = ls
        sty.paragraph_format.space_before = Pt(0)
        sty.paragraph_format.space_after = Pt(0)
        sty.paragraph_format.keep_with_next = True
        if lc.get("page_break", level == 1):
            sty.paragraph_format.page_break_before = True
        # Zap leftover Pandoc CS size (w:szCs=40 → 20pt Cyrillic bug)
        _set_cs_font(sty, fn, int(sz * 2))

    # ── Caption (figures: justify; table captions fixed in post-processing) ──
    if "Caption" in [s.name for s in doc.styles]:
        sty = doc.styles["Caption"]
        sty.font.name = fn
        sty.font.size = Pt(fs)
        sty.font.italic = False  # clear Pandoc default italic
        _set_cs_font(sty, fn, int(fs * 2))
        sty.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        sty.paragraph_format.first_line_indent = Cm(0)
        sty.paragraph_format.line_spacing = 1.0

    # ── Table ──
    # Pandoc default has only "Table" style (not "Table Grid" or "Table Normal").
    # Add borders (grid) so tables have visible lines like the old system.
    # GOST: font 12pt, line_spacing=1, indent=0, justify.
    tn = "Table"
    if tn in [s.name for s in doc.styles]:
        tbl = doc.styles[tn]
        tbl.font.name = fn
        tbl.font.size = Pt(12)
        _set_cs_font(tbl, fn, 24)
        tbl.paragraph_format.line_spacing = 1.0
        tbl.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        tbl.paragraph_format.first_line_indent = Cm(0)
        # Add table-level borders (grid) via XML
        tbl_pr = tbl.element.find(f'{{{_W_NS}}}tblPr')
        if tbl_pr is None:
            tbl_pr = _make_child(tbl.element, _W_NS, 'tblPr')
        # Remove existing borders if any
        for old in tbl_pr.findall(f'{{{_W_NS}}}tblBorders'):
            tbl_pr.remove(old)
        borders = _make_child(tbl_pr, _W_NS, 'tblBorders')
        for edge in ('top', 'left', 'bottom', 'right', 'insideH', 'insideV'):
            el = _make_child(borders, _W_NS, edge)
            el.set(f'{{{_W_NS}}}val', 'single')
            el.set(f'{{{_W_NS}}}sz', '4')
            el.set(f'{{{_W_NS}}}space', '0')
            el.set(f'{{{_W_NS}}}color', '000000')

    # ── List bullet ──
    if "List Bullet" in [s.name for s in doc.styles]:
        sty = doc.styles["List Bullet"]
        sty.font.name = fn
        sty.font.size = Pt(fs)
        _set_cs_font(sty, fn, int(fs * 2))
        sty.paragraph_format.line_spacing = ls
        sty.paragraph_format.left_indent = Cm(0)
        sty.paragraph_format.first_line_indent = Cm(0)
        # Remove any explicit indent XML so numbering XML controls everything
        pPr = sty.element.find(f"{{{_W_NS}}}pPr")
        if pPr is not None:
            ind = pPr.find(f"{{{_W_NS}}}ind")
            if ind is not None:
                pPr.remove(ind)

    # ── List Number ──
    if "List Number" in [s.name for s in doc.styles]:
        sty = doc.styles["List Number"]
        sty.font.name = fn
        sty.font.size = Pt(fs)
        _set_cs_font(sty, fn, int(fs * 2))
        sty.paragraph_format.line_spacing = ls
        sty.paragraph_format.left_indent = Cm(0)
        sty.paragraph_format.first_line_indent = Cm(0)
        # Remove any explicit indent XML so numbering XML controls everything
        pPr = sty.element.find(f"{{{_W_NS}}}pPr")
        if pPr is not None:
            ind = pPr.find(f"{{{_W_NS}}}ind")
            if ind is not None:
                pPr.remove(ind)

    doc.save(docx_path)
    # ── List numbering: fix indent so number is at margin, text at 1.25cm ──
    _fix_numbering_indent(docx_path, cfg)
    # ── XML-level cleanup: strip italic from heading/caption/title styles ──
    # python-docx italic=False doesn't always remove existing <w:i> XML
    from lxml import etree
    for sty in doc.styles:
        sid = sty.style_id if hasattr(sty, 'style_id') else sty.name
        if (sid.startswith("Heading") or sid.startswith("heading") or
            sid in ("Caption", "Title", "Subtitle", "Author", "Date")):
            rPr = sty.element.find(f"{{{_W_NS}}}rPr")
            if rPr is not None:
                for tag in ("i", "iCs"):
                    elem = rPr.find(f"{{{_W_NS}}}{tag}")
                    if elem is not None:
                        rPr.remove(elem)
    doc.save(docx_path)
    print(f"  [ref] Customized: {docx_path}")


def main():
    args = sys.argv[1:]
    docx_path = None
    config_path = None
    i = 0
    while i < len(args):
        if args[i] == "--config" and i + 1 < len(args):
            config_path = args[i + 1]
            i += 2
        elif not args[i].startswith("--"):
            docx_path = args[i]
            i += 1
        else:
            i += 1

    if not docx_path:
        print("Usage: python utils/make_reference.py <reference.docx> [--config config.json]")
        sys.exit(1)

    customize_reference(docx_path, config_path)


if __name__ == "__main__":
    main()
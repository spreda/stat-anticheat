"""Inspect current style assignments in the latest DOCX."""
import zipfile, os, glob
from lxml import etree

out_dir = 'output'
files = sorted([f for f in glob.glob(os.path.join(out_dir, '*.docx')) if not os.path.basename(f).startswith('~$')], key=os.path.getmtime)
if not files:
    print('No DOCX files')
    exit()
f = files[-1]
print('File:', os.path.basename(f))

ns = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
z = zipfile.ZipFile(f)
doc = etree.fromstring(z.read('word/document.xml'))
styles = etree.fromstring(z.read('word/styles.xml'))
body = doc.find(f'{{{ns}}}body')

# List ALL style IDs in styles.xml
style_ids = []
for sty in styles.findall(f'{{{ns}}}style'):
    style_ids.append(sty.get(f'{{{ns}}}styleId'))
print('Styles in styles.xml:', style_ids)

# Table cell pStyle
tbl = body.find(f'{{{ns}}}tbl')
if tbl is not None:
    tc = tbl.find(f'.//{{{ns}}}tc')
    p = tc.find(f'{{{ns}}}p')
    pPr = p.find(f'{{{ns}}}pPr')
    pStyle = pPr.find(f'{{{ns}}}pStyle') if pPr is not None else None
    print(f'Table cell pStyle: {pStyle.get(f"{{{ns}}}val") if pStyle is not None else "NONE"}')

# List pStyle
for el in body:
    tag = el.tag.split('}')[1] if '}' in el.tag else el.tag
    if tag != 'p': continue
    pPr = el.find(f'{{{ns}}}pPr')
    if pPr is None: continue
    numPr = pPr.find(f'{{{ns}}}numPr')
    if numPr is None: continue
    pStyle = pPr.find(f'{{{ns}}}pStyle')
    print(f'List pStyle: {pStyle.get(f"{{{ns}}}val") if pStyle is not None else "NONE"}')
    break

# Table style
for sty in styles.findall(f'{{{ns}}}style'):
    sid = sty.get(f'{{{ns}}}styleId')
    if sid == 'Table':
        rPr = sty.find(f'{{{ns}}}rPr')
        if rPr is not None:
            sz = rPr.find(f'{{{ns}}}sz')
            szCs = rPr.find(f'{{{ns}}}szCs')
            print(f'Table style: sz={sz.get(f"{{{ns}}}val") if sz is not None else "NONE"}')
        break

# List all styles with their sz
print('\nAll styles with sz:')
for sty in styles.findall(f'{{{ns}}}style'):
    sid = sty.get(f'{{{ns}}}styleId')
    rPr = sty.find(f'{{{ns}}}rPr')
    if rPr is not None:
        sz = rPr.find(f'{{{ns}}}sz')
        sz_val = sz.get(f'{{{ns}}}val') if sz is not None else '-'
        if sz_val != '-':
            print(f'  {sid}: sz={sz_val}')

z.close()
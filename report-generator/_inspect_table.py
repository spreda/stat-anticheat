"""Inspect table cell styles in latest DOCX."""
import zipfile, os, glob
from lxml import etree

out_dir = 'output'
files = sorted([f for f in glob.glob(os.path.join(out_dir, '*.docx')) if not os.path.basename(f).startswith('~$')], key=os.path.getmtime)
f = files[-1]
print('File:', os.path.basename(f))

ns = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
z = zipfile.ZipFile(f)
doc = etree.fromstring(z.read('word/document.xml'))
body = doc.find(f'{{{ns}}}body')

tbl = body.find(f'{{{ns}}}tbl')
if tbl is None:
    print('No tables')
    z.close()
    exit()

for tr in tbl.findall(f'{{{ns}}}tr'):
    trPr = tr.find(f'{{{ns}}}trPr')
    is_hdr = trPr is not None and trPr.find(f'{{{ns}}}tblHeader') is not None
    label = 'HDR' if is_hdr else 'BDY'
    for tc in tr.findall(f'{{{ns}}}tc'):
        for p in tc.findall(f'{{{ns}}}p'):
            pPr = p.find(f'{{{ns}}}pPr')
            pStyle = pPr.find(f'{{{ns}}}pStyle')
            pStyle_val = pStyle.get(f'{{{ns}}}val') if pStyle is not None else 'NONE'
            text = ''.join(t.text or '' for t in p.findall('.//{{{ns}}t'))
            # check run
            r = p.find(f'{{{ns}}}r')
            rPr = r.find(f'{{{ns}}}rPr') if r is not None else None
            sz = rPr.find(f'{{{ns}}sz') if rPr is not None else None
            sz_val = sz.get(f'{{{ns}}val') if sz is not None else 'NONE'
            bold = rPr.find(f'{{{ns}}b') if rPr is not None else None
            bold_val = bold.get(f'{{{ns}}val') if bold is not None else '0'
            print(f'[{label}] pStyle={pStyle_val} sz={sz_val} bold={bold_val} "{text.strip()[:30]}"')
            break
        break
    break

z.close()
#!/usr/bin/env python3
"""Extract heading structure from the diploma template."""
import zipfile
from lxml import etree

ns = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'

z = zipfile.ZipFile('Шаблон для ДР - Copy.docx')
doc = etree.fromstring(z.read('word/document.xml'))
body = doc.find(f'{ns}body')

print('=== HEADINGS STRUCTURE ===')
for elem in body.iter():
    tag = elem.tag.split('}')[1] if '}' in elem.tag else elem.tag
    if tag == 'p':
        pPr = elem.find(f'{ns}pPr')
        if pPr is not None:
            pStyle = pPr.find(f'{ns}pStyle')
            if pStyle is not None:
                style_val = pStyle.get(f'{ns}val')
                if style_val and style_val.startswith('Heading'):
                    texts = []
                    for t in elem.findall(f'.//{ns}t'):
                        if t.text:
                            texts.append(t.text)
                    text = ''.join(texts).strip()
                    level = style_val.replace('Heading', '')
                    indent = '  ' * (int(level) if level.isdigit() else 0)
                    print(f'{indent}H{level}: {text[:120]}')

# Also print all paragraphs (non-heading) to see structure
print('\n=== ALL PARAGRAPHS ===')
for elem in body.iter():
    tag = elem.tag.split('}')[1] if '}' in elem.tag else elem.tag
    if tag == 'p':
        pPr = elem.find(f'{ns}pPr')
        style_val = ''
        if pPr is not None:
            pStyle = pPr.find(f'{ns}pStyle')
            if pStyle is not None:
                style_val = pStyle.get(f'{ns}val', '')
        texts = []
        for t in elem.findall(f'.//{ns}t'):
            if t.text:
                texts.append(t.text)
        text = ''.join(texts).strip()
        if text:
            extra = f' [{style_val}]' if style_val else ''
            print(f'  {text[:150]}{extra}')
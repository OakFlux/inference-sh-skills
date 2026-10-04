from __future__ import annotations

import json
import re
from io import BytesIO

import requests
from pypdf import PdfReader

CODE = '300659'
BASE = 'https://data.eastmoney.com'
s = requests.Session()
s.headers.update({'User-Agent':'Mozilla/5.0','Referer':f'{BASE}/stockcalendar/{CODE}.html'})

calendar_url = f'{BASE}/stockcalendar/{CODE}.html'
r = s.get(calendar_url, timeout=(20,90))
print('CALENDAR', r.status_code, r.headers.get('content-type'), len(r.content), r.url, flush=True)
r.raise_for_status()
text = r.text

# Extract compact event objects embedded in var pagedata.
blocks = []
for match in re.finditer(r'\{[^{}]{0,8000}?"EVENT_TYPE_CODE"\s*:\s*"020"[^{}]{0,8000}?\}', text, re.S):
    try:
        obj = json.loads(match.group(0))
    except Exception:
        continue
    if str(obj.get('SECURITY_CODE')) == CODE and obj.get('INFO_CODE'):
        blocks.append(obj)

# Deduplicate by info code and sort newest first.
by_code = {str(x['INFO_CODE']): x for x in blocks}
items = sorted(by_code.values(), key=lambda x: str(x.get('NOTICE_DATE') or ''), reverse=True)
print('REPORT_EVENTS', len(items), flush=True)
for obj in items:
    print('EVENT', json.dumps(obj, ensure_ascii=False), flush=True)

for obj in items:
    info = str(obj['INFO_CODE'])
    detail_url = f'{BASE}/report/info/{info}.html'
    detail = s.get(detail_url, timeout=(20,60))
    title_match = re.search(r'<h1[^>]*>(.*?)</h1>', detail.text, re.S | re.I)
    title = re.sub(r'<[^>]+>', '', title_match.group(1)).strip() if title_match else ''
    spans = [re.sub(r'<[^>]+>','', x).strip() for x in re.findall(r'<span[^>]*>(.*?)</span>', detail.text, re.S|re.I)]
    spans = [x for x in spans if x]
    pdf_match = re.search(r'href=["\'](https://pdf\.dfcfw\.com/pdf/[^"\']+\.pdf[^"\']*)', detail.text, re.I)
    pdf_url = pdf_match.group(1).split('?')[0] if pdf_match else f'https://pdf.dfcfw.com/pdf/H3_{info}_1.pdf'
    pdf = s.get(pdf_url, timeout=(20,120))
    pages = None
    if pdf.status_code == 200 and pdf.content.startswith(b'%PDF'):
        try:
            pages = len(PdfReader(BytesIO(pdf.content), strict=False).pages)
        except Exception as exc:
            pages = f'ERR:{exc!r}'
    print('DETAIL', json.dumps({
        'date': obj.get('NOTICE_DATE'),
        'infoCode': info,
        'eventTitle': obj.get('LEVEL1_CONTENT'),
        'pageTitle': title,
        'spans': spans[:20],
        'pdfUrl': pdf_url,
        'status': pdf.status_code,
        'bytes': len(pdf.content),
        'pages': pages,
    }, ensure_ascii=False), flush=True)

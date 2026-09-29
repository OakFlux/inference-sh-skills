from __future__ import annotations

import json
import re
import requests
from pypdf import PdfReader
from io import BytesIO

CODES = [
    'AP201408130006631015',
    'AP201407180006381375',
    'AP201208210005449688',
    'AP201206050005274029',
    'AP201203270005067117',
    'AS201202190003064346',
    'AS201202180003056551',
    'AS201202170003042583',
]
PATTERNS = [
    'https://pdf.dfcfw.com/pdf/H3_{code}_1.pdf',
    'https://pdf.dfcfw.com/pdf/{code}_1.pdf',
    'https://pdf.dfcfw.com/pdf/H3_{code}.pdf',
    'https://pdf.dfcfw.com/pdf/{code}.pdf',
    'https://pdf.dfcfw.com/pdf/H3_{code}_1.PDF',
]
DETAILS = [
    'https://data.eastmoney.com/report/info/{code}.html',
    'https://data.eastmoney.com/report/zw_stock.jshtml?infocode={code}',
]

s=requests.Session()
s.headers.update({'User-Agent':'Mozilla/5.0','Referer':'https://data.eastmoney.com/'})

for code in CODES:
    print('\n=== CODE',code,'===',flush=True)
    for template in DETAILS:
        url=template.format(code=code)
        try:
            r=s.get(url,timeout=(15,45),allow_redirects=True)
            print('DETAIL',r.status_code,r.headers.get('content-type'),len(r.content),r.url,flush=True)
            txt=r.text
            for key in ['机构','研究员','页数','报告名称','宏源证券','民生证券','天风证券','长江证券','兴业证券','东兴证券','中信证券','银河证券']:
                p=txt.find(key)
                if p>=0:
                    print('DETAIL_CTX',key,txt[max(0,p-250):p+600].replace('\n',' ')[:850],flush=True)
            for rx in [r'https?://[^"\']+\.pdf[^"\']*',r'pdf[^"\']{0,300}',r'orgSName[^,]{0,200}',r'researcher[^,]{0,200}']:
                found=re.findall(rx,txt,re.I)
                if found:
                    print('DETAIL_RX',rx,found[:10],flush=True)
        except Exception as exc:
            print('DETAIL_ERR',url,repr(exc),flush=True)

    for template in PATTERNS:
        url=template.format(code=code)
        try:
            r=s.get(url,timeout=(15,60),allow_redirects=True)
            data=r.content
            head=data[:8]
            pages=None
            if r.status_code==200 and head.startswith(b'%PDF'):
                try:
                    pages=len(PdfReader(BytesIO(data),strict=False).pages)
                except Exception as exc:
                    pages=f'ERR:{exc!r}'
            print('PDF',r.status_code,r.headers.get('content-type'),len(data),head,r.url,'pages',pages,flush=True)
        except Exception as exc:
            print('PDF_ERR',url,repr(exc),flush=True)

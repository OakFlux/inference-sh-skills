from __future__ import annotations

import json
from pathlib import Path

import requests

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/152 Safari/537.36"
s = requests.Session()
s.trust_env = False
s.headers.update({"User-Agent": UA, "Referer": "https://data.eastmoney.com/"})

params = {
    "industryCode": "*",
    "pageSize": "100",
    "industry": "*",
    "rating": "*",
    "ratingChange": "*",
    "beginTime": "2000-01-01",
    "endTime": "2030-01-01",
    "pageNo": "1",
    "fields": "",
    "qType": "0",
    "orgCode": "",
    "code": "002513",
    "rcode": "",
    "p": "1",
    "pageNum": "1",
    "pageNumber": "1",
}

url = "https://reportapi.eastmoney.com/report/list"
r = s.get(url, params=params, timeout=(20, 120))
print("LIST", r.status_code, r.url, r.headers.get("content-type"), len(r.content))
print(r.text[:1000])
r.raise_for_status()
obj = r.json()
print("TOP_KEYS", list(obj) if isinstance(obj, dict) else type(obj))
print(json.dumps(obj, ensure_ascii=False, indent=2)[:100000])

records = []
if isinstance(obj, dict):
    for key in ["data", "Data", "result", "Result"]:
        value = obj.get(key)
        if isinstance(value, list):
            records = value
            break
        if isinstance(value, dict):
            for subkey in ["data", "list", "items", "records"]:
                if isinstance(value.get(subkey), list):
                    records = value[subkey]
                    break
        if records:
            break

print("RECORD_COUNT", len(records))
for rec in records:
    code = rec.get("infoCode") or rec.get("info_code") or rec.get("INFO_CODE") or rec.get("reportId")
    compact = {
        k: rec.get(k)
        for k in [
            "infoCode", "title", "stockName", "stockCode", "orgSName", "orgName",
            "researcher", "publishDate", "emRatingName", "ratingName", "attachPages",
            "attachSize", "reportType", "industryName", "encodeUrl"
        ]
    }
    print("RECORD", json.dumps(compact, ensure_ascii=False))
    if not code:
        continue
    for template in [
        f"https://pdf.dfcfw.com/pdf/H3_{code}_1.pdf",
        f"https://pdf.dfcfw.com/pdf/H3_{code}_1.pdf?{code}.pdf",
    ]:
        try:
            p = s.get(template, timeout=(20, 120), allow_redirects=True)
            print("PDF", code, p.status_code, p.url, p.headers.get("content-type"), len(p.content), p.content[:8])
        except Exception as e:
            print("PDF_ERROR", code, repr(e))

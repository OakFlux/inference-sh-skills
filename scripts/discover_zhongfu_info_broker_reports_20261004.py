from __future__ import annotations

import json
import re
from io import BytesIO

import requests
from pypdf import PdfReader

CODE = "300659"
BEGIN = "2017-01-01"
END = "2026-10-04"

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0",
    "Referer": "https://data.eastmoney.com/",
})

params = {
    "industryCode": "*",
    "pageSize": "100",
    "industry": "*",
    "rating": "*",
    "ratingChange": "*",
    "beginTime": BEGIN,
    "endTime": END,
    "pageNo": "1",
    "fields": "",
    "qType": "0",
    "orgCode": "",
    "code": CODE,
    "rcode": "",
    "p": "1",
    "pageNum": "1",
    "pageNumber": "1",
}
url = "https://reportapi.eastmoney.com/report/list"
response = session.get(url, params=params, timeout=(20, 90))
print("API", response.status_code, response.headers.get("content-type"), len(response.content), response.url, flush=True)
response.raise_for_status()
data = response.json()
rows = data.get("data") or data.get("result") or []
print("COUNT", len(rows), flush=True)

for row in rows:
    print("REPORT", json.dumps({
        "publishDate": row.get("publishDate"),
        "title": row.get("title"),
        "orgSName": row.get("orgSName"),
        "researcher": row.get("researcher"),
        "infoCode": row.get("infoCode"),
        "attachPages": row.get("attachPages"),
        "attachSize": row.get("attachSize"),
        "emRatingName": row.get("emRatingName"),
        "reportType": row.get("reportType"),
    }, ensure_ascii=False), flush=True)

# Probe every report with at least 8 indexed pages, plus known deep-report title terms.
for row in rows:
    try:
        indexed_pages = int(row.get("attachPages") or 0)
    except Exception:
        indexed_pages = 0
    title = str(row.get("title") or "")
    if indexed_pages < 8 and not any(k in title for k in ("首次覆盖", "深度", "困境反转", "新台阶")):
        continue
    info = str(row.get("infoCode") or "")
    if not info:
        continue
    detail_url = f"https://data.eastmoney.com/report/info/{info}.html"
    detail = session.get(detail_url, timeout=(20, 60))
    pdf_match = re.search(r'href=["\'](https://pdf\.dfcfw\.com/pdf/[^"\']+\.pdf[^"\']*)', detail.text, re.I)
    pdf_url = pdf_match.group(1) if pdf_match else f"https://pdf.dfcfw.com/pdf/H3_{info}_1.pdf"
    clean_pdf_url = pdf_url.split("?")[0]
    pdf = session.get(clean_pdf_url, timeout=(20, 120))
    pages = None
    if pdf.status_code == 200 and pdf.content.startswith(b"%PDF"):
        try:
            pages = len(PdfReader(BytesIO(pdf.content), strict=False).pages)
        except Exception as exc:
            pages = f"ERR:{exc!r}"
    print("PROBE", json.dumps({
        "publishDate": row.get("publishDate"),
        "title": title,
        "orgSName": row.get("orgSName"),
        "researcher": row.get("researcher"),
        "infoCode": info,
        "indexedPages": indexed_pages,
        "pdfUrl": clean_pdf_url,
        "status": pdf.status_code,
        "bytes": len(pdf.content),
        "pages": pages,
    }, ensure_ascii=False), flush=True)

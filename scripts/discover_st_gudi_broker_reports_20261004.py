from __future__ import annotations

import json
import re
from html import unescape
from io import BytesIO

import requests
from pypdf import PdfReader

CODE = "002694"
BEGIN = "2010-01-01"
END = "2026-10-04"

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/152 Safari/537.36",
    "Referer": f"https://data.eastmoney.com/report/{CODE}.html",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
})


def get(url: str, **kwargs):
    r = session.get(url, timeout=(20, 120), allow_redirects=True, **kwargs)
    print("HTTP", r.status_code, r.headers.get("content-type"), len(r.content), r.url, flush=True)
    r.raise_for_status()
    return r


def list_reports() -> list[dict]:
    url = "https://reportapi.eastmoney.com/report/list"
    all_rows: list[dict] = []
    for page in range(1, 20):
        params = {
            "industryCode": "*", "pageSize": 100, "industry": "*", "rating": "*",
            "ratingChange": "*", "beginTime": BEGIN, "endTime": END, "pageNo": page,
            "fields": "", "qType": 0, "orgCode": "", "code": CODE, "rcode": "",
            "p": page, "pageNum": page, "pageNumber": page,
        }
        r = get(url, params=params)
        data = r.json()
        rows = data.get("data") or []
        print("PAGE", page, "ROWS", len(rows), "META", json.dumps({k: data.get(k) for k in ("hits", "size", "TotalPage", "pageNo")}, ensure_ascii=False), flush=True)
        if not rows:
            break
        all_rows.extend(rows)
        total_pages = int(data.get("TotalPage") or 1)
        if page >= total_pages:
            break
    print("TOTAL_REPORTS", len(all_rows), flush=True)
    for row in all_rows:
        print("REPORT_META", json.dumps(row, ensure_ascii=False), flush=True)
    return all_rows


def detail(info_code: str) -> None:
    url = f"https://data.eastmoney.com/report/info/{info_code}.html"
    r = get(url)
    text = r.text
    title = ""
    m = re.search(r"<h1[^>]*>(.*?)</h1>", text, re.S | re.I)
    if m:
        title = unescape(re.sub(r"<[^>]+>", "", m.group(1)).strip())
    spans = [unescape(re.sub(r"<[^>]+>", "", s).strip()) for s in re.findall(r"<span[^>]*>(.*?)</span>", text, re.S | re.I)]
    spans = [x for x in spans if x]
    pdfs = re.findall(r'href=["\'](https?://[^"\']+\.pdf[^"\']*)["\']', text, re.I)
    pdf_url = pdfs[0].split("?", 1)[0] if pdfs else ""
    out = {"infoCode": info_code, "pageTitle": title, "spans": spans[:50], "pdfUrl": pdf_url, "detailUrl": url}
    if pdf_url:
        try:
            pr = get(pdf_url, headers={"Referer": url, "Accept": "application/pdf,*/*"})
            pages = len(PdfReader(BytesIO(pr.content), strict=False).pages) if pr.content.startswith(b"%PDF") else None
            out["pdfStatus"] = pr.status_code
            out["pdfBytes"] = len(pr.content)
            out["pdfPages"] = pages
        except Exception as exc:
            out["pdfError"] = repr(exc)
    print("DETAIL", json.dumps(out, ensure_ascii=False), flush=True)


rows = list_reports()
seen = set()
for row in rows:
    code = str(row.get("infoCode") or "")
    if code and code not in seen:
        seen.add(code)
        try:
            detail(code)
        except Exception as exc:
            print("DETAIL_ERROR", code, repr(exc), flush=True)

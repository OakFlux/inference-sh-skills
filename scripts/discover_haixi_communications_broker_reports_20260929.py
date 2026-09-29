from __future__ import annotations

import json
import re
from io import BytesIO
from html import unescape
from urllib.parse import urljoin

import requests
from pypdf import PdfReader

CODES = ["920405", "831305"]
BEGIN = "2020-01-01"
END = "2026-09-29"

session = requests.Session()
session.headers.update(
    {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/152 Safari/537.36",
        "Referer": "https://data.eastmoney.com/",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
)


def get(url: str, **kwargs):
    r = session.get(url, timeout=(20, 90), allow_redirects=True, **kwargs)
    print("HTTP", r.status_code, r.headers.get("content-type"), len(r.content), r.url, flush=True)
    r.raise_for_status()
    return r


def report_api(code: str) -> list[dict]:
    url = "https://reportapi.eastmoney.com/report/list"
    params = {
        "industryCode": "*",
        "pageSize": 100,
        "industry": "*",
        "rating": "*",
        "ratingChange": "*",
        "beginTime": BEGIN,
        "endTime": END,
        "pageNo": 1,
        "fields": "",
        "qType": 0,
        "orgCode": "",
        "code": code,
        "rcode": "",
        "p": 1,
        "pageNum": 1,
        "pageNumber": 1,
    }
    r = get(url, params=params, headers={"Referer": f"https://data.eastmoney.com/report/{code}.html"})
    data = r.json()
    rows = data.get("data") or data.get("result") or []
    if isinstance(rows, dict):
        rows = rows.get("data") or rows.get("list") or []
    print("API_ROWS", code, len(rows), flush=True)
    for row in rows:
        print("API_REPORT", json.dumps(row, ensure_ascii=False), flush=True)
    return list(rows)


def extract_pagedata(text: str) -> dict:
    marker = "var pagedata ="
    pos = text.find(marker)
    if pos < 0:
        return {}
    start = text.find("{", pos)
    if start < 0:
        return {}
    decoder = json.JSONDecoder()
    try:
        obj, _ = decoder.raw_decode(text[start:])
        return obj if isinstance(obj, dict) else {}
    except Exception as exc:
        print("PAGEDATA_ERROR", repr(exc), flush=True)
        return {}


def calendar_reports(code: str) -> list[dict]:
    r = get(f"https://data.eastmoney.com/stockcalendar/{code}.html")
    data = extract_pagedata(r.text)
    rows = (((data.get("sjyl") or {}).get("result") or {}).get("data") or [])
    out = []
    for row in rows:
        if str(row.get("EVENT_TYPE_CODE")) == "020" and row.get("INFO_CODE"):
            out.append(row)
            print("CAL_REPORT", json.dumps(row, ensure_ascii=False), flush=True)
    print("CAL_ROWS", code, len(out), flush=True)
    return out


def detail(info_code: str) -> dict:
    url = f"https://data.eastmoney.com/report/info/{info_code}.html"
    r = get(url)
    text = r.text
    title = ""
    m = re.search(r"<h1[^>]*>(.*?)</h1>", text, re.S | re.I)
    if m:
        title = re.sub(r"<[^>]+>", "", m.group(1)).strip()
    spans = [re.sub(r"<[^>]+>", "", s).strip() for s in re.findall(r"<span[^>]*>(.*?)</span>", text, re.S | re.I)]
    spans = [unescape(x) for x in spans if x]
    pdfs = re.findall(r'href=["\'](https?://[^"\']+\.pdf[^"\']*)["\']', text, re.I)
    pdf_url = pdfs[0] if pdfs else ""
    clean_pdf_url = pdf_url.split("?", 1)[0]
    result = {"info_code": info_code, "title": unescape(title), "spans": spans[:40], "pdf_url": clean_pdf_url, "detail_url": url}
    print("DETAIL", json.dumps(result, ensure_ascii=False), flush=True)
    if clean_pdf_url:
        try:
            pr = get(clean_pdf_url, headers={"Referer": url, "Accept": "application/pdf,*/*"})
            pages = None
            if pr.content.startswith(b"%PDF"):
                pages = len(PdfReader(BytesIO(pr.content), strict=False).pages)
            print("PDF_META", info_code, pages, len(pr.content), pr.url, flush=True)
        except Exception as exc:
            print("PDF_ERROR", info_code, repr(exc), flush=True)
    return result


all_info_codes: list[str] = []
for code in CODES:
    try:
        rows = report_api(code)
        for row in rows:
            info = str(row.get("infoCode") or row.get("info_code") or row.get("INFO_CODE") or "")
            if info:
                all_info_codes.append(info)
    except Exception as exc:
        print("API_ERROR", code, repr(exc), flush=True)
    try:
        rows = calendar_reports(code)
        all_info_codes.extend(str(row.get("INFO_CODE")) for row in rows if row.get("INFO_CODE"))
    except Exception as exc:
        print("CAL_ERROR", code, repr(exc), flush=True)

# Add codes already identified through public search to ensure full metadata recovery.
all_info_codes.extend([])

seen = set()
for info_code in all_info_codes:
    if not info_code or info_code in seen:
        continue
    seen.add(info_code)
    try:
        detail(info_code)
    except Exception as exc:
        print("DETAIL_ERROR", info_code, repr(exc), flush=True)

print("UNIQUE_INFO_CODES", json.dumps(sorted(seen), ensure_ascii=False), flush=True)

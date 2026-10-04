from __future__ import annotations

import json
import re
from io import BytesIO
from html import unescape

import requests
from pypdf import PdfReader

CODE = "605011"
BEGIN = "2020-01-01"
END = "2026-10-04"

session = requests.Session()
session.headers.update(
    {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/152 Safari/537.36",
        "Referer": "https://data.eastmoney.com/",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
)


def get(url: str, **kwargs):
    response = session.get(url, timeout=(20, 90), allow_redirects=True, **kwargs)
    print("HTTP", response.status_code, response.headers.get("content-type"), len(response.content), response.url, flush=True)
    response.raise_for_status()
    return response


def report_api() -> list[dict]:
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
        "code": CODE,
        "rcode": "",
        "p": 1,
        "pageNum": 1,
        "pageNumber": 1,
    }
    response = get(url, params=params, headers={"Referer": f"https://data.eastmoney.com/report/{CODE}.html"})
    data = response.json()
    rows = data.get("data") or data.get("result") or []
    if isinstance(rows, dict):
        rows = rows.get("data") or rows.get("list") or []
    print("API_ROWS", len(rows), flush=True)
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


def calendar_reports() -> list[dict]:
    response = get(f"https://data.eastmoney.com/stockcalendar/{CODE}.html")
    data = extract_pagedata(response.text)
    rows = (((data.get("sjyl") or {}).get("result") or {}).get("data") or [])
    reports = []
    for row in rows:
        if str(row.get("EVENT_TYPE_CODE")) == "020" and row.get("INFO_CODE"):
            reports.append(row)
            print("CAL_REPORT", json.dumps(row, ensure_ascii=False), flush=True)
    print("CAL_ROWS", len(reports), flush=True)
    return reports


def detail(info_code: str) -> dict:
    url = f"https://data.eastmoney.com/report/info/{info_code}.html"
    response = get(url)
    text = response.text
    title = ""
    match = re.search(r"<h1[^>]*>(.*?)</h1>", text, re.S | re.I)
    if match:
        title = re.sub(r"<[^>]+>", "", match.group(1)).strip()
    spans = [re.sub(r"<[^>]+>", "", value).strip() for value in re.findall(r"<span[^>]*>(.*?)</span>", text, re.S | re.I)]
    spans = [unescape(value) for value in spans if value]
    pdfs = re.findall(r'href=["\'](https?://[^"\']+\.pdf[^"\']*)["\']', text, re.I)
    pdf_url = pdfs[0].split("?", 1)[0] if pdfs else ""
    result = {
        "info_code": info_code,
        "title": unescape(title),
        "spans": spans[:40],
        "pdf_url": pdf_url,
        "detail_url": url,
    }
    print("DETAIL", json.dumps(result, ensure_ascii=False), flush=True)
    if pdf_url:
        pdf_response = get(pdf_url, headers={"Referer": url, "Accept": "application/pdf,*/*"})
        pages = None
        if pdf_response.content.startswith(b"%PDF"):
            pages = len(PdfReader(BytesIO(pdf_response.content), strict=False).pages)
        print("PDF_META", info_code, pages, len(pdf_response.content), pdf_response.url, flush=True)
    return result


info_codes: list[str] = []
try:
    for row in report_api():
        info = str(row.get("infoCode") or row.get("info_code") or row.get("INFO_CODE") or "")
        if info:
            info_codes.append(info)
except Exception as exc:
    print("API_ERROR", repr(exc), flush=True)

try:
    for row in calendar_reports():
        info = str(row.get("INFO_CODE") or "")
        if info:
            info_codes.append(info)
except Exception as exc:
    print("CAL_ERROR", repr(exc), flush=True)

seen: set[str] = set()
for info_code in info_codes:
    if not info_code or info_code in seen:
        continue
    seen.add(info_code)
    try:
        detail(info_code)
    except Exception as exc:
        print("DETAIL_ERROR", info_code, repr(exc), flush=True)

print("UNIQUE_INFO_CODES", json.dumps(sorted(seen), ensure_ascii=False), flush=True)

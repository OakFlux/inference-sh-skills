from __future__ import annotations

import json
import re
from html import unescape
from io import BytesIO

import requests
from pypdf import PdfReader

TARGET_CODES = {"002694"}
TARGET_NAMES = ("顾地科技", "ST顾地", "*ST顾地", "顾地")
WINDOWS = [
    ("2012-07-01", "2012-10-31"),
    ("2013-02-01", "2013-05-31"),
    ("2014-02-01", "2014-05-31"),
    ("2015-02-01", "2015-05-31"),
    ("2016-02-01", "2016-05-31"),
    ("2017-02-01", "2017-05-31"),
]

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/152 Safari/537.36",
    "Referer": "https://data.eastmoney.com/report/",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
})


def call_api(begin: str, end: str, page: int) -> dict:
    url = "https://reportapi.eastmoney.com/report/list"
    params = {
        "industryCode": "*", "pageSize": 100, "industry": "*", "rating": "*",
        "ratingChange": "*", "beginTime": begin, "endTime": end, "pageNo": page,
        "fields": "", "qType": 0, "orgCode": "", "code": "", "rcode": "",
        "p": page, "pageNum": page, "pageNumber": page,
    }
    r = session.get(url, params=params, timeout=(20, 120))
    print("CALL", begin, end, page, r.status_code, len(r.content), r.url, flush=True)
    r.raise_for_status()
    return r.json()


def is_match(row: dict) -> bool:
    code = str(row.get("stockCode") or "")
    name = str(row.get("stockName") or "")
    title = str(row.get("title") or "")
    return code in TARGET_CODES or any(term in name or term in title for term in TARGET_NAMES)


matches: dict[str, dict] = {}
for begin, end in WINDOWS:
    page = 1
    while True:
        data = call_api(begin, end, page)
        rows = data.get("data") or []
        for row in rows:
            if is_match(row):
                key = str(row.get("infoCode") or json.dumps(row, ensure_ascii=False))
                matches[key] = row
                print("MATCH", json.dumps(row, ensure_ascii=False), flush=True)
        total_pages = int(data.get("TotalPage") or 1)
        if not rows or page >= total_pages:
            break
        page += 1
        if page > 60:
            raise RuntimeError(f"Too many pages for {begin}-{end}")

# Parse Eastmoney stock calendar for any report events not exposed by report/list.
cal_url = "https://data.eastmoney.com/stockcalendar/002694.html"
r = session.get(cal_url, timeout=(20, 120))
print("CAL", r.status_code, len(r.content), r.url, flush=True)
r.raise_for_status()
text = r.text
marker = "var pagedata ="
pos = text.find(marker)
if pos >= 0:
    start = text.find("{", pos)
    if start >= 0:
        try:
            data, _ = json.JSONDecoder().raw_decode(text[start:])
            rows = (((data.get("sjyl") or {}).get("result") or {}).get("data") or [])
            for row in rows:
                if str(row.get("EVENT_TYPE_CODE")) == "020":
                    print("CAL_REPORT", json.dumps(row, ensure_ascii=False), flush=True)
                    info = str(row.get("INFO_CODE") or "")
                    if info:
                        matches.setdefault(info, {"infoCode": info, "calendar": row})
        except Exception as exc:
            print("CAL_PARSE_ERROR", repr(exc), flush=True)

print("MATCH_COUNT", len(matches), flush=True)

for info_code, row in matches.items():
    if not info_code.startswith("AP"):
        continue
    url = f"https://data.eastmoney.com/report/info/{info_code}.html"
    try:
        rr = session.get(url, timeout=(20, 120))
        print("DETAIL_HTTP", info_code, rr.status_code, len(rr.content), rr.url, flush=True)
        rr.raise_for_status()
        html = rr.text
        title = ""
        m = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.S | re.I)
        if m:
            title = unescape(re.sub(r"<[^>]+>", "", m.group(1)).strip())
        spans = [unescape(re.sub(r"<[^>]+>", "", s).strip()) for s in re.findall(r"<span[^>]*>(.*?)</span>", html, re.S | re.I)]
        spans = [x for x in spans if x]
        pdfs = re.findall(r'href=["\'](https?://[^"\']+\.pdf[^"\']*)["\']', html, re.I)
        pdf_url = pdfs[0].split("?", 1)[0] if pdfs else ""
        detail = {"infoCode": info_code, "row": row, "pageTitle": title, "spans": spans[:40], "pdfUrl": pdf_url}
        if pdf_url:
            pr = session.get(pdf_url, timeout=(20, 120), headers={"Referer": url, "Accept": "application/pdf,*/*"})
            detail["pdfStatus"] = pr.status_code
            detail["pdfBytes"] = len(pr.content)
            if pr.content.startswith(b"%PDF"):
                detail["pdfPages"] = len(PdfReader(BytesIO(pr.content), strict=False).pages)
        print("DETAIL", json.dumps(detail, ensure_ascii=False), flush=True)
    except Exception as exc:
        print("DETAIL_ERROR", info_code, repr(exc), flush=True)

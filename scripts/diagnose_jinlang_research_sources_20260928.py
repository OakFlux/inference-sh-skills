from __future__ import annotations

import html
import json
import re
from urllib.parse import urljoin

import requests

S = requests.Session()
S.trust_env = False
HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

PAGES = [
    "https://bg.sgpjbg.com/bgdown/5748.html",
    "https://www.sgpjbg.com.cn/baogao/19533.html",
    "https://www.nxny.com/report/view_4415280.html",
    "https://stock.jrj.com.cn/2023/03/02140937373614.shtml",
]


def get(url: str, **kwargs):
    r = S.get(url, headers=HEADERS, timeout=60, allow_redirects=True, **kwargs)
    print("GET", url, "status", r.status_code, "type", r.headers.get("content-type"), "len", len(r.content), "final", r.url, flush=True)
    return r


for page in PAGES:
    try:
        r = get(page)
        text = r.text
        print("TITLE", re.findall(r"<title[^>]*>(.*?)</title>", text, flags=re.I | re.S)[:2], flush=True)
        attrs = re.findall(r"(?:href|src|data-url|data-src|content)=[\"']([^\"']+)[\"']", text, flags=re.I)
        selected = []
        for raw in attrs:
            value = html.unescape(raw)
            low = value.lower()
            if any(token in low for token in (".pdf", "download", "down", "preview", "file", "docview", "read")):
                selected.append(urljoin(r.url, value))
        for item in list(dict.fromkeys(selected))[:100]:
            print("CANDIDATE", item, flush=True)
        for token in (".pdf", "pdfurl", "downloadurl", "downurl", "fileurl", "file_url", "documenturl", "preview"):
            idx = text.lower().find(token.lower())
            if idx >= 0:
                print("SNIPPET", token, text[max(0, idx-500):idx+1000].replace("\n", " ")[:1600], flush=True)
    except Exception as exc:
        print("PAGE_ERROR", page, repr(exc), flush=True)

api_urls = [
    "https://reportapi.eastmoney.com/report/list?cb=datatable&pageSize=50&pageNo=1&fields=&qType=0&orgCode=&author=&beginTime=2023-03-01&endTime=2023-03-03&code=300763&industryCode=*&industry=*&rating=*&ratingChange=*",
    "https://reportapi.eastmoney.com/report/list?cb=datatable&pageSize=100&pageNo=1&fields=&qType=0&orgCode=&author=&beginTime=2020-01-01&endTime=2023-12-31&code=300763&industryCode=*&industry=*&rating=*&ratingChange=*",
]
for url in api_urls:
    try:
        r = get(url)
        print("API_TEXT", r.text[:12000], flush=True)
    except Exception as exc:
        print("API_ERROR", repr(exc), flush=True)

ap_ids = [
    "AP202206291575539306",
    "AP202206231574294746",
]
for ap in ap_ids:
    for suffix in ("_1.pdf", ".pdf"):
        url = f"https://pdf.dfcfw.com/pdf/H3_{ap}{suffix}"
        try:
            r = get(url, stream=True)
            first = next(r.iter_content(32), b"")
            print("PDF_PROBE", url, "head", first[:16], "length", r.headers.get("content-length"), flush=True)
            r.close()
        except Exception as exc:
            print("PDF_PROBE_ERROR", url, repr(exc), flush=True)

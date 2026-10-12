from __future__ import annotations

import html
import json
import re
from urllib.parse import urljoin

import requests

REPORT_IDS = [
    "788464099552",
    "788430748152",
    "763549027077",
    "762789035848",
]

session = requests.Session()
session.trust_env = False
headers = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/155 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Referer": "https://finance.sina.com.cn/realstock/company/sh603344/nc.shtml",
}

for report_id in REPORT_IDS:
    url = (
        "https://stock.finance.sina.com.cn/stock/go.php/"
        f"vReport_Show/kind/search/rptid/{report_id}/index.phtml"
    )
    response = session.get(url, headers=headers, timeout=90, allow_redirects=True)
    response.encoding = response.apparent_encoding or "gb18030"
    text = response.text
    print("\n=== REPORT", report_id, "===", flush=True)
    print(
        "HTTP",
        response.status_code,
        response.headers.get("content-type"),
        len(response.content),
        response.url,
        response.encoding,
        flush=True,
    )

    title_match = re.search(r"<h1[^>]*>(.*?)</h1>", text, re.I | re.S)
    page_title = re.search(r"<title>(.*?)</title>", text, re.I | re.S)
    broker = re.search(r"机构：.*?>([^<>]+)</a>", text, re.S)
    analysts = re.search(r"研究员：.*?>([^<>]+)</a>", text, re.S)
    date = re.search(r"日期：\s*([0-9-]+)", text)
    metadata = {
        "h1": re.sub(r"<[^>]+>", "", title_match.group(1)).strip() if title_match else None,
        "title": re.sub(r"<[^>]+>", "", page_title.group(1)).strip() if page_title else None,
        "broker": broker.group(1).strip() if broker else None,
        "analysts": analysts.group(1).strip() if analysts else None,
        "date": date.group(1) if date else None,
    }
    print("META", json.dumps(metadata, ensure_ascii=False), flush=True)

    body_match = re.search(
        r'<div class="blk_container">\s*<p>(.*?)</p>',
        text,
        re.I | re.S,
    )
    body = ""
    if body_match:
        body = html.unescape(re.sub(r"<br\s*/?>", "\n", body_match.group(1), flags=re.I))
        body = re.sub(r"<[^>]+>", "", body)
        body = re.sub(r"\s+", " ", body).strip()
    print("BODY_CHARS", len(body), flush=True)
    print("BODY_HEAD", body[:1200], flush=True)

    links: list[str] = []
    for match in re.finditer(r'(?:href|src)\s*=\s*["\']([^"\']+)["\']', text, re.I):
        full = urljoin(response.url, html.unescape(match.group(1)))
        low = full.lower()
        if any(key in low for key in ("pdf", "download", "attach", "file", "report", "rpt")):
            links.append(full)
    for match in re.finditer(r'https?://[^\s"\'<>]+', text, re.I):
        full = html.unescape(match.group(0)).rstrip(");,]")
        low = full.lower()
        if any(key in low for key in (".pdf", "download", "attach", "file")):
            links.append(full)
    links = list(dict.fromkeys(links))
    print("ASSET_LINKS", json.dumps(links[:200], ensure_ascii=False), flush=True)

    patterns = [
        ".pdf",
        "download",
        "附件",
        "file",
        "attach",
        "rptid",
        "研报",
        "第一页",
        "下一页",
    ]
    for pattern in patterns:
        positions = [m.start() for m in re.finditer(re.escape(pattern), text, re.I)]
        for pos in positions[:5]:
            snippet = re.sub(r"\s+", " ", text[max(0, pos - 500) : pos + 1200])
            print("SNIP", pattern, snippet[:1700], flush=True)

    script_sources = re.findall(r'<script[^>]+src=["\']([^"\']+)["\']', text, re.I)
    print(
        "SCRIPT_SOURCES",
        json.dumps([urljoin(response.url, html.unescape(src)) for src in script_sources], ensure_ascii=False),
        flush=True,
    )

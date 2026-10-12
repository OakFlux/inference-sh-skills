from __future__ import annotations

import html
import json
import re
from urllib.parse import urljoin

import requests

URLS = [
    "https://www.360why.com/bg/86378d000043600.html",
    "https://www.ifxh.com/2638.html",
    "https://stock.quote.stockstar.com/info_603344.shtml",
    "https://www.futunn.com/stock/603344-SH/institutional-ratings",
]

session = requests.Session()
session.trust_env = False
headers = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/155 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

for url in URLS:
    print("\n\n=== PAGE", url, "===", flush=True)
    try:
        response = session.get(url, headers=headers, timeout=120, allow_redirects=True)
    except Exception as exc:
        print("REQUEST_ERROR", repr(exc), flush=True)
        continue
    response.encoding = response.apparent_encoding or "utf-8"
    text = response.text
    print(
        "HTTP",
        response.status_code,
        response.headers.get("content-type"),
        len(response.content),
        response.url,
        response.encoding,
        flush=True,
    )
    title = re.search(r"<title[^>]*>(.*?)</title>", text, re.I | re.S)
    print(
        "TITLE",
        html.unescape(re.sub(r"<[^>]+>", "", title.group(1))).strip() if title else "",
        flush=True,
    )

    links: list[dict[str, str]] = []
    for match in re.finditer(
        r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>',
        text,
        re.I | re.S,
    ):
        href = urljoin(response.url, html.unescape(match.group(1)))
        label = html.unescape(re.sub(r"<[^>]+>", " ", match.group(2)))
        label = re.sub(r"\s+", " ", label).strip()
        low = (href + " " + label).lower()
        if any(
            key in low
            for key in (
                "pdf",
                "下载",
                "download",
                "file",
                "attachment",
                "preview",
                "86378d",
                "星德胜",
                "603344",
                "夸克",
                "百度",
                "pan.",
            )
        ):
            links.append({"href": href, "label": label[:300]})
    print("LINKS", json.dumps(links[:300], ensure_ascii=False), flush=True)

    assets: list[str] = []
    for match in re.finditer(r'(?:src|data-src|data-url|data-file|data-pdf)=["\']([^"\']+)["\']', text, re.I):
        full = urljoin(response.url, html.unescape(match.group(1)))
        low = full.lower()
        if any(key in low for key in ("pdf", "file", "download", "preview", "86378d", "603344", "oss", "cos", "cdn")):
            assets.append(full)
    for match in re.finditer(r'https?://[^\s"\'<>]+', text, re.I):
        full = html.unescape(match.group(0)).rstrip(");,]}")
        low = full.lower()
        if any(key in low for key in (".pdf", "download", "attachment", "86378d", "603344", "pan.baidu", "quark", "aliyundrive")):
            assets.append(full)
    print("ASSETS", json.dumps(list(dict.fromkeys(assets))[:300], ensure_ascii=False), flush=True)

    script_sources = [
        urljoin(response.url, html.unescape(source))
        for source in re.findall(r'<script[^>]+src=["\']([^"\']+)["\']', text, re.I)
    ]
    print("SCRIPTS", json.dumps(script_sources, ensure_ascii=False), flush=True)

    patterns = [
        "星德胜",
        "86378d000043600",
        "首次覆盖",
        "微特电机领域优质企业",
        ".pdf",
        "download",
        "下载",
        "pan.baidu",
        "quark",
        "attachment",
        "fileUrl",
        "pdfUrl",
    ]
    for pattern in patterns:
        positions = [m.start() for m in re.finditer(re.escape(pattern), text, re.I)]
        print("PATTERN_COUNT", pattern, len(positions), flush=True)
        for pos in positions[:12]:
            snippet = re.sub(r"\s+", " ", text[max(0, pos - 700) : pos + 1800])
            print("SNIP", pattern, snippet[:2500], flush=True)

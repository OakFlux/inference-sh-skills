from __future__ import annotations

import html
import json
import re
from urllib.parse import urljoin

import requests

URLS = [
    "https://www.fxbaogao.com/detail/4653227",
    "https://fxbaogao.com/detail/4653227",
    "https://www.fxbaogao.com/q/2606085191119851",
]

session = requests.Session()
session.trust_env = False
headers = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/155 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

for url in URLS:
    print("\n===", url, "===", flush=True)
    try:
        response = session.get(url, headers=headers, timeout=120, allow_redirects=True)
    except Exception as exc:
        print("ERROR", repr(exc), flush=True)
        continue
    response.encoding = response.apparent_encoding or "utf-8"
    text = response.text
    print("HTTP", response.status_code, response.headers.get("content-type"), len(response.content), response.url, flush=True)
    title = re.search(r"<title[^>]*>(.*?)</title>", text, re.I | re.S)
    print("TITLE", html.unescape(re.sub(r"<[^>]+>", "", title.group(1))).strip() if title else "", flush=True)

    links = []
    for m in re.finditer(r'(?:href|src|data-url|data-file|data-pdf)\s*=\s*["\']([^"\']+)["\']', text, re.I):
        full = urljoin(response.url, html.unescape(m.group(1)))
        low = full.lower()
        if any(k in low for k in ("pdf", "download", "file", "oss", "cos", "4653227", "report")):
            links.append(full)
    for m in re.finditer(r'https?://[^\s"\'<>]+', text, re.I):
        full = html.unescape(m.group(0)).rstrip(");,]}\\")
        low = full.lower()
        if any(k in low for k in (".pdf", "download", "file", "oss", "cos", "4653227")):
            links.append(full)
    print("LINKS", json.dumps(list(dict.fromkeys(links))[:500], ensure_ascii=False), flush=True)

    scripts = [urljoin(response.url, html.unescape(x)) for x in re.findall(r'<script[^>]+src=["\']([^"\']+)["\']', text, re.I)]
    print("SCRIPTS", json.dumps(scripts, ensure_ascii=False), flush=True)

    for pattern in ["4653227", ".pdf", "pdfUrl", "downloadUrl", "fileUrl", "oss", "cos", "附件", "下载", "星德胜", "微特电机领域优质企业"]:
        positions = [m.start() for m in re.finditer(re.escape(pattern), text, re.I)]
        print("COUNT", pattern, len(positions), flush=True)
        for pos in positions[:20]:
            snippet = re.sub(r"\s+", " ", text[max(0, pos - 700):pos + 1800])
            print("SNIP", pattern, snippet[:2500], flush=True)

    for script_url in scripts:
        if not any(k in script_url.lower() for k in ("detail", "app", "main", "chunk", "report", "index")):
            continue
        try:
            script = session.get(script_url, headers=headers, timeout=120)
            print("SCRIPT", script.status_code, len(script.content), script.url, flush=True)
            script_text = script.text
            for pattern in ["download", "pdf", "fileUrl", "detail", "4653227"]:
                positions = [m.start() for m in re.finditer(re.escape(pattern), script_text, re.I)]
                if positions:
                    print("SCRIPT_COUNT", script_url, pattern, len(positions), flush=True)
                    for pos in positions[:8]:
                        snippet = re.sub(r"\s+", " ", script_text[max(0, pos - 500):pos + 1400])
                        print("SCRIPT_SNIP", pattern, snippet[:1900], flush=True)
        except Exception as exc:
            print("SCRIPT_ERROR", script_url, repr(exc), flush=True)

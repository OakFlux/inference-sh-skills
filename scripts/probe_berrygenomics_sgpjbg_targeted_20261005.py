from __future__ import annotations

import html
import json
import re
from urllib.parse import urljoin

import requests

LIST_PAGES = [
    "https://www.sgpjbg.com/labels/beiruijiyinnianbao.html",
    "https://www.sgpjbg.com.cn/labels/jiyinxingyeguojiazhengce.html",
    "https://www.sgpjbg.com.cn/bggroup/2287.html",
]
TARGETS = {
    "解码生命经纬": "东北证券2025",
    "基因测序行业的领头羊": "海通证券2020",
}

s = requests.Session()
s.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/152 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
})


def fetch(url: str):
    r = s.get(url, timeout=(15, 45), allow_redirects=True)
    print("GET", url, r.status_code, r.url, r.headers.get("content-type"), len(r.content), flush=True)
    r.raise_for_status()
    enc = r.apparent_encoding or r.encoding or "utf-8"
    return r, r.content.decode(enc, errors="replace")


def links(base: str, text: str):
    for m in re.finditer(r'''<a\b[^>]*href=["']([^"']+)["'][^>]*>(.*?)</a>''', text, re.I | re.S):
        href = urljoin(base, html.unescape(m.group(1)))
        label = re.sub(r"<[^>]+>", " ", m.group(2))
        label = re.sub(r"\s+", " ", html.unescape(label)).strip()
        yield href, label

found: dict[str, dict[str, str]] = {}
for page in LIST_PAGES:
    try:
        r, text = fetch(page)
    except Exception as exc:
        print("LIST_ERROR", page, repr(exc), flush=True)
        continue
    for href, label in links(r.url, text):
        for target, name in TARGETS.items():
            if target in label or target in html.unescape(href):
                print("MATCH", name, json.dumps({"href": href, "label": label}, ensure_ascii=False), flush=True)
                found.setdefault(target, {"href": href, "label": label, "name": name})
    for target, name in TARGETS.items():
        pos = text.find(target)
        if pos >= 0:
            print("CONTEXT", name, repr(text[max(0,pos-1000):pos+1800]), flush=True)

# Search result pages sometimes link through mobile or direct report routes; normalize and inspect only target reports.
urls: dict[str, str] = {}
for target, meta in found.items():
    href = meta["href"]
    urls[href] = meta["name"]
    m = re.search(r"/(?:baogao|bgdown)/(\d+)\.html", href)
    if m:
        ident = m.group(1)
        for host in ["https://www.sgpjbg.com", "https://www.sgpjbg.com.cn", "https://m.sgpjbg.com.cn"]:
            urls[f"{host}/baogao/{ident}.html"] = meta["name"]
            urls[f"{host}/bgdown/{ident}.html"] = meta["name"]

print("FOUND", json.dumps(found, ensure_ascii=False, indent=2), flush=True)
print("URLS", json.dumps(urls, ensure_ascii=False, indent=2), flush=True)
for url, name in urls.items():
    print("\nDETAIL", name, url, flush=True)
    try:
        r, text = fetch(url)
    except Exception as exc:
        print("DETAIL_ERROR", url, repr(exc), flush=True)
        continue
    print("PREFIX", repr(text[:1200]), flush=True)
    candidates = set()
    for m in re.finditer(r'''(?:href|src|data-src|data-original|url|file|path|pdf|download)\s*[:=]\s*["']([^"']+)["']''', text, re.I):
        raw = html.unescape(m.group(1)).replace("\\/", "/")
        full = urljoin(r.url, raw)
        if any(k in full.lower() for k in ("pdf", "page", "preview", "image", "img", "upload", "static", "oss", "down", "file")):
            candidates.add(full)
    for m in re.finditer(r'''https?://[^\s"'<>\\]+''', text, re.I):
        full = html.unescape(m.group(0)).replace("\\/", "/")
        if any(k in full.lower() for k in ("pdf", "page", "preview", "image", "img", "upload", "static", "oss", "down", "file")):
            candidates.add(full)
    print("CANDIDATES", len(candidates), flush=True)
    for value in sorted(candidates):
        print(value, flush=True)
    for token in ["pdfurl", "fileurl", "downurl", "preview", "imageList", "pageList", "pdf", "下载", "预览"]:
        positions = [m.start() for m in re.finditer(re.escape(token), text, re.I)]
        for pos in positions[:4]:
            print("TOKEN_CONTEXT", token, repr(text[max(0,pos-500):pos+1200]), flush=True)

from __future__ import annotations

import html
import json
import re
from urllib.parse import urljoin

import requests

PAGES = [
    "https://www.sgpjbg.com/labels/beiruijiyinnianbao.html",
    "https://www.sgpjbg.com.cn/labels/jiyinxingyeguojiazhengce.html",
    "https://www.sgpjbg.com.cn/bggroup/2287.html",
]
NEEDLES = [
    "解码生命经纬",
    "基因测序行业的领头羊",
    "肿瘤早筛",
    "贝瑞基因",
]

s = requests.Session()
s.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/152 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
})


def fetch(url: str):
    r = s.get(url, timeout=(20, 120), allow_redirects=True)
    print("GET", url, r.status_code, r.url, r.headers.get("content-type"), len(r.content), flush=True)
    r.raise_for_status()
    enc = r.apparent_encoding or r.encoding or "utf-8"
    try:
        text = r.content.decode(enc, errors="replace")
    except Exception:
        text = r.text
    return r, text


def collect_links(base: str, text: str):
    links = []
    for m in re.finditer(r'''<a\b[^>]*href=["']([^"']+)["'][^>]*>(.*?)</a>''', text, re.I | re.S):
        href = urljoin(base, html.unescape(m.group(1)))
        label = re.sub(r"<[^>]+>", " ", m.group(2))
        label = re.sub(r"\s+", " ", html.unescape(label)).strip()
        links.append((href, label))
    return links

report_urls: dict[str, str] = {}
for page in PAGES:
    print("\n==== LIST PAGE", page, "====", flush=True)
    try:
        r, text = fetch(page)
    except Exception as exc:
        print("LIST_ERROR", page, repr(exc), flush=True)
        continue
    print("PREFIX", repr(text[:1000]), flush=True)
    links = collect_links(r.url, text)
    print("LINK_COUNT", len(links), flush=True)
    for needle in NEEDLES:
        positions = [m.start() for m in re.finditer(re.escape(needle), text, re.I)]
        print("NEEDLE", needle, "COUNT", len(positions), flush=True)
        for pos in positions[:10]:
            print("CONTEXT", needle, repr(text[max(0, pos-1600):pos+2400]), flush=True)
    for href, label in links:
        if any(needle in label for needle in NEEDLES) or any(needle in href for needle in NEEDLES):
            print("MATCH_LINK", json.dumps({"href": href, "label": label}, ensure_ascii=False), flush=True)
            if re.search(r"/(?:baogao|bgdown)/\d+\.html", href):
                report_urls[href] = label

# Infer paired baogao/bgdown URLs and inspect each.
all_urls = dict(report_urls)
for href, label in list(report_urls.items()):
    if "/baogao/" in href:
        all_urls[href.replace("/baogao/", "/bgdown/")] = label
    if "/bgdown/" in href:
        all_urls[href.replace("/bgdown/", "/baogao/")] = label

print("\nREPORT_URLS", json.dumps(all_urls, ensure_ascii=False, indent=2), flush=True)
for url, label in all_urls.items():
    print("\n==== DETAIL", url, label, "====", flush=True)
    try:
        r, text = fetch(url)
    except Exception as exc:
        print("DETAIL_ERROR", url, repr(exc), flush=True)
        continue
    print("PREFIX", repr(text[:1800]), flush=True)
    # Print contexts around useful tokens.
    for token in ["pdf", "download", "down", "preview", "page", "file", "image", "oss", "static", "立即下载", "报告预览"]:
        positions = [m.start() for m in re.finditer(re.escape(token), text, re.I)]
        if positions:
            print("TOKEN", token, "COUNT", len(positions), flush=True)
            for pos in positions[:5]:
                print("TOKEN_CONTEXT", token, repr(text[max(0, pos-700):pos+1500]), flush=True)
    candidates = set()
    for m in re.finditer(r'''(?:href|src|data-src|url|file|path|pdf|download)\s*[:=]\s*["']([^"']+)["']''', text, re.I):
        value = html.unescape(m.group(1)).replace("\\/", "/")
        full = urljoin(r.url, value)
        if any(k in full.lower() for k in ("pdf", "download", "down", "preview", "page", "file", "image", "img", "oss", "static", "upload", "baogao", "bgdown")):
            candidates.add(full)
    for m in re.finditer(r'''https?://[^\s"'<>\\]+''', text, re.I):
        full = html.unescape(m.group(0)).replace("\\/", "/")
        if any(k in full.lower() for k in ("pdf", "download", "down", "preview", "page", "file", "image", "img", "oss", "static", "upload")):
            candidates.add(full)
    print("CANDIDATES", len(candidates), flush=True)
    for value in sorted(candidates):
        print(value, flush=True)

from __future__ import annotations

import json
import re
from urllib.parse import urljoin

import requests

session = requests.Session()
session.trust_env = False
headers = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/152 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

pages = [
    ("国泰君安2019首次覆盖", "https://fxbaogao.com/detail/1332144"),
    ("银河2025首次覆盖目录", "https://299sucai.com/hybg/10766/"),
]

for label, url in pages:
    print("\n=====", label, url, flush=True)
    r = session.get(url, headers=headers, timeout=90, allow_redirects=True)
    print("STATUS", r.status_code, r.url, r.headers.get("content-type"), len(r.content), flush=True)
    text = r.text
    title = re.search(r"<title[^>]*>(.*?)</title>", text, re.I | re.S)
    print("TITLE", re.sub(r"\s+", " ", title.group(1).strip()) if title else "", flush=True)

    # Print all potentially relevant links and attributes.
    candidates = []
    patterns = [
        r"(?:href|src|data-src|data-original|data-url|content)\s*=\s*[\"']([^\"']+)[\"']",
        r"[\"'](https?:\\?/\\?/[^\"']+)[\"']",
        r"[\"']([^\"']*(?:\.pdf|\.jpg|\.jpeg|\.png|download|preview|viewer|report|document|file)[^\"']*)[\"']",
    ]
    for pat in patterns:
        for value in re.findall(pat, text, re.I):
            value = value.replace("\\/", "/")
            if value.startswith("data:"):
                continue
            full = urljoin(r.url, value)
            if full not in candidates:
                candidates.append(full)
    for full in candidates:
        low = full.lower()
        if any(k in low for k in [".pdf", ".jpg", ".jpeg", ".png", "download", "preview", "viewer", "report", "document", "file", "api"]):
            print("ASSET", full, flush=True)

    # Surface JavaScript objects or API strings with report identifiers.
    for token in ["1332144", "pdf", "download", "preview", "document", "pages", "report", "fileUrl", "oss", "cos"]:
        for match in re.finditer(token, text, re.I):
            start = max(0, match.start() - 220)
            end = min(len(text), match.end() + 500)
            print("CTX", token, re.sub(r"\s+", " ", text[start:end]), flush=True)
            break

    print("HEADTEXT", re.sub(r"\s+", " ", text[:2500]), flush=True)

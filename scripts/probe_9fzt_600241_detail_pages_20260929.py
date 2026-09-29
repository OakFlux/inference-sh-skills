from __future__ import annotations

import json
import re
from html import unescape
from urllib.parse import urljoin

import requests

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/152 Safari/537.36"
s = requests.Session()
s.trust_env = False
headers = {"User-Agent": UA, "Accept": "text/html,application/json,*/*;q=0.8", "Accept-Language": "zh-CN,zh;q=0.9"}

URLS = [
    "https://www.9fzt.com/detail/sh_600241_10_342529751921.html",
    "https://www.9fzt.com/detail/sh_600241_10_367671422358.html",
    "https://www.9fzt.com/detail/sh_600241_10_431443338082.html",
    "https://www.9fzt.com/detail/sh_600241_10_435311825001.html",
    "https://www.9fzt.com/detail/sh_600241_10_535453743433.html",
]


def walk(value, path="root"):
    if isinstance(value, dict):
        for key, item in value.items():
            new_path = f"{path}.{key}"
            yield new_path, item
            yield from walk(item, new_path)
    elif isinstance(value, list):
        for i, item in enumerate(value):
            new_path = f"{path}[{i}]"
            yield new_path, item
            yield from walk(item, new_path)

for url in URLS:
    print("\n=== URL", url, "===", flush=True)
    r = s.get(url, headers=headers, timeout=90, allow_redirects=True)
    print("STATUS", r.status_code, "FINAL", r.url, "CT", r.headers.get("content-type"), "BYTES", len(r.content), flush=True)
    r.raise_for_status()
    text = r.content.decode(r.encoding or r.apparent_encoding or "utf-8", errors="replace")
    title_match = re.search(r"<title>(.*?)</title>", text, flags=re.I | re.S)
    print("TITLE", re.sub(r"\s+", " ", unescape(title_match.group(1))) if title_match else "", flush=True)

    next_match = re.search(r'<script[^>]+id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>', text, flags=re.I | re.S)
    if next_match:
        try:
            data = json.loads(unescape(next_match.group(1)))
            print("NEXT_TOP_KEYS", list(data.keys()), flush=True)
            interesting = []
            for path, value in walk(data):
                low = path.lower()
                if any(key in low for key in ("content", "summary", "title", "author", "org", "report", "pdf", "file", "url", "date", "source")):
                    if isinstance(value, (str, int, float, bool)) or value is None:
                        sval = str(value)
                        if len(sval) > 8000:
                            sval = sval[:8000] + "...[TRUNC]"
                        interesting.append((path, sval))
            print("NEXT_INTERESTING_COUNT", len(interesting), flush=True)
            for path, value in interesting[:500]:
                print("NEXT_FIELD", path, repr(value), flush=True)
        except Exception as exc:
            print("NEXT_PARSE_ERROR", repr(exc), flush=True)

    # Extract all URLs and likely media/document fields from raw HTML.
    patterns = [
        r'https?://[^"\'<> ]+\.pdf[^"\'<> ]*',
        r'["\']([^"\']+\.pdf[^"\']*)["\']',
        r'https?://[^"\'<> ]+(?:download|attachment|report|file)[^"\'<> ]*',
        r'(?:pdfUrl|fileUrl|downloadUrl|attachmentUrl|sourceUrl|reportUrl)["\']?\s*[:=]\s*["\']([^"\']+)["\']',
    ]
    for pat in patterns:
        vals = re.findall(pat, text, flags=re.I)
        print("RAW_PATTERN", pat, vals[:100], flush=True)

    scripts = re.findall(r'<script[^>]+src=["\']([^"\']+)["\']', text, flags=re.I)
    print("SCRIPTS", scripts, flush=True)
    # Fetch page-specific scripts and search detail/report API clues.
    for src in scripts:
        full = urljoin(r.url, src)
        if "detail" not in full.lower() and "chunk" not in full.lower():
            continue
        try:
            j = s.get(full, headers=headers, timeout=90, allow_redirects=True)
            jt = j.content.decode(j.encoding or j.apparent_encoding or "utf-8", errors="replace")
            if not any(term.lower() in jt.lower() for term in ("report/detail", "research", "article", "pdf", "download", "stock/a/report")):
                continue
            print("SCRIPT", full, "STATUS", j.status_code, "BYTES", len(j.content), flush=True)
            for term in ("stock/a/report", "report/detail", "article/detail", "download", "pdf", "getReport"):
                positions = [m.start() for m in re.finditer(re.escape(term), jt, flags=re.I)]
                for pos in positions[:20]:
                    print("SCRIPT_CONTEXT", term, re.sub(r"\s+", " ", jt[max(0,pos-1000):pos+2500]), flush=True)
        except Exception as exc:
            print("SCRIPT_ERROR", full, repr(exc), flush=True)

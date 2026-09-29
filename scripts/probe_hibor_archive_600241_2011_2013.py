from __future__ import annotations

import json
import re
from html import unescape
from urllib.parse import urljoin

import requests

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/152 Safari/537.36"
s = requests.Session()
s.trust_env = False
headers = {"User-Agent": UA, "Accept": "text/html,application/xhtml+xml,*/*;q=0.8", "Accept-Language": "zh-CN,zh;q=0.9"}
months = ["201108", "201109", "201309", "201310", "201311"]


def decode(r: requests.Response) -> str:
    for enc in (r.encoding, r.apparent_encoding, "gb18030", "gbk", "utf-8"):
        if not enc:
            continue
        try:
            return r.content.decode(enc)
        except Exception:
            pass
    return r.content.decode("utf-8", errors="replace")

all_hits = []
for month in months:
    for base in ("https://fxgroup.hibor.com.cn/archiver/", "https://www.hibor.com.cn/archiver/"):
        url = base + month + ".html"
        try:
            r = s.get(url, headers=headers, timeout=120, allow_redirects=True)
            print("ARCHIVE", month, url, "STATUS", r.status_code, "FINAL", r.url, "BYTES", len(r.content), flush=True)
            if r.status_code != 200:
                continue
            text = decode(r)
            hits = []
            for m in re.finditer(r'<a\b[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', text, flags=re.I | re.S):
                href = unescape(m.group(1))
                title = re.sub(r"<[^>]+>", "", unescape(m.group(2)))
                title = re.sub(r"\s+", " ", title).strip()
                if any(key in title for key in ("时代万恒", "辽宁时代", "600241", "ST时万")):
                    hits.append({"month": month, "title": title, "url": urljoin(r.url, href)})
            print("HITS", month, json.dumps(hits, ensure_ascii=False, indent=2), flush=True)
            all_hits.extend(hits)
            if hits:
                break
        except Exception as exc:
            print("ARCHIVE_ERROR", month, url, repr(exc), flush=True)

print("ALL_HITS", json.dumps(all_hits, ensure_ascii=False, indent=2), flush=True)

# Inspect detail pages and all candidate file/view/download links.
for hit in all_hits:
    try:
        r = s.get(hit["url"], headers=headers, timeout=90, allow_redirects=True)
        text = decode(r)
        print("DETAIL", hit["title"], hit["url"], "STATUS", r.status_code, "FINAL", r.url, "BYTES", len(r.content), flush=True)
        patterns = [
            r'https?://[^"\'<> ]+\.pdf[^"\'<> ]*',
            r'["\']([^"\']+\.pdf[^"\']*)["\']',
            r'(?:viewUrl|downloadUrl|newContentUrl|ncid)\s*=\s*["\']([^"\']+)["\']',
            r'href=["\']([^"\']*(?:view|download|down|pdf)[^"\']*)["\']',
        ]
        for pat in patterns:
            vals = re.findall(pat, text, flags=re.I)
            print("DETAIL_PATTERN", pat, vals[:50], flush=True)
        for keyword in ("时代万恒", "600241", "viewUrl", "downloadUrl", "ncid", "NewContent"):
            positions = [m.start() for m in re.finditer(keyword, text, flags=re.I)]
            for pos in positions[:8]:
                print("DETAIL_CONTEXT", keyword, re.sub(r"\s+", " ", text[max(0,pos-800):pos+1800]), flush=True)
    except Exception as exc:
        print("DETAIL_ERROR", hit, repr(exc), flush=True)

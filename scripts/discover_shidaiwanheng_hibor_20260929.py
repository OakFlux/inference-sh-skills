from __future__ import annotations

import re
from html import unescape
from urllib.parse import urljoin

import requests

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/152 Safari/537.36"
s = requests.Session()
s.trust_env = False
headers = {"User-Agent": UA, "Accept": "text/html,application/xhtml+xml,application/pdf,*/*"}

urls = [
    "https://fxgroup.hibor.com.cn/archiver/201012.html",
    "http://fxgroup.hibor.com.cn/archiver/201012.html",
    "https://www.hibor.com.cn/archiver_houtai/201012.html",
    "http://www.hibor.com.cn/archiver_houtai/201012.html",
]

for url in urls:
    try:
        r = s.get(url, headers=headers, timeout=40, allow_redirects=True)
        print("FETCH", url, "STATUS", r.status_code, "FINAL", r.url, "CT", r.headers.get("content-type"), "BYTES", len(r.content), flush=True)
        raw = r.content
        text = None
        for enc in (r.apparent_encoding, "gb18030", "gbk", "utf-8"):
            if not enc:
                continue
            try:
                text = raw.decode(enc)
                print("ENC", enc, flush=True)
                break
            except Exception:
                continue
        if text is None:
            text = raw.decode("utf-8", errors="replace")
        hits = []
        for m in re.finditer(r'<a\b[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', text, flags=re.I | re.S):
            href = unescape(m.group(1))
            title = re.sub(r"<[^>]+>", "", unescape(m.group(2)))
            title = re.sub(r"\s+", " ", title).strip()
            if "时代万恒" in title or "辽宁时代" in title or "600241" in title:
                hits.append((title, urljoin(r.url, href)))
        print("HITS", len(hits), hits, flush=True)
        for title, detail in hits:
            try:
                d = s.get(detail, headers=headers, timeout=40, allow_redirects=True)
                print("DETAIL", title, detail, "STATUS", d.status_code, "FINAL", d.url, "CT", d.headers.get("content-type"), "BYTES", len(d.content), flush=True)
                dr = d.content
                dt = None
                for enc in (d.apparent_encoding, "gb18030", "gbk", "utf-8"):
                    if not enc:
                        continue
                    try:
                        dt = dr.decode(enc)
                        print("DETAIL_ENC", enc, flush=True)
                        break
                    except Exception:
                        continue
                if dt is None:
                    dt = dr.decode("utf-8", errors="replace")
                for pat in (r'https?://[^"\'<> ]+\.pdf[^"\'<> ]*', r'href=["\']([^"\']*(?:down|download|pdf|report)[^"\']*)["\']'):
                    vals = re.findall(pat, dt, flags=re.I)
                    print("PATTERN", pat, "MATCHES", vals[:30], flush=True)
                print("DETAIL_HEAD", re.sub(r"\s+", " ", dt[:5000]), flush=True)
            except Exception as exc:
                print("DETAIL_ERROR", detail, repr(exc), flush=True)
    except Exception as exc:
        print("ERROR", url, repr(exc), flush=True)

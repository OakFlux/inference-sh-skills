from __future__ import annotations

import html
import json
import re
from urllib.parse import urljoin, urlparse

import requests

IDS = ["4660212", "4274904", "4653227"]
S = requests.Session()
S.trust_env = False
H = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/155 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

for doc_id in IDS:
    for endpoint in (f"https://www.fxbaogao.com/detail/{doc_id}", f"https://www.fxbaogao.com/view?id={doc_id}"):
        print("\n\n===", endpoint, "===", flush=True)
        try:
            r = S.get(endpoint, headers=H, timeout=120, allow_redirects=True)
        except Exception as exc:
            print("ERROR", repr(exc), flush=True)
            continue
        r.encoding = r.apparent_encoding or "utf-8"
        text = r.text
        print("HTTP", r.status_code, r.headers.get("content-type"), len(r.content), r.url, r.encoding, flush=True)
        title = re.search(r"<title[^>]*>(.*?)</title>", text, re.I | re.S)
        print("TITLE", html.unescape(re.sub(r"<[^>]+>", "", title.group(1))).strip() if title else "", flush=True)
        print("HTML_HEAD", re.sub(r"\s+", " ", text[:5000])[:5000], flush=True)

        # Extract every image/source-like URL and every obvious API/file URL.
        urls: list[str] = []
        attrs = r'(?:src|href|data-src|data-url|data-file|data-pdf|content)\s*=\s*["\']([^"\']+)["\']'
        for m in re.finditer(attrs, text, re.I):
            value = html.unescape(m.group(1)).strip()
            if not value or value.startswith(("javascript:", "#")):
                continue
            urls.append(urljoin(r.url, value))
        for m in re.finditer(r'https?://[^\s"\'<>]+', text, re.I):
            urls.append(html.unescape(m.group(0)).rstrip(");,]}\\"))
        urls = list(dict.fromkeys(urls))
        selected = []
        for u in urls:
            low = u.lower()
            if any(k in low for k in (
                "report-image", ".png", ".jpg", ".jpeg", ".webp", ".pdf",
                "api", "detail", "view", "download", "file", "document",
                "oss", "cos", "page", "docid", doc_id,
            )):
                selected.append(u)
        print("SELECTED_URLS", json.dumps(selected[:1000], ensure_ascii=False), flush=True)

        scripts = [u for u in urls if urlparse(u).path.lower().endswith((".js", ".mjs"))]
        print("SCRIPTS", json.dumps(scripts, ensure_ascii=False), flush=True)

        for pattern in [doc_id, "report-image", "pageCount", "page_count", "totalPage", "total_page", "pages", "imageList", "images", "pdf", "download", "api/", "view", "__NEXT_DATA__"]:
            positions = [m.start() for m in re.finditer(re.escape(pattern), text, re.I)]
            print("COUNT", pattern, len(positions), flush=True)
            for pos in positions[:12]:
                snippet = re.sub(r"\s+", " ", text[max(0, pos-1000):pos+2500])
                print("SNIP", pattern, snippet[:3500], flush=True)

        # Read relevant JS for API route strings.
        for script_url in scripts:
            low = script_url.lower()
            if not any(k in low for k in ("view", "detail", "app", "main", "chunk", "report")):
                continue
            try:
                sr = S.get(script_url, headers={**H, "Referer": r.url}, timeout=120)
                print("SCRIPT_HTTP", sr.status_code, len(sr.content), sr.url, flush=True)
                st = sr.text
                for pattern in ["report-image", "pageCount", "totalPage", "imageList", "download", "pdf", "/api/", "docId", "view?id"]:
                    pos_list = [m.start() for m in re.finditer(re.escape(pattern), st, re.I)]
                    if pos_list:
                        print("SCRIPT_COUNT", pattern, len(pos_list), script_url, flush=True)
                        for pos in pos_list[:10]:
                            snip = re.sub(r"\s+", " ", st[max(0,pos-1000):pos+2500])
                            print("SCRIPT_SNIP", pattern, snip[:3500], flush=True)
            except Exception as exc:
                print("SCRIPT_ERROR", script_url, repr(exc), flush=True)

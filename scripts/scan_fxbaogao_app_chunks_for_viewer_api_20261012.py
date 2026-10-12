from __future__ import annotations

import json
import re

import requests

URLS = [
    "https://www.fxbaogao.com/_fxbg/2610081742/js/runtime.465a9e213aeef458f5ed.js",
    "https://www.fxbaogao.com/_fxbg/2610081742/js/vendors~app-pages-fxbg-main-js.a8a85051eeedf9517354.chunk.js",
    "https://www.fxbaogao.com/_fxbg/2610081742/js/app-pages-fxbg-main-js.0aed1db6b40b47cce683.chunk.js",
]
S = requests.Session()
S.trust_env = False
H = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/155 Safari/537.36",
    "Referer": "https://www.fxbaogao.com/view?id=4653227",
}
NEEDLES = [
    "report-image", "pageCount", "totalPage", "imageList", "download",
    "pdf", "/api/", "docId", "reportId", "view?id", "getReport",
    "document", "preview", "original", "sourceUrl", "fileUrl", "url:",
]
for url in URLS:
    try:
        r = S.get(url, headers=H, timeout=(15, 45), allow_redirects=True)
        text = r.text
        found = {}
        for needle in NEEDLES:
            positions = [m.start() for m in re.finditer(re.escape(needle), text, re.I)]
            if positions:
                found[needle] = [
                    re.sub(r"\s+", " ", text[max(0, p-500):p+1300])[:1800]
                    for p in positions[:8]
                ]
        # Also collect URL-like and endpoint-like strings containing relevant keywords.
        strings = re.findall(r'["\']([^"\']{3,300})["\']', text)
        candidates = []
        for s in strings:
            low = s.lower()
            if any(k in low for k in ("report", "document", "preview", "download", "pdf", "image", "/api/", "page")):
                candidates.append(s)
        print("CHUNK", json.dumps({
            "url": url,
            "status": r.status_code,
            "bytes": len(r.content),
            "found": found,
            "candidate_strings": list(dict.fromkeys(candidates))[:300],
        }, ensure_ascii=False), flush=True)
    except Exception as exc:
        print("CHUNK_ERROR", json.dumps({"url": url, "error": repr(exc)}, ensure_ascii=False), flush=True)

from __future__ import annotations

import json
import re
import requests
from urllib.parse import urljoin

URLS = [
    "https://www.hibor.com.cn/docdetail_101662.html",
    "https://www.hibor.com.cn/docdetail_1759886.html",
    "https://www.sdyanbao.com/detail/104332",
    "https://www.sdyanbao.com/detail/939202",
    "https://www.sdyanbao.com/detail/939857",
]

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/152 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
})

for url in URLS:
    try:
        r = session.get(url, timeout=(20, 90), allow_redirects=True)
        print("PAGE", url, "status", r.status_code, "final", r.url, "type", r.headers.get("content-type"), "bytes", len(r.content), flush=True)
        text = r.text
        for pattern_name, pattern in [
            ("PDF_LINK", r'https?://[^\"\'<>\s]+\.pdf(?:\?[^\"\'<>\s]*)?'),
            ("PNG_LINK", r'https?://[^\"\'<>\s]+\.png(?:\?[^\"\'<>\s]*)?'),
            ("HREF", r'href=[\"\']([^\"\']+)[\"\']'),
            ("SRC", r'src=[\"\']([^\"\']+)[\"\']'),
        ]:
            values = []
            for m in re.finditer(pattern, text, flags=re.I):
                value = m.group(1) if m.lastindex else m.group(0)
                if value.startswith("/"):
                    value = urljoin(r.url, value)
                if value not in values:
                    values.append(value)
            print(pattern_name, json.dumps(values[:80], ensure_ascii=False), flush=True)
        for key in ["page_url", "share_url", "data_source_uuid", "original_id", "page_count", "file_size", "download", "docid", "reportid"]:
            matches = re.findall(rf'{key}[^\n\r]{{0,180}}', text, flags=re.I)
            if matches:
                print("KEY", key, json.dumps(matches[:10], ensure_ascii=False), flush=True)
        print("TEXT_PREFIX", re.sub(r"\s+", " ", text)[:2500], flush=True)
    except Exception as exc:
        print("ERROR", url, repr(exc), flush=True)

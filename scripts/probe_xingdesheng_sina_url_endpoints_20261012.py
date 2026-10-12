from __future__ import annotations

import hashlib
import json
from pathlib import Path

import requests

REPORT_IDS = [
    "788464099552",
    "788430748152",
    "763549027077",
    "762789035848",
]

session = requests.Session()
session.trust_env = False
headers = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/155 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Referer": "https://finance.sina.com.cn/realstock/company/sh603344/nc.shtml",
}

for report_id in REPORT_IDS:
    endpoint = (
        "https://stock.finance.sina.com.cn/stock/go.php/"
        f"vReport_Show/kind/search/rptid/{report_id}/url"
    )
    print("\n===", report_id, "===", flush=True)
    first = session.get(endpoint, headers=headers, timeout=90, allow_redirects=False)
    print(
        "NO_REDIRECT",
        first.status_code,
        first.headers.get("content-type"),
        first.headers.get("location"),
        len(first.content),
        first.url,
        flush=True,
    )
    try:
        final = session.get(endpoint, headers=headers, timeout=180, allow_redirects=True)
        print(
            "FINAL",
            final.status_code,
            final.headers.get("content-type"),
            len(final.content),
            final.url,
            flush=True,
        )
        print("HISTORY", json.dumps([
            {
                "status": item.status_code,
                "url": item.url,
                "location": item.headers.get("location"),
                "content_type": item.headers.get("content-type"),
                "bytes": len(item.content),
            }
            for item in final.history
        ], ensure_ascii=False), flush=True)
        print("HEAD", repr(final.content[:200]), flush=True)
        if final.content.startswith(b"%PDF") and len(final.content) > 100_000:
            path = Path(f"sina_{report_id}.pdf")
            path.write_bytes(final.content)
            print(
                "SAVED_PDF",
                path.name,
                path.stat().st_size,
                hashlib.sha256(path.read_bytes()).hexdigest(),
                flush=True,
            )
    except Exception as exc:
        print("FINAL_ERROR", repr(exc), flush=True)

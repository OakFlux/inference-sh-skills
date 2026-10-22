#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urljoin

import requests

OUT = Path("diag_wuhan_fingu")
OUT.mkdir(parents=True, exist_ok=True)
SESSION = requests.Session()
SESSION.trust_env = False
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/155.0.0.0 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
})

URLS = [
    "https://www.sgpjbg.com/baogao/16990.html",
    "https://bg.sgpjbg.com/baogao/16990.html",
    "https://www.sgpjbg.com/bgdown/16990.html",
    "https://bg.sgpjbg.com/bgdown/16990.html",
    "https://www.sgpjbg.com/zhuanti/hefanyiyaobaogao.html",
    "https://www.sgpjbg.com/search.html?keyword=%E6%AD%A6%E6%B1%89%E5%87%A1%E8%B0%B7",
    "https://www.9fzt.com/detail/sz_002194_10_650430884853.html",
    "https://webf10.gw.com.cn/SZ/B16/SZ002194_B16.html",
    "https://stock.finance.sina.com.cn/stock/go.php/vReport_List/kind/search/index.phtml?symbol=sz002194",
    "https://vip.stock.finance.sina.com.cn/q/go.php/vReport_List/kind/search/index.phtml?symbol=sz002194",
    "https://stock.finance.sina.com.cn/stock/go.php/vReport_List/kind/search/index.phtml?stockid=002194",
    "https://vip.stock.finance.sina.com.cn/q/go.php/vReport_List/kind/search/index.phtml?stockid=002194",
    "https://www.hibor.com.cn/search?key=%E6%AD%A6%E6%B1%89%E5%87%A1%E8%B0%B7",
]

records = []
for idx, url in enumerate(URLS, start=1):
    rec = {"url": url}
    try:
        response = SESSION.get(url, timeout=(20, 120), allow_redirects=True)
        rec.update({
            "status": response.status_code,
            "final_url": response.url,
            "content_type": response.headers.get("content-type"),
            "content_length": response.headers.get("content-length"),
            "bytes": len(response.content),
            "history": [{"status": x.status_code, "url": x.url, "location": x.headers.get("location")} for x in response.history],
        })
        suffix = ".pdf" if response.content[:5] == b"%PDF-" else ".html"
        out = OUT / f"{idx:02d}{suffix}"
        out.write_bytes(response.content)
        rec["saved"] = str(out)
        if suffix == ".html":
            text = response.text
            hrefs = []
            for raw in re.findall(r'''(?:href|src|action)\s*=\s*["']([^"']+)["']''', text, re.I):
                absolute = urljoin(response.url, raw)
                if any(token in absolute.lower() for token in ("pdf", "down", "download", "baogao", "report", "rpt", "002194", "16990")):
                    hrefs.append(absolute)
            strings = sorted(set(re.findall(r'https?://[^"\'<>\s)]+', text)))
            rec["interesting_hrefs"] = sorted(set(hrefs))[:500]
            rec["absolute_urls"] = [x for x in strings if any(t in x.lower() for t in ("pdf", "down", "report", "baogao", "002194", "16990"))][:500]
            rec["title_hits"] = [line.strip() for line in text.splitlines() if any(t in line for t in ("武汉凡谷", "专注基站射频", "三季报点评", "首次覆盖"))][:200]
        print(json.dumps(rec, ensure_ascii=False), flush=True)
    except Exception as exc:
        rec["error"] = repr(exc)
        print(json.dumps(rec, ensure_ascii=False), flush=True)
    records.append(rec)

(OUT / "summary.json").write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")

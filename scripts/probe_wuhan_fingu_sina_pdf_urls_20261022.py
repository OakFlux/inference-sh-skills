#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urljoin

import requests

OUT = Path("probe_wuhan_fingu_sina_pdf_urls")
OUT.mkdir(parents=True, exist_ok=True)
S = requests.Session()
S.trust_env = False
S.headers.update({
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/155.0.0.0 Safari/537.36",
    "Accept": "application/pdf,text/html,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
})

CANDIDATES = [
    ("650430884853", "海通证券_专注基站射频三十年"),
    ("607639534009", "财通证券_立足陶瓷滤波器"),
    ("455115656422", "招商证券_受益4G订单饱满"),
    ("445966199370", "华创证券_行业景气带来业绩释放"),
    ("393600427890", "平安证券_市场份额有望企稳"),
]

records = []
for rptid, label in CANDIDATES:
    detail = f"https://stock.finance.sina.com.cn/stock/go.php/vReport_Show/kind/search/rptid/{rptid}/index.phtml"
    endpoint = f"https://stock.finance.sina.com.cn/stock/go.php/vReport_Show/kind/search/rptid/{rptid}/url"
    rec = {"rptid": rptid, "label": label, "detail": detail, "endpoint": endpoint}
    try:
        r0 = S.get(endpoint, headers={"Referer": detail}, timeout=(20, 120), allow_redirects=False)
        rec["no_redirect"] = {
            "status": r0.status_code,
            "headers": dict(r0.headers),
            "bytes": len(r0.content),
            "head_hex": r0.content[:64].hex(),
            "text_head": r0.text[:500] if "text" in (r0.headers.get("content-type") or "").lower() else "",
        }
        print("NO_REDIRECT", json.dumps(rec["no_redirect"], ensure_ascii=False), flush=True)
        r0.close()
    except Exception as exc:
        rec["no_redirect_error"] = repr(exc)

    try:
        r = S.get(endpoint, headers={"Referer": detail}, timeout=(20, 240), allow_redirects=True)
        content = r.content
        content_type = r.headers.get("content-type") or ""
        suffix = ".pdf" if content.startswith(b"%PDF-") else ".bin"
        saved = OUT / f"{rptid}_{label}{suffix}"
        saved.write_bytes(content)
        rec["redirect"] = {
            "status": r.status_code,
            "url": r.url,
            "history": [{"status": h.status_code, "url": h.url, "location": h.headers.get("location")} for h in r.history],
            "headers": dict(r.headers),
            "bytes": len(content),
            "head_hex": content[:64].hex(),
            "saved": str(saved),
        }
        if not content.startswith(b"%PDF-"):
            text = content.decode(r.encoding or "utf-8", errors="replace")
            rec["redirect"]["text_head"] = text[:2000]
            rec["redirect"]["interesting_urls"] = sorted(set(
                urljoin(r.url, x) for x in re.findall(r'''(?:href|src|action)\s*=\s*["']([^"']+)["']''', text, re.I)
                if any(t in x.lower() for t in ("pdf", "download", "report", "rpt"))
            ))[:100]
        print("REDIRECT", json.dumps(rec["redirect"], ensure_ascii=False), flush=True)
        r.close()
    except Exception as exc:
        rec["redirect_error"] = repr(exc)
    records.append(rec)

(OUT / "summary.json").write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")

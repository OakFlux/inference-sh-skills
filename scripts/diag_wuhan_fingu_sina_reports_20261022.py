#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urljoin

import requests

OUT = Path("diag_wuhan_fingu_sina")
OUT.mkdir(parents=True, exist_ok=True)
SESSION = requests.Session()
SESSION.trust_env = False
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/155.0.0.0 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
})


def decode_response(resp: requests.Response) -> str:
    for enc in [resp.encoding, "gb18030", "gbk", "utf-8"]:
        if not enc:
            continue
        try:
            return resp.content.decode(enc)
        except Exception:
            pass
    return resp.content.decode("utf-8", errors="replace")


def fetch(url: str, name: str) -> tuple[requests.Response, str]:
    resp = SESSION.get(url, timeout=(20, 120), allow_redirects=True)
    text = decode_response(resp)
    (OUT / name).write_bytes(resp.content)
    print("FETCH", resp.status_code, len(resp.content), resp.url, flush=True)
    return resp, text

list_urls = [
    "https://stock.finance.sina.com.cn/stock/go.php/vReport_List/kind/search/index.phtml?t1=2&symbol=sz002194",
    "https://stock.finance.sina.com.cn/stock/go.php/vReport_List/kind/search/index.phtml?t1=2&symbol=002194",
    "https://stock.finance.sina.com.cn/stock/go.php/vReport_List/kind/search/index.phtml?t1=5&title=%CE%E4%BA%BA%B7%B2%B9%C8",
]

results = []
report_links: dict[str, dict] = {}
for i, url in enumerate(list_urls, start=1):
    try:
        resp, text = fetch(url, f"list_{i}.html")
        rec = {"url": url, "status": resp.status_code, "final_url": resp.url, "bytes": len(resp.content)}
        # table row extraction, tolerant to legacy HTML
        row_pattern = re.compile(
            r'<tr[^>]*>.*?<a[^>]+title="([^"]+)"[^>]+href="([^"]*vReport_Show[^"]+)"[^>]*>.*?</a>.*?'
            r'<td>([^<]*)</td>.*?<div class="fname05"><span>([^<]*)</span></div>.*?'
            r'<div class="fname"><span>([^<]*)</span></div>.*?</tr>',
            re.I | re.S,
        )
        parsed = []
        for title, href, date_or_type, institution, analyst in row_pattern.findall(text):
            absolute = urljoin(resp.url, href)
            rptid_match = re.search(r'/rptid/(\d+)/', absolute)
            rptid = rptid_match.group(1) if rptid_match else ""
            item = {
                "title": re.sub(r"\s+", " ", title).strip(),
                "url": absolute,
                "rptid": rptid,
                "date_or_type": re.sub(r"\s+", " ", date_or_type).strip(),
                "institution": re.sub(r"\s+", " ", institution).strip(),
                "analyst": re.sub(r"\s+", " ", analyst).strip(),
            }
            parsed.append(item)
            if rptid:
                report_links[rptid] = item
        # simpler extraction fallback
        for title, href in re.findall(r'<a[^>]+title="([^"]+)"[^>]+href="([^"]*vReport_Show[^"]+)"', text, re.I):
            absolute = urljoin(resp.url, href)
            m = re.search(r'/rptid/(\d+)/', absolute)
            if m and m.group(1) not in report_links:
                report_links[m.group(1)] = {"title": re.sub(r"\s+", " ", title).strip(), "url": absolute, "rptid": m.group(1)}
        rec["parsed"] = parsed
        rec["wuhan_hits"] = [line.strip() for line in text.splitlines() if any(k in line for k in ("武汉凡谷", "002194", "专注基站射频", "Q3业绩", "盈利能力大幅提升", "新周期开启"))][:100]
        rec["pagination"] = sorted(set(urljoin(resp.url, x) for x in re.findall(r'href="([^"]+)"', text, re.I) if any(t in x for t in ("page=", "p=", "pageNo="))))[:100]
        results.append(rec)
        print(json.dumps(rec, ensure_ascii=False), flush=True)
    except Exception as exc:
        results.append({"url": url, "error": repr(exc)})
        print("LIST_ERROR", url, repr(exc), flush=True)

# Fetch every report detail found in the properly filtered list.
details = []
for idx, (rptid, meta) in enumerate(report_links.items(), start=1):
    try:
        resp, text = fetch(meta["url"], f"detail_{idx}_{rptid}.html")
        hrefs = sorted(set(urljoin(resp.url, raw) for raw in re.findall(r'(?:href|src|action)\s*=\s*["\']([^"\']+)["\']', text, re.I)))
        interesting = [x for x in hrefs if any(t in x.lower() for t in ("pdf", "down", "download", "rptid", "report"))]
        absolute_urls = sorted(set(re.findall(r'https?://[^"\'<>\s)]+', text)))
        interesting += [x for x in absolute_urls if any(t in x.lower() for t in ("pdf", "down", "download", "rptid", "report"))]
        rec = {
            **meta,
            "status": resp.status_code,
            "final_url": resp.url,
            "bytes": len(resp.content),
            "interesting_urls": sorted(set(interesting))[:200],
            "pdf_text_hits": [line.strip() for line in text.splitlines() if any(k in line for k in ("PDF", "pdf", "下载", "查看原文", "武汉凡谷"))][:200],
        }
        details.append(rec)
        print("DETAIL", json.dumps(rec, ensure_ascii=False), flush=True)
    except Exception as exc:
        rec = {**meta, "error": repr(exc)}
        details.append(rec)
        print("DETAIL_ERROR", json.dumps(rec, ensure_ascii=False), flush=True)

(OUT / "summary.json").write_text(json.dumps({"lists": results, "details": details}, ensure_ascii=False, indent=2), encoding="utf-8")

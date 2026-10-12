from __future__ import annotations

import html
import json
import re
from urllib.parse import urljoin

import requests

IDS = ["4660212", "4653227", "4274904"]
S = requests.Session()
S.trust_env = False
H = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/155 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

for doc_id in IDS:
    result = {"id": doc_id, "pages": []}
    for kind, url in (
        ("detail", f"https://www.fxbaogao.com/detail/{doc_id}"),
        ("view", f"https://www.fxbaogao.com/view?id={doc_id}"),
    ):
        try:
            r = S.get(url, headers=H, timeout=90, allow_redirects=True)
            r.encoding = r.apparent_encoding or "utf-8"
            text = r.text
            item = {
                "kind": kind,
                "status": r.status_code,
                "content_type": r.headers.get("content-type"),
                "bytes": len(r.content),
                "final_url": r.url,
            }
            title = re.search(r"<title[^>]*>(.*?)</title>", text, re.I | re.S)
            item["title"] = html.unescape(re.sub(r"<[^>]+>", "", title.group(1))).strip() if title else ""

            urls = []
            for m in re.finditer(r'https?://[^\s"\'<>]+', text, re.I):
                u = html.unescape(m.group(0)).rstrip(");,]}\\")
                if "report-image" in u.lower() or ".pdf" in u.lower():
                    urls.append(u)
            for m in re.finditer(r'(?:src|href|data-src|data-url|data-file|data-pdf)\s*=\s*["\']([^"\']+)["\']', text, re.I):
                u = urljoin(r.url, html.unescape(m.group(1)))
                if "report-image" in u.lower() or ".pdf" in u.lower():
                    urls.append(u)
            item["asset_urls"] = list(dict.fromkeys(urls))[:50]

            page_counts = []
            patterns = [
                r'"(?:pageCount|page_count|totalPage|total_page|pages)"\s*:\s*"?(\d+)',
                r'(?:pageCount|page_count|totalPage|total_page|pages)\s*[=:]\s*"?(\d+)',
                r'共\s*(\d+)\s*页',
            ]
            for pat in patterns:
                page_counts += [int(x) for x in re.findall(pat, text, re.I)]
            item["page_count_candidates"] = sorted(set(x for x in page_counts if 1 <= x <= 500))

            # Compact context around asset path and any page-count fields.
            snippets = []
            for token in ("report-image", "pageCount", "totalPage", "imageList", "__NEXT_DATA__"):
                pos = text.find(token)
                if pos >= 0:
                    snippets.append(re.sub(r"\s+", " ", text[max(0, pos-250):pos+700])[:950])
            item["snippets"] = snippets[:10]
            result["pages"].append(item)
        except Exception as exc:
            result["pages"].append({"kind": kind, "error": repr(exc)})

    # Probe only assets explicitly exposed by the public pages.
    explicit_assets = []
    for page in result["pages"]:
        explicit_assets.extend(page.get("asset_urls", []))
    probes = []
    for asset in list(dict.fromkeys(explicit_assets))[:15]:
        try:
            rr = S.get(asset, headers={**H, "Referer": f"https://www.fxbaogao.com/view?id={doc_id}"}, timeout=90, allow_redirects=True)
            probes.append({
                "url": asset,
                "status": rr.status_code,
                "content_type": rr.headers.get("content-type"),
                "bytes": len(rr.content),
                "head": rr.content[:12].hex(),
            })
        except Exception as exc:
            probes.append({"url": asset, "error": repr(exc)})
    result["asset_probes"] = probes
    print("RESULT", json.dumps(result, ensure_ascii=False), flush=True)

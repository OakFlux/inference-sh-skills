from __future__ import annotations

import html
import json
import re
from urllib.parse import urljoin

import requests

SESSION = requests.Session()
SESSION.trust_env = False
HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/152 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Accept": "text/html,application/pdf,application/octet-stream;q=0.9,*/*;q=0.8",
}

for rptid in ("650127406222", "649940413902"):
    detail = f"https://stock.finance.sina.com.cn/stock/go.php/vReport_Show/kind/search/rptid/{rptid}/index.phtml"
    detail_response = SESSION.get(detail, headers=HEADERS, timeout=60, allow_redirects=True)
    detail_response.encoding = detail_response.apparent_encoding or detail_response.encoding or "gbk"
    detail_text = detail_response.text
    title_match = re.search(r"<title[^>]*>(.*?)</title>", detail_text, re.I | re.S)
    title = html.unescape(re.sub(r"<[^>]+>", "", title_match.group(1)).strip()) if title_match else ""
    detail_urls = []
    for match in re.finditer(
        r'''(?:href|src|action|data-url|data-href)\s*=\s*["']([^"']+)["']''',
        detail_text,
        re.I,
    ):
        candidate = urljoin(str(detail_response.url), html.unescape(match.group(1)))
        if any(token in candidate.lower() for token in ("pdf", "download", "vreport_show", "file.finance")):
            detail_urls.append(candidate)

    endpoint = f"https://stock.finance.sina.com.cn/stock/go.php/vReport_Show/kind/search/rptid/{rptid}/url"
    endpoint_headers = dict(HEADERS)
    endpoint_headers["Referer"] = detail
    endpoint_response = SESSION.get(endpoint, headers=endpoint_headers, timeout=60, allow_redirects=True)
    endpoint_response.encoding = endpoint_response.apparent_encoding or endpoint_response.encoding or "gbk"
    endpoint_text = endpoint_response.text if not endpoint_response.content.startswith(b"%PDF-") else ""
    endpoint_urls = []
    if endpoint_text:
        patterns = [
            r'''(?:href|src|action|data-url|data-href)\s*=\s*["']([^"']+)["']''',
            r'''(?:window\.)?location(?:\.href)?\s*=\s*["']([^"']+)["']''',
            r'''https?://[^\s"'<>]+''',
        ]
        for pattern in patterns:
            for match in re.finditer(pattern, endpoint_text, re.I):
                raw = match.group(1) if match.lastindex else match.group(0)
                candidate = urljoin(str(endpoint_response.url), html.unescape(raw))
                if any(token in candidate.lower() for token in ("pdf", "download", "vreport_show", "file.finance", "report")):
                    endpoint_urls.append(candidate)
    clean_endpoint = html.unescape(
        re.sub(
            r"\s+",
            " ",
            re.sub(
                r"<[^>]+>",
                " ",
                re.sub(r"<script.*?</script>|<style.*?</style>", " ", endpoint_text, flags=re.I | re.S),
            ),
        )
    )
    output = {
        "rptid": rptid,
        "detail": {
            "status": detail_response.status_code,
            "final_url": str(detail_response.url),
            "content_type": detail_response.headers.get("content-type"),
            "bytes": len(detail_response.content),
            "title": title,
            "relevant_urls": list(dict.fromkeys(detail_urls)),
        },
        "url_endpoint": {
            "status": endpoint_response.status_code,
            "final_url": str(endpoint_response.url),
            "content_type": endpoint_response.headers.get("content-type"),
            "bytes": len(endpoint_response.content),
            "pdf_header": endpoint_response.content.startswith(b"%PDF-"),
            "history": [
                {
                    "status": item.status_code,
                    "url": str(item.url),
                    "location": item.headers.get("location"),
                }
                for item in endpoint_response.history
            ],
            "relevant_urls": list(dict.fromkeys(endpoint_urls)),
            "clean_text_head": clean_endpoint[:5000],
            "raw_head": endpoint_text[:5000],
        },
    }
    print("RESULT_JSON", json.dumps(output, ensure_ascii=False, indent=2), flush=True)

from __future__ import annotations

import html
import json
import re
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

URLS = [
    "https://www.9fzt.com/detail/sz_001391_10_820515916583.html",
    "https://www.futunn.com/stock/001391-SZ/institutional-ratings",
    "https://www.baogaobox.com/insights/260106000024574.html",
    "https://www.nxny.com/report/view_6187299.html",
]
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
}
OUT = Path("air_china_cargo_zhejiang_source_inventory.json")


def extract_candidates(text: str, base_url: str) -> list[str]:
    decoded = html.unescape(text).replace("\\/", "/")
    patterns = [
        r'https?://[^\s"\'<>]+',
        r'(?i)(?:src|href|url|pdfUrl|fileUrl|downloadUrl|attachmentUrl)["\']?\s*[:=]\s*["\']([^"\']+)',
    ]
    candidates: list[str] = []
    for pattern in patterns:
        for match in re.findall(pattern, decoded):
            value = match if isinstance(match, str) else match[0]
            value = value.rstrip(",);]}\\")
            if value.startswith("//"):
                value = "https:" + value
            elif value.startswith("/"):
                value = urljoin(base_url, value)
            if any(token in value.lower() for token in ("pdf", "report", "download", "attachment", "file", "document", "820515916583", "6187299", "001391")):
                candidates.append(value)
    soup = BeautifulSoup(text, "html.parser")
    for tag in soup.find_all(["a", "script", "iframe", "link"]):
        for attr in ("href", "src", "data-url", "data-src", "data-href", "data-pdf"):
            value = tag.get(attr)
            if not value:
                continue
            value = urljoin(base_url, value)
            if any(token in value.lower() for token in ("pdf", "report", "download", "attachment", "file", "document", "820515916583", "6187299", "001391")):
                candidates.append(value)
    return sorted(set(candidates))


def main() -> None:
    session = requests.Session()
    session.headers.update(HEADERS)
    output = []
    for url in URLS:
        try:
            response = session.get(url, timeout=120, allow_redirects=True)
            text = response.text
            record = {
                "url": url,
                "final_url": response.url,
                "status": response.status_code,
                "bytes": len(response.content),
                "content_type": response.headers.get("content-type"),
                "headers": dict(response.headers),
                "title": "",
                "candidates": extract_candidates(text, response.url),
                "text_prefix": text[:5000],
            }
            soup = BeautifulSoup(text, "html.parser")
            if soup.title:
                record["title"] = soup.title.get_text(" ", strip=True)
            output.append(record)
            print("PAGE", json.dumps({k: record[k] for k in ("url", "final_url", "status", "bytes", "content_type", "title")}, ensure_ascii=False), flush=True)
            for candidate in record["candidates"]:
                print("CANDIDATE", candidate, flush=True)
            for token in ("820515916583", "6187299", "跨境电商方兴未艾", "李丹", "李逸", ".pdf", "download"):
                positions = [m.start() for m in re.finditer(re.escape(token), text, re.I)]
                for pos in positions[:10]:
                    excerpt = text[max(0, pos - 500):pos + 1000]
                    print("EXCERPT", token, json.dumps(excerpt, ensure_ascii=False), flush=True)
        except Exception as exc:
            output.append({"url": url, "error": repr(exc)})
            print("ERROR", url, repr(exc), flush=True)
    OUT.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print("WROTE", OUT, OUT.stat().st_size, flush=True)


if __name__ == "__main__":
    main()

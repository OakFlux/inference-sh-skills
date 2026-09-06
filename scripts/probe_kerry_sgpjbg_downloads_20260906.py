#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/151.0.0.0 Safari/537.36"
BASE = "https://www.sgpjbg.com"
OUT = Path("kerry-sgpjbg-download-probe")
OUT.mkdir(exist_ok=True)
REPORTS = {
    "613527": "2025-02-18_29p",
    "959322": "2025-11-05_35p",
    "1122678": "2026-02-09_28p",
}

s = requests.Session()
s.headers.update({
    "User-Agent": UA,
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
    "Accept": "text/html,application/xhtml+xml,application/pdf,application/octet-stream;q=0.9,*/*;q=0.8",
})


def decode(r: requests.Response) -> str:
    for enc in (r.encoding, r.apparent_encoding, "utf-8", "gb18030"):
        if not enc:
            continue
        try:
            text = r.content.decode(enc)
            if text.count("�") < 10:
                return text
        except Exception:
            pass
    return r.content.decode("utf-8", errors="replace")


def inspect_response(label: str, r: requests.Response) -> dict:
    rec = {
        "label": label,
        "requested": r.request.url,
        "resolved": r.url,
        "status": r.status_code,
        "type": r.headers.get("content-type"),
        "length": r.headers.get("content-length"),
        "disposition": r.headers.get("content-disposition"),
        "bytes": len(r.content),
        "head": r.content[:20].hex(),
        "history": [(x.status_code, x.url, x.headers.get("location")) for x in r.history],
    }
    print("RESPONSE", json.dumps(rec, ensure_ascii=False), flush=True)
    return rec


def extract_candidates(html: str, page_url: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    values: list[str] = []
    for tag in soup.find_all(True):
        for attr in (
            "href", "src", "data-src", "data-original", "data-url", "data-file", "data-pdf",
            "data-download", "data-href", "data-link", "content", "value", "action",
        ):
            value = tag.get(attr)
            if isinstance(value, str) and value.strip():
                values.append(value.strip())
    patterns = [
        r"(?:https?:)?//[^\s\"'<>\\]+",
        r"/(?:bgdown|download|downloads|file|files|pdf|preview|api|document|doc|attachment|source|view|fileroot)[^\s\"'<>\\]*",
    ]
    for pattern in patterns:
        values.extend(re.findall(pattern, html, flags=re.I))
    candidates = []
    seen = set()
    for raw in values:
        raw = raw.replace("\\/", "/").rstrip("),]};'\"")
        u = urljoin(page_url, raw)
        low = u.lower()
        if len(u) > 1200 or u in seen:
            continue
        seen.add(u)
        if any(k in low for k in (".pdf", "bgdown", "download", "fileroot", "file.sgpjbg", "cache.sgpjbg", "/api/")):
            candidates.append(u)
    return candidates


def get(url: str, referer: str | None = None, accept_pdf: bool = False) -> requests.Response:
    headers = {
        "User-Agent": UA,
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
        "Accept": "application/pdf,application/octet-stream;q=0.9,*/*;q=0.8" if accept_pdf else "text/html,application/xhtml+xml,application/pdf;q=0.9,*/*;q=0.8",
    }
    if referer:
        headers["Referer"] = referer
    return s.get(url, headers=headers, timeout=(30, 300), allow_redirects=True)


def main() -> None:
    results = {}
    for report_id, stem in REPORTS.items():
        report_url = f"{BASE}/baogao/{report_id}.html"
        download_url = f"{BASE}/bgdown/{report_id}.html"
        entry = {"report_id": report_id, "report_url": report_url, "download_url": download_url, "responses": [], "candidates": [], "pdfs": []}

        page = get(report_url)
        entry["responses"].append(inspect_response(f"{stem}_page", page))
        page_text = decode(page)
        (OUT / f"{stem}_page.html").write_text(page_text, encoding="utf-8")
        candidates = extract_candidates(page_text, page.url)
        print("PAGE CANDIDATES", report_id, len(candidates), flush=True)
        for c in candidates:
            print("CANDIDATE", report_id, c, flush=True)

        down = get(download_url, referer=page.url, accept_pdf=True)
        entry["responses"].append(inspect_response(f"{stem}_bgdown", down))
        if down.status_code == 200 and down.content.startswith(b"%PDF-"):
            path = OUT / f"{stem}_bgdown.pdf"
            path.write_bytes(down.content)
            entry["pdfs"].append(str(path))
        else:
            down_text = decode(down)
            (OUT / f"{stem}_bgdown.html").write_text(down_text, encoding="utf-8")
            down_candidates = extract_candidates(down_text, down.url)
            for c in down_candidates:
                if c not in candidates:
                    candidates.append(c)
            print("DOWN CANDIDATES", report_id, len(down_candidates), flush=True)
            for c in down_candidates:
                print("CANDIDATE", report_id, c, flush=True)

        # Try only plausible public document URLs found in the page/download response.
        entry["candidates"] = candidates
        for idx, c in enumerate(candidates, 1):
            low = c.lower()
            if any(x in low for x in (".gif", ".png", ".jpg", ".jpeg", ".webp", ".css", ".js")) and ".pdf" not in low:
                # Also try replacing the preview GIF extension with PDF when this is a fileroot document URL.
                if "file.sgpjbg.com/fileroot" in low and low.endswith(".gif"):
                    alternatives = [re.sub(r"\.gif(?:\?.*)?$", ".pdf", c, flags=re.I)]
                else:
                    continue
            else:
                alternatives = [c]
            for alt in alternatives:
                try:
                    r = get(alt, referer=page.url, accept_pdf=True)
                    rec = inspect_response(f"{stem}_candidate_{idx}", r)
                    entry["responses"].append(rec)
                    if r.status_code == 200 and r.content.startswith(b"%PDF-"):
                        path = OUT / f"{stem}_candidate_{idx}.pdf"
                        path.write_bytes(r.content)
                        entry["pdfs"].append(str(path))
                        print("FOUND PDF", report_id, path, len(r.content), flush=True)
                        break
                except Exception as exc:
                    print("CANDIDATE ERROR", report_id, alt, repr(exc), flush=True)
            if entry["pdfs"]:
                break
        results[report_id] = entry

    Path("kerry-sgpjbg-download-results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()

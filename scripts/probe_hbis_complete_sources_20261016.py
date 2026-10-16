from __future__ import annotations

import json
import re
from io import BytesIO
from urllib.parse import urljoin

import requests
from PIL import Image

session = requests.Session()
session.trust_env = False
headers = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/152 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

# 1) Test the 2025 China Galaxy first-coverage report direct PDF.
pdf_url = "https://pdf.dfcfw.com/pdf/H3_AP202504151656740249_1.pdf"
r = session.get(
    pdf_url,
    headers={**headers, "Accept": "application/pdf,*/*;q=0.8", "Referer": "https://data.eastmoney.com/report/stock.jshtml"},
    timeout=120,
    allow_redirects=True,
)
print("GALAXY_PDF", r.status_code, r.url, r.headers.get("content-type"), len(r.content), r.content[:16], flush=True)

# 2) Inspect fxbaogao public full-report viewer for the 2019 GTJA first-coverage report.
view_urls = [
    "https://fxbaogao.com/view?id=1332144",
    "https://www.fxbaogao.com/view?id=1332144",
    "https://m.fxbaogao.com/view?id=1332144",
]
for view_url in view_urls:
    try:
        rr = session.get(view_url, headers=headers, timeout=120, allow_redirects=True)
    except Exception as exc:
        print("VIEW_ERROR", view_url, repr(exc), flush=True)
        continue
    print("VIEW", view_url, rr.status_code, rr.url, rr.headers.get("content-type"), len(rr.content), flush=True)
    text = rr.text
    title = re.search(r"<title[^>]*>(.*?)</title>", text, re.I | re.S)
    print("VIEW_TITLE", re.sub(r"\s+", " ", title.group(1).strip()) if title else "", flush=True)
    for key in ["__NEXT_DATA__", "report-image", "pageCount", "page_count", "totalPage", "1332144", "documentUrl", "fileUrl", "pdfUrl"]:
        idx = text.find(key)
        if idx >= 0:
            print("VIEW_CTX", key, re.sub(r"\s+", " ", text[max(0, idx-400):idx+1200]), flush=True)
    attrs = re.findall(r"(?:href|src|data-src|data-original|data-url|content)\s*=\s*[\"']([^\"']+)[\"']", text, re.I)
    shown = set()
    for value in attrs:
        full = urljoin(rr.url, value.replace("\\/", "/"))
        low = full.lower()
        if full in shown:
            continue
        if any(token in low for token in ["1332144", "report-image", ".pdf", "download", "document", "viewer", "page"]):
            shown.add(full)
            print("VIEW_ASSET", full, flush=True)

# 3) Probe sequential full-resolution report pages. Stop after a gap of 5 missing pages.
base_patterns = [
    "https://public.fxbaogao.com/report-image/2019/06/17/1332144-{n}.png",
    "https://public.fxbaogao.com/report-image/2019/06/17/1332144-{n}.jpg",
    "https://public.fxbaogao.com/report-image/2019/06/17/1332144-{n}.jpeg",
]
found = []
consecutive_missing = 0
for n in range(1, 81):
    page_found = False
    for pattern in base_patterns:
        url = pattern.format(n=n)
        try:
            pr = session.get(url, headers={**headers, "Referer": "https://fxbaogao.com/view?id=1332144"}, timeout=60, allow_redirects=True)
        except Exception as exc:
            print("PAGE_ERROR", n, url, repr(exc), flush=True)
            continue
        if pr.status_code == 200 and len(pr.content) > 5000 and pr.content[:8] in (b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff\xe0", b"\xff\xd8\xff\xe1", b"\xff\xd8\xff\xdb"):
            try:
                image = Image.open(BytesIO(pr.content))
                image.load()
                width, height = image.size
            except Exception as exc:
                print("PAGE_DECODE_ERROR", n, url, repr(exc), flush=True)
                continue
            print("PAGE_FOUND", n, url, pr.headers.get("content-type"), len(pr.content), width, height, flush=True)
            found.append({"page": n, "url": url, "bytes": len(pr.content), "width": width, "height": height, "format": image.format})
            page_found = True
            break
        elif n <= 5 or pr.status_code not in (403, 404):
            print("PAGE_MISS", n, url, pr.status_code, pr.headers.get("content-type"), len(pr.content), pr.content[:12], flush=True)
    if page_found:
        consecutive_missing = 0
    else:
        consecutive_missing += 1
        if consecutive_missing >= 5 and n > 5:
            break

print("FOUND_PAGES", json.dumps(found, ensure_ascii=False), flush=True)
print("FOUND_COUNT", len(found), "MAX_PAGE", max((x["page"] for x in found), default=0), flush=True)

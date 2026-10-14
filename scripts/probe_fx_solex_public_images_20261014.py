from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

OUT = Path("fx_solex_public_probe")
OUT.mkdir(exist_ok=True)

REPORTS = [
    {"id": 5201086, "date": "2025/12/24", "name": "国盛证券_机器人+大健康"},
    {"id": 5085249, "date": "2025/09/30", "name": "东方财富证券_智能厨卫+大健康"},
    {"id": 5077383, "date": "2025/09/26", "name": "华鑫证券_机器人新业务"},
    {"id": 4902712, "date": "2025/06/11", "name": "财通证券_IDM技术固本"},
]

session = requests.Session()
session.trust_env = False
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/155 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/png,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

results = []
for report in REPORTS:
    rid = report["id"]
    rdir = OUT / str(rid)
    rdir.mkdir(exist_ok=True)
    rec = {**report, "pages": [], "views": []}
    for view_url in [
        f"https://www.fxbaogao.com/view?id={rid}",
        f"https://www.fxbaogao.com/detail/{rid}",
        f"https://m.fxbaogao.com/detail/{rid}",
        f"https://m.fxbaogao.com/view?id={rid}",
    ]:
        try:
            response = session.get(view_url, headers=headers, timeout=(20, 120), allow_redirects=True)
            item = {"url": view_url, "status": response.status_code, "final_url": response.url,
                    "content_type": response.headers.get("content-type"), "bytes": len(response.content)}
            suffix = ".html" if "html" in (response.headers.get("content-type") or "") else ".bin"
            name = re.sub(r"[^a-zA-Z0-9]+", "_", view_url)[:100] + suffix
            (rdir / name).write_bytes(response.content)
            if suffix == ".html":
                soup = BeautifulSoup(response.text, "lxml")
                item["title"] = soup.title.get_text(" ", strip=True) if soup.title else ""
                item["assets"] = []
                for tag in soup.find_all(["script", "img", "link", "a"]):
                    u = tag.get("src") or tag.get("href")
                    if not u:
                        continue
                    absolute = urljoin(response.url, u)
                    if any(k in absolute.lower() for k in ["5201086", "5085249", "5077383", "4902712", "report-image", "pdf", "api", "view", "_next/static"]):
                        item["assets"].append(absolute)
                embedded = re.findall(r"https?://[^\"'<>\\\s]+", response.text)
                item["embedded"] = sorted(set(x for x in embedded if any(k in x.lower() for k in [str(rid), "report-image", "pdf", "api"])))[:1000]
                print("VIEW", rid, response.status_code, len(response.content), response.url, item.get("title"), flush=True)
                for asset in item["assets"][:100]:
                    print("ASSET", rid, asset, flush=True)
            else:
                print("VIEW_BIN", rid, response.status_code, len(response.content), response.url, response.headers.get("content-type"), flush=True)
            rec["views"].append(item)
        except Exception as exc:  # noqa: BLE001
            rec["views"].append({"url": view_url, "error": repr(exc)})
            print("VIEW_ERROR", rid, view_url, repr(exc), flush=True)

    # Probe likely public page-image paths. Save every actual image found.
    for page in range(1, 51):
        variants = [
            f"https://public.fxbaogao.com/report-image/{report['date']}/{rid}-{page}.png",
            f"https://public.fxbaogao.com/report-image/{report['date']}/{rid}-{page}.jpg",
            f"https://public.fxbaogao.com/report-image/{report['date']}/{rid}-{page}.jpeg",
        ]
        found = False
        for url in variants:
            try:
                response = session.get(url, headers={**headers, "Referer": f"https://www.fxbaogao.com/view?id={rid}"}, timeout=(20, 120), allow_redirects=True)
                ct = (response.headers.get("content-type") or "").lower()
                item = {"page": page, "url": url, "status": response.status_code, "final_url": response.url, "content_type": ct, "bytes": len(response.content)}
                is_image = response.status_code == 200 and ct.startswith("image/") and len(response.content) > 5000
                item["is_image"] = is_image
                rec["pages"].append(item)
                print("PAGE", rid, page, response.status_code, ct, len(response.content), url, flush=True)
                if is_image:
                    ext = ".png" if "png" in ct else ".jpg"
                    (rdir / f"page_{page:03d}{ext}").write_bytes(response.content)
                    found = True
                    break
            except Exception as exc:  # noqa: BLE001
                rec["pages"].append({"page": page, "url": url, "error": repr(exc)})
                print("PAGE_ERROR", rid, page, url, repr(exc), flush=True)
        if not found:
            # Once several consecutive pages are missing after at least one found page, stop.
            found_pages = [x["page"] for x in rec["pages"] if x.get("is_image")]
            if found_pages and page > max(found_pages) + 3:
                break
    results.append(rec)

(OUT / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

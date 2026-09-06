#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from urllib.parse import quote, urljoin

import requests
from bs4 import BeautifulSoup
from PIL import Image

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/151.0.0.0 Safari/537.36"
BASE = "https://www.fxbaogao.com"
PUBLIC = "https://public.fxbaogao.com"
OUT = Path("kerry-fxbaogao-probe")
OUT.mkdir(exist_ok=True)

REPORTS = {
    "4702606": {"date": "2025/02/18", "pages": 29, "label": "xingzheng_20250218"},
    "5263403": {"date": "2026/02/10", "pages": 28, "label": "caitong_20260210"},
}

s = requests.Session()
s.headers.update({
    "User-Agent": UA,
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
    "Referer": BASE + "/",
})


def fetch(url: str, referer: str | None = None, timeout: int = 120) -> requests.Response:
    headers = {"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7"}
    if referer:
        headers["Referer"] = referer
    return s.get(url, headers=headers, timeout=(30, timeout), allow_redirects=True)


def save_html(label: str, r: requests.Response) -> str:
    enc = r.apparent_encoding or r.encoding or "utf-8"
    try:
        text = r.content.decode(enc)
    except Exception:
        text = r.content.decode("utf-8", errors="replace")
    (OUT / f"{label}.html").write_text(text, encoding="utf-8")
    return text


def inspect_detail(report_id: str) -> dict:
    url = f"{BASE}/detail/{report_id}"
    r = fetch(url)
    text = save_html(f"detail_{report_id}", r)
    soup = BeautifulSoup(text, "html.parser")
    urls = []
    for tag in soup.find_all(True):
        for attr in ("href", "src", "data-src", "data-url", "data-image", "content"):
            value = tag.get(attr)
            if isinstance(value, str) and value.strip():
                u = urljoin(r.url, value.strip().replace("\\/", "/"))
                if u not in urls and any(k in u.lower() for k in ("report-image", "public.fxbaogao", ".png", ".jpg", ".pdf", "/api/", "search")):
                    urls.append(u)
    for value in re.findall(r"(?:https?:)?//[^\s\"'<>\\]+", text):
        u = value if value.startswith("http") else "https:" + value
        u = u.rstrip("),]};'\"")
        if u not in urls and any(k in u.lower() for k in ("report-image", "public.fxbaogao", ".png", ".jpg", ".pdf", "/api/", "search")):
            urls.append(u)
    snippets = []
    for m in re.finditer(r".{0,300}(?:report-image|public\.fxbaogao|imageUrl|image_url|pageCount|page_count|download|search).{0,700}", text, flags=re.I | re.S):
        snip = re.sub(r"\s+", " ", m.group(0))[:1300]
        if snip not in snippets:
            snippets.append(snip)
    print("DETAIL", report_id, r.status_code, r.url, r.headers.get("content-type"), len(r.content), soup.title.get_text(" ", strip=True) if soup.title else "", flush=True)
    for u in urls[:200]:
        print("DETAIL URL", report_id, u, flush=True)
    for snip in snippets[:80]:
        print("DETAIL SNIP", report_id, snip, flush=True)
    return {"status": r.status_code, "resolved": r.url, "type": r.headers.get("content-type"), "bytes": len(r.content), "title": soup.title.get_text(" ", strip=True) if soup.title else "", "urls": urls, "snippets": snippets[:80]}


def try_image_patterns(report_id: str, cfg: dict) -> dict:
    y, m, d = cfg["date"].split("/")
    patterns = [
        f"{PUBLIC}/report-image/{y}/{m}/{d}/{report_id}-{{page}}.png",
        f"{PUBLIC}/report-image/{y}/{m}/{d}/{report_id}_{{page}}.png",
        f"{PUBLIC}/report-image/{y}/{m}/{d}/{report_id}/{{page}}.png",
        f"{PUBLIC}/report-image/{y}/{m}/{d}/{report_id}-{{page}}.jpg",
    ]
    chosen = None
    probes = []
    for pattern in patterns:
        u = pattern.format(page=1)
        try:
            r = fetch(u, referer=f"{BASE}/detail/{report_id}", timeout=90)
            rec = {"url": u, "status": r.status_code, "type": r.headers.get("content-type"), "bytes": len(r.content), "head": r.content[:16].hex()}
            probes.append(rec)
            print("IMAGE PROBE", report_id, json.dumps(rec, ensure_ascii=False), flush=True)
            if r.status_code == 200 and r.content[:8] == b"\x89PNG\r\n\x1a\n":
                chosen = pattern
                break
            if r.status_code == 200 and r.content[:3] == b"\xff\xd8\xff":
                chosen = pattern
                break
        except Exception as exc:
            probes.append({"url": u, "error": repr(exc)})
    result = {"probes": probes, "chosen": chosen, "downloaded": []}
    if not chosen:
        return result
    report_dir = OUT / cfg["label"]
    report_dir.mkdir(exist_ok=True)
    for page in range(1, cfg["pages"] + 1):
        u = chosen.format(page=page)
        r = fetch(u, referer=f"{BASE}/detail/{report_id}", timeout=120)
        ext = ".png" if r.content[:8] == b"\x89PNG\r\n\x1a\n" else ".jpg" if r.content[:3] == b"\xff\xd8\xff" else ".bin"
        path = report_dir / f"{page:03d}{ext}"
        path.write_bytes(r.content)
        image_ok = False
        size = None
        if ext in (".png", ".jpg"):
            try:
                with Image.open(path) as im:
                    im.verify()
                with Image.open(path) as im:
                    size = im.size
                image_ok = True
            except Exception as exc:
                print("IMAGE VERIFY ERROR", report_id, page, repr(exc), flush=True)
        rec = {"page": page, "url": u, "status": r.status_code, "type": r.headers.get("content-type"), "bytes": len(r.content), "path": str(path), "image_ok": image_ok, "size": size}
        result["downloaded"].append(rec)
        print("IMAGE PAGE", report_id, json.dumps(rec, ensure_ascii=False), flush=True)
        time.sleep(0.08)
    return result


def inspect_search_routes() -> list[dict]:
    keyword = quote("嘉里建设")
    routes = [
        f"{BASE}/search?keyword={keyword}",
        f"{BASE}/search?key={keyword}",
        f"{BASE}/search?kw={keyword}",
        f"{BASE}/search/{keyword}",
        f"{BASE}/?keyword={keyword}",
    ]
    results = []
    for idx, url in enumerate(routes, 1):
        try:
            r = fetch(url)
            text = save_html(f"search_{idx}", r)
            soup = BeautifulSoup(text, "html.parser")
            links = []
            for a in soup.find_all("a", href=True):
                label = " ".join(a.get_text(" ", strip=True).split())
                href = urljoin(r.url, a["href"])
                if "/detail/" in href and ("嘉里建设" in label or "嘉里建設" in label or "kerry" in label.lower()):
                    links.append({"text": label, "href": href})
            rec = {"url": url, "resolved": r.url, "status": r.status_code, "type": r.headers.get("content-type"), "bytes": len(r.content), "title": soup.title.get_text(" ", strip=True) if soup.title else "", "links": links}
            results.append(rec)
            print("SEARCH ROUTE", json.dumps(rec, ensure_ascii=False), flush=True)
        except Exception as exc:
            results.append({"url": url, "error": repr(exc)})
    return results


def main() -> None:
    details = {rid: inspect_detail(rid) for rid in REPORTS}
    images = {rid: try_image_patterns(rid, cfg) for rid, cfg in REPORTS.items()}
    searches = inspect_search_routes()
    Path("kerry-fxbaogao-results.json").write_text(json.dumps({"details": details, "images": images, "searches": searches}, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()

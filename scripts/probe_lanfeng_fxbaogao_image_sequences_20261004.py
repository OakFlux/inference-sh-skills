from __future__ import annotations

import hashlib
import json
from io import BytesIO
from pathlib import Path

import requests
from PIL import Image

OUT = Path("out/lanfeng_image_probe")
OUT.mkdir(parents=True, exist_ok=True)

session = requests.Session()
session.trust_env = False
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/152 Safari/537.36",
    "Referer": "https://www.fxbaogao.com/",
})

reports = [
    {"id": 966932, "date": "2015/11/11"},
    {"id": 967723, "date": "2015/11/12"},
]

records = []
for report in reports:
    rid = report["id"]
    folder = OUT / str(rid)
    folder.mkdir(exist_ok=True)
    misses = 0
    for page in range(1, 61):
        candidates = [
            f"https://public.fxbaogao.com/report-image/{report['date']}/{rid}-{page}.png",
            f"https://public.fxbaogao.com/report-image/{report['date']}/{rid}_{page}.png",
            f"https://public.fxbaogao.com/report-image/{report['date']}/{rid}/{page}.png",
            f"https://public.fxbaogao.com/report-image/{report['date']}/{rid}-{page}.jpg",
        ]
        page_hit = False
        for ci, url in enumerate(candidates, 1):
            try:
                response = session.get(url, timeout=(20, 120), allow_redirects=True)
                content_type = response.headers.get("content-type") or ""
                valid = response.status_code == 200 and (
                    response.content.startswith(b"\x89PNG") or response.content.startswith(b"\xff\xd8\xff")
                )
                item = {
                    "report_id": rid,
                    "page": page,
                    "candidate": ci,
                    "url": url,
                    "status": response.status_code,
                    "content_type": content_type,
                    "bytes": len(response.content),
                    "valid_image": valid,
                }
                if valid:
                    try:
                        image = Image.open(BytesIO(response.content))
                        image.verify()
                        image = Image.open(BytesIO(response.content))
                        item["width"] = image.width
                        item["height"] = image.height
                        item["format"] = image.format
                    except Exception as exc:
                        item["image_error"] = repr(exc)
                        valid = False
                        item["valid_image"] = False
                records.append(item)
                print(json.dumps(item, ensure_ascii=False))
                if valid:
                    ext = ".png" if response.content.startswith(b"\x89PNG") else ".jpg"
                    path = folder / f"page_{page:03d}{ext}"
                    path.write_bytes(response.content)
                    item["saved"] = str(path)
                    item["sha256"] = hashlib.sha256(response.content).hexdigest()
                    page_hit = True
                    break
            except Exception as exc:
                item = {"report_id": rid, "page": page, "candidate": ci, "url": url, "error": repr(exc)}
                records.append(item)
                print(json.dumps(item, ensure_ascii=False))
        if page_hit:
            misses = 0
        else:
            misses += 1
            if page >= 3 and misses >= 3:
                break

(OUT / "probe.json").write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")

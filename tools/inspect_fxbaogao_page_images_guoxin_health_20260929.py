from __future__ import annotations

import json
from pathlib import Path

import requests
from PIL import Image
from io import BytesIO

BASE = "https://public.fxbaogao.com/report-image/2022/09/27/3392613-{page}.png"
OUT = Path("fxbaogao_guoxin_health_page_images.json")
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/152.0.0.0 Safari/537.36",
    "Referer": "https://www.fxbaogao.com/view?id=3392613",
    "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
}


def main():
    session = requests.Session()
    session.headers.update(HEADERS)
    records = []
    misses = 0
    for page in range(1, 41):
        url = BASE.format(page=page)
        try:
            response = session.get(url, timeout=90, allow_redirects=True)
            record = {
                "page": page,
                "url": url,
                "status": response.status_code,
                "bytes": len(response.content),
                "content_type": response.headers.get("content-type"),
                "etag": response.headers.get("etag"),
            }
            if response.status_code == 200 and len(response.content) > 1000:
                try:
                    image = Image.open(BytesIO(response.content))
                    record.update({"format": image.format, "width": image.width, "height": image.height})
                except Exception as exc:
                    record["image_error"] = repr(exc)
                misses = 0
            else:
                misses += 1
            records.append(record)
            print("PAGE_IMAGE", json.dumps(record, ensure_ascii=False), flush=True)
            if misses >= 3:
                break
        except Exception as exc:
            record = {"page": page, "url": url, "error": repr(exc)}
            records.append(record)
            misses += 1
            print("PAGE_IMAGE_ERROR", json.dumps(record, ensure_ascii=False), flush=True)
            if misses >= 3:
                break
    OUT.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()

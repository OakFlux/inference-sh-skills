from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path

import requests
from PIL import Image

REPORTS = [
    {"doc_id": 1531832, "date_path": "2010/01/14", "institution": "安信证券", "title": "泰尔重工：联轴器细分龙头，受冶金业影响较大"},
    {"doc_id": 1531895, "date_path": "2010/01/14", "institution": "国都证券", "title": "泰尔重工：国内联轴器行业龙头企业"},
    {"doc_id": 1531967, "date_path": "2010/01/14", "institution": "国信证券", "title": "泰尔重工：产能扩张，巩固龙头地位"},
    {"doc_id": 1532060, "date_path": "2010/01/15", "institution": "长城证券", "title": "泰尔重工：冶金联轴器龙头，立足于进口替代"},
]
OUT = Path("taier_fxbaogao_page_inventory.json")
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/152.0.0.0 Safari/537.36",
    "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
}


def main() -> None:
    session = requests.Session()
    records = []
    for report in REPORTS:
        pages = []
        misses = 0
        for page in range(1, 81):
            url = f"https://public.fxbaogao.com/report-image/{report['date_path']}/{report['doc_id']}-{page}.png"
            response = session.get(
                url,
                headers={**HEADERS, "Referer": f"https://www.fxbaogao.com/view?id={report['doc_id']}"},
                timeout=90,
                allow_redirects=True,
            )
            item = {
                "page": page,
                "url": url,
                "status": response.status_code,
                "bytes": len(response.content),
                "content_type": response.headers.get("content-type"),
            }
            if response.status_code == 200 and len(response.content) > 5000:
                image = Image.open(BytesIO(response.content))
                image.load()
                item.update({"format": image.format, "width": image.width, "height": image.height, "mode": image.mode})
                pages.append(item)
                misses = 0
            else:
                misses += 1
                if misses >= 3:
                    break
        rec = {**report, "page_count": len(pages), "pages": pages}
        records.append(rec)
        print("REPORT_PAGES", json.dumps({k: rec[k] for k in ("doc_id", "institution", "title", "page_count")}, ensure_ascii=False), flush=True)
        if pages:
            print("FIRST_LAST", json.dumps({"first": pages[0], "last": pages[-1]}, ensure_ascii=False), flush=True)
    OUT.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()

from __future__ import annotations

import json
import re
import requests

s = requests.Session()
s.trust_env = False
headers = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/152 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

for begin, end in [
    ("2019-01-01", "2020-12-31"),
    ("2021-01-01", "2022-12-31"),
    ("2023-01-01", "2024-12-31"),
    ("2025-01-01", "2026-09-28"),
]:
    for page in range(1, 5):
        url = (
            "https://reportapi.eastmoney.com/report/list"
            f"?cb=datatable&pageSize=100&pageNo={page}&fields=&qType=0&orgCode=&author="
            f"&beginTime={begin}&endTime={end}&code=300763"
            "&industryCode=*&industry=*&rating=*&ratingChange=*"
        )
        r = s.get(url, headers=headers, timeout=90)
        r.raise_for_status()
        m = re.search(r"datatable\((.*)\)\s*$", r.text, flags=re.S)
        if not m:
            raise RuntimeError(r.text[:500])
        payload = json.loads(m.group(1))
        if page == 1:
            print("WINDOW", begin, end, "hits", payload.get("hits"), "pages", payload.get("TotalPage"), flush=True)
        rows = payload.get("data") or []
        for row in rows:
            pages = int(row.get("attachPages") or 0)
            if pages < 15:
                continue
            print("LONG_REPORT", json.dumps({
                "title": row.get("title"),
                "orgSName": row.get("orgSName"),
                "publishDate": row.get("publishDate"),
                "infoCode": row.get("infoCode"),
                "attachPages": pages,
                "attachSize": row.get("attachSize"),
                "researcher": row.get("researcher"),
                "indvIsNew": row.get("indvIsNew"),
                "rating": row.get("emRatingName"),
            }, ensure_ascii=False), flush=True)
        total_pages = int(payload.get("TotalPage") or 1)
        if page >= total_pages or not rows:
            break

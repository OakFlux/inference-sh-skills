from __future__ import annotations

import json

import requests

API = "https://reportapi.eastmoney.com/report/list2"
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151 Safari/537.36"
)

session = requests.Session()
session.headers.update(
    {
        "User-Agent": UA,
        "Referer": "https://data.eastmoney.com/report/stock.jshtml",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Content-Type": "application/json",
    }
)


def query(code: str) -> list[dict]:
    rows_all: list[dict] = []
    for page in range(1, 6):
        body = {
            "pageSize": 100,
            "pageNo": page,
            "p": page,
            "pageNum": page,
            "pageNumber": page,
            "beginTime": "2000-01-01",
            "endTime": "2030-01-01",
            "code": code,
            "industryCode": "*",
            "rating": None,
            "ratingChange": None,
            "orgCode": None,
            "rcode": "",
        }
        response = session.post(API, json=body, timeout=(20, 120))
        print("CODE", repr(code), "PAGE", page, "STATUS", response.status_code)
        response.raise_for_status()
        print("TEXT_HEAD", response.text[:500].replace("\n", " "))
        payload = response.json()
        rows = payload.get("data") or []
        print(
            "ROWS", len(rows),
            "TOTAL", payload.get("TotalCount") or payload.get("total") or payload.get("count"),
        )
        if not rows:
            break
        rows_all.extend(rows)
        if len(rows) < 100:
            break
    return rows_all


codes = [
    "00152",
    "0152",
    "152",
    "00152.HK",
    "0152.HK",
    "HK00152",
    "116.00152",
    "116.0152",
    "深圳国际",
]

all_unique: dict[str, dict] = {}
for code in codes:
    print("\n=== QUERY", repr(code), "===")
    try:
        rows = query(code)
    except Exception as exc:
        print("ERROR", repr(exc))
        continue
    print("QUERY_ROWS", len(rows))
    for row in rows:
        info_code = str(row.get("infoCode") or row.get("encodeUrl") or row.get("InfoCode") or "")
        key = info_code or json.dumps(row, ensure_ascii=False, sort_keys=True)
        all_unique[key] = row

print("\n=== UNIQUE", len(all_unique), "===")
for row in sorted(
    all_unique.values(),
    key=lambda item: str(item.get("publishDate") or item.get("PublishDate") or ""),
    reverse=True,
):
    print(json.dumps(row, ensure_ascii=False))

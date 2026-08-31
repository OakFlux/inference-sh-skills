from __future__ import annotations

import json
import time

import requests

API = "https://reportapi.eastmoney.com/report/list"
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
    }
)


def query(params_extra: dict[str, str]) -> list[dict]:
    rows_all: list[dict] = []
    for page in range(1, 6):
        params = {
            "industryCode": "*",
            "pageSize": "100",
            "industry": "*",
            "rating": "*",
            "ratingChange": "*",
            "beginTime": "2000-01-01",
            "endTime": "2030-01-01",
            "pageNo": str(page),
            "fields": "",
            "qType": "0",
            "orgCode": "",
            "rcode": "",
            "p": str(page),
            "pageNum": str(page),
            "pageNumber": str(page),
            "_": str(int(time.time() * 1000)),
            **params_extra,
        }
        response = session.get(API, params=params, timeout=(20, 120))
        print("REQUEST", response.url, "STATUS", response.status_code)
        response.raise_for_status()
        payload = response.json()
        rows = payload.get("data") or []
        print("PAGE", page, "ROWS", len(rows), "TOTAL", payload.get("TotalCount") or payload.get("total"))
        if not rows:
            break
        rows_all.extend(rows)
        if len(rows) < 100:
            break
        time.sleep(1)
    return rows_all


queries = [
    ("code_00152", {"code": "00152"}),
    ("code_0152", {"code": "0152"}),
    ("keyword_深圳国际", {"keyword": "深圳国际"}),
    ("keyword_深圳國際", {"keyword": "深圳國際"}),
]

all_unique: dict[str, dict] = {}
for name, params in queries:
    print("\n===", name, "===")
    try:
        rows = query(params)
    except Exception as exc:
        print("ERROR", repr(exc))
        continue
    print("QUERY_ROWS", len(rows))
    for row in rows:
        info_code = str(row.get("infoCode") or row.get("encodeUrl") or row.get("InfoCode") or "")
        title = str(row.get("title") or row.get("Title") or "")
        stock_name = str(row.get("stockName") or row.get("secuName") or row.get("StockName") or "")
        stock_code = str(row.get("stockCode") or row.get("secuCode") or row.get("StockCode") or "")
        hay = " ".join([title, stock_name, stock_code])
        if "深圳国际" not in hay and "深圳國際" not in hay and stock_code not in {"00152", "0152"}:
            continue
        key = info_code or json.dumps(row, ensure_ascii=False, sort_keys=True)
        all_unique[key] = row

print("\n=== MATCHED UNIQUE", len(all_unique), "===")
for row in sorted(
    all_unique.values(),
    key=lambda item: str(item.get("publishDate") or item.get("PublishDate") or ""),
    reverse=True,
):
    keep = {
        key: row.get(key)
        for key in (
            "infoCode",
            "title",
            "publishDate",
            "orgSName",
            "researcher",
            "stockName",
            "stockCode",
            "secuName",
            "secuCode",
            "emRatingName",
            "indvInduName",
            "encodeUrl",
        )
        if key in row
    }
    print(json.dumps(keep, ensure_ascii=False))

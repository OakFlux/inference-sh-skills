from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import requests

CODE = "300311"
OUT = Path("renzixing_report_inventory.json")
URL = "https://reportapi.eastmoney.com/report/list"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/152.0.0.0 Safari/537.36",
    "Referer": "https://data.eastmoney.com/",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
}


def parse_jsonp(text: str) -> dict[str, Any]:
    text = text.strip()
    match = re.match(r"^[^(]+\((.*)\)\s*;?$", text, re.S)
    if match:
        text = match.group(1)
    return json.loads(text)


def normalize(row: dict[str, Any], year: int) -> dict[str, Any]:
    return {
        "year": year,
        "infoCode": row.get("infoCode"),
        "title": row.get("title"),
        "publishDate": row.get("publishDate"),
        "orgSName": row.get("orgSName") or row.get("orgName"),
        "researcher": row.get("researcher"),
        "emRatingName": row.get("emRatingName") or row.get("ratingName"),
        "ratingChange": row.get("ratingChange"),
        "indvInduName": row.get("indvInduName"),
        "stockName": row.get("stockName"),
        "stockCode": row.get("stockCode"),
        "encodeUrl": row.get("encodeUrl"),
        "attachType": row.get("attachType"),
        "count": row.get("count"),
    }


def main() -> None:
    session = requests.Session()
    session.headers.update(HEADERS)
    all_rows: list[dict[str, Any]] = []
    for year in range(2012, 2027):
        params = {
            "cb": "datatable",
            "pageSize": "200",
            "pageNo": "1",
            "qType": "0",
            "orgCode": "",
            "code": CODE,
            "industryCode": "",
            "industry": "",
            "rating": "",
            "ratingchange": "",
            "beginTime": f"{year}-01-01",
            "endTime": f"{year}-12-31",
            "fields": "",
            "p": "1",
            "pageNum": "1",
            "pageNumber": "1",
        }
        response = session.get(URL, params=params, timeout=90)
        print("YEAR_REQUEST", year, response.status_code, len(response.content), response.url, flush=True)
        response.raise_for_status()
        payload = parse_jsonp(response.text)
        rows = payload.get("data") or []
        print("YEAR_COUNT", year, len(rows), flush=True)
        for row in rows:
            item = normalize(row, year)
            all_rows.append(item)
            print("REPORT", json.dumps(item, ensure_ascii=False), flush=True)

    # De-duplicate by infoCode and sort newest first.
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for item in sorted(all_rows, key=lambda x: str(x.get("publishDate") or ""), reverse=True):
        key = str(item.get("infoCode") or "")
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(item)

    result = {"code": CODE, "count": len(deduped), "reports": deduped}
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print("TOTAL", len(deduped), flush=True)


if __name__ == "__main__":
    main()

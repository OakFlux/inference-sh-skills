from __future__ import annotations

import json
import re
import time
from pathlib import Path

import requests

OUT = Path("renzixing_report_inventory.json")
API = "https://reportapi.eastmoney.com/report/list"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/152.0.0.0 Safari/537.36",
    "Accept": "*/*",
    "Referer": "https://data.eastmoney.com/report/300311.html",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
}


def parse_jsonp(text: str):
    text = text.strip()
    if text.startswith("{"):
        return json.loads(text)
    match = re.search(r"^[^(]+\((.*)\)\s*;?\s*$", text, re.S)
    if not match:
        raise RuntimeError(f"Unrecognized response: {text[:300]}")
    return json.loads(match.group(1))


def main() -> None:
    session = requests.Session()
    session.headers.update(HEADERS)
    all_rows = []
    for year in range(2011, 2027):
        params = {
            "cb": "datatable",
            "pageSize": "200",
            "pageNo": "1",
            "qType": "0",
            "orgCode": "",
            "code": "300311",
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
        response = session.get(API, params=params, timeout=120)
        print("YEAR_REQUEST", year, response.status_code, len(response.content), response.url, flush=True)
        response.raise_for_status()
        payload = parse_jsonp(response.text)
        rows = payload.get("data") or []
        print("YEAR_COUNT", year, len(rows), flush=True)
        for row in rows:
            rec = {
                "year": year,
                "infoCode": row.get("infoCode"),
                "title": row.get("title"),
                "publishDate": row.get("publishDate"),
                "org": row.get("orgSName") or row.get("orgName"),
                "researcher": row.get("researcher"),
                "rating": row.get("emRatingName") or row.get("rating"),
                "ratingChange": row.get("ratingChange"),
                "predictThisYearEps": row.get("predictThisYearEps"),
                "predictNextYearEps": row.get("predictNextYearEps"),
                "indvInduName": row.get("indvInduName"),
            }
            all_rows.append(rec)
            print("REPORT", json.dumps(rec, ensure_ascii=False), flush=True)
        time.sleep(0.25)
    OUT.write_text(json.dumps(all_rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print("TOTAL", len(all_rows), flush=True)


if __name__ == "__main__":
    main()

from __future__ import annotations

import json
import re
from pathlib import Path

import requests

CODE = "000503"
OUT = Path("guoxin_health_report_inventory.json")
URL = "https://reportapi.eastmoney.com/report/list"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/152.0.0.0 Safari/537.36",
    "Accept": "application/json,text/plain,*/*",
    "Referer": "https://data.eastmoney.com/",
}


def parse_jsonp(text: str):
    text = text.strip()
    if text.startswith("datatable(") and text.endswith(")"):
        text = text[len("datatable("):-1]
    elif text.startswith("datatable"):
        match = re.search(r"datatable\((.*)\)\s*;?\s*$", text, re.S)
        if match:
            text = match.group(1)
    return json.loads(text)


def main():
    session = requests.Session()
    session.headers.update(HEADERS)
    all_rows = []
    for year in range(2010, 2027):
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
        response = session.get(URL, params=params, timeout=120)
        print("YEAR_REQUEST", year, response.status_code, len(response.content), response.url, flush=True)
        response.raise_for_status()
        data = parse_jsonp(response.text)
        rows = data.get("data") or []
        print("YEAR_COUNT", year, len(rows), flush=True)
        for row in rows:
            item = {
                "year": year,
                "info_code": row.get("infoCode") or row.get("info_code"),
                "title": row.get("title"),
                "publish_date": row.get("publishDate") or row.get("publish_date"),
                "org": row.get("orgSName") or row.get("orgName") or row.get("org"),
                "author": row.get("researcher") or row.get("author"),
                "rating": row.get("emRatingName") or row.get("rating"),
                "predict_this_year_eps": row.get("predictThisYearEps"),
                "predict_next_year_eps": row.get("predictNextYearEps"),
            }
            all_rows.append(item)
            print("REPORT", json.dumps(item, ensure_ascii=False), flush=True)
    OUT.write_text(json.dumps(all_rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print("WROTE", OUT, len(all_rows), flush=True)


if __name__ == "__main__":
    main()

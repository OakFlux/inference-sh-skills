from __future__ import annotations

import json
from pathlib import Path

import requests

CODE = "002347"
OUT = Path("taier_report_inventory.json")
URL = "https://reportapi.eastmoney.com/report/list"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/152.0.0.0 Safari/537.36",
    "Referer": "https://data.eastmoney.com/",
    "Accept": "*/*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
}


def parse_jsonp(text: str):
    text = text.strip()
    if text.startswith("datatable(") and text.endswith(")"):
        text = text[len("datatable("):-1]
    return json.loads(text)


def main() -> None:
    session = requests.Session()
    session.headers.update(HEADERS)
    rows_all = []
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
                "rating": row.get("emRatingName") or row.get("ratingName"),
                "ratingChange": row.get("ratingChange"),
                "predictThisYearEps": row.get("predictThisYearEps"),
                "predictNextYearEps": row.get("predictNextYearEps"),
                "indvInduName": row.get("indvInduName"),
            }
            rows_all.append(rec)
            print("REPORT", json.dumps(rec, ensure_ascii=False), flush=True)
    OUT.write_text(json.dumps(rows_all, ensure_ascii=False, indent=2), encoding="utf-8")
    print("TOTAL", len(rows_all), flush=True)


if __name__ == "__main__":
    main()

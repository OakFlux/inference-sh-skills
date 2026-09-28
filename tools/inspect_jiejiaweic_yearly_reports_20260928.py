from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
import requests

OUT = Path("jiejiaweic_yearly_report_inventory.json")
CODE = "300724"
ENDPOINT = "https://reportapi.eastmoney.com/report/list"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/152.0.0.0 Safari/537.36",
    "Accept": "application/json,text/plain,*/*",
    "Referer": "https://data.eastmoney.com/report/300724.html",
}


def parse(text: str) -> Any:
    text = text.strip()
    if text.startswith(("{", "[")):
        return json.loads(text)
    m = re.match(r"^[^(]+\((.*)\)\s*;?\s*$", text, re.S)
    if not m:
        raise ValueError(text[:200])
    return json.loads(m.group(1))


def rows_from(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, dict):
        value = data.get("data")
        if isinstance(value, list):
            return value
        if isinstance(value, dict):
            for key in ("data", "list", "items"):
                if isinstance(value.get(key), list):
                    return value[key]
    return []


def val(row: dict[str, Any], *keys: str) -> str:
    for key in keys:
        if row.get(key) not in (None, ""):
            return str(row[key])
    return ""


def main() -> None:
    s = requests.Session(); s.headers.update(HEADERS)
    all_rows: list[dict[str, Any]] = []
    for year in range(2020, 2027):
        params = {
            "cb": "datatable",
            "pageSize": 200,
            "pageNo": 1,
            "qType": 0,
            "orgCode": "",
            "code": CODE,
            "industryCode": "",
            "industry": "",
            "rating": "",
            "ratingchange": "",
            "beginTime": f"{year}-01-01",
            "endTime": f"{year}-12-31",
            "fields": "",
            "p": 1,
            "pageNum": 1,
            "pageNumber": 1,
        }
        r = s.get(ENDPOINT, params=params, timeout=120)
        print("YEAR_REQUEST", year, r.status_code, len(r.content), r.url, flush=True)
        r.raise_for_status()
        data = parse(r.text)
        rows = rows_from(data)
        print("YEAR_COUNT", year, len(rows), flush=True)
        for row in rows:
            normalized = {
                "year": year,
                "title": val(row, "title", "reportTitle", "REPORT_TITLE", "TITLE"),
                "info_code": val(row, "infoCode", "INFO_CODE", "reportId", "id"),
                "publish_date": val(row, "publishDate", "PUBLISH_DATE", "date"),
                "org": val(row, "orgSName", "orgName", "ORG_SNAME", "ORG_NAME"),
                "author": val(row, "researcher", "author", "RESEARCHER"),
                "rating": val(row, "emRatingName", "ratingName", "rating", "EM_RATING_NAME"),
                "raw": row,
            }
            all_rows.append(normalized)
            print("REPORT", json.dumps({k: normalized[k] for k in ("year", "title", "info_code", "publish_date", "org", "author", "rating")}, ensure_ascii=False), flush=True)
    OUT.write_text(json.dumps(all_rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print("WROTE", OUT, len(all_rows), flush=True)

if __name__ == "__main__":
    main()

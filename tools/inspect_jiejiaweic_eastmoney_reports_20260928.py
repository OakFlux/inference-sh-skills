from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import requests

OUT = Path("jiejiaweic_eastmoney_report_inventory.json")
CODE = "300724"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/152.0.0.0 Safari/537.36",
    "Accept": "application/json,text/plain,*/*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
    "Referer": "https://data.eastmoney.com/report/300724.html",
}


def unwrap_jsonp(text: str) -> Any:
    text = text.strip()
    if text.startswith("{") or text.startswith("["):
        return json.loads(text)
    m = re.match(r"^[^(]+\((.*)\)\s*;?\s*$", text, re.S)
    if not m:
        raise ValueError(f"Unable to parse JSONP prefix: {text[:200]!r}")
    return json.loads(m.group(1))


def iter_rows(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if not isinstance(data, dict):
        return []
    candidates = [
        data.get("data"),
        data.get("result"),
        data.get("reports"),
        data.get("items"),
        data.get("list"),
    ]
    for value in candidates:
        if isinstance(value, list):
            return [x for x in value if isinstance(x, dict)]
        if isinstance(value, dict):
            for key in ("data", "items", "list", "reports"):
                sub = value.get(key)
                if isinstance(sub, list):
                    return [x for x in sub if isinstance(x, dict)]
    return []


def get_value(row: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return str(value)
    return ""


def main() -> None:
    session = requests.Session()
    session.headers.update(HEADERS)
    endpoint = "https://reportapi.eastmoney.com/report/list"
    variants = [
        {
            "name": "canonical",
            "params": {
                "cb": "datatable",
                "pageSize": 100,
                "pageNo": 1,
                "qType": 0,
                "orgCode": "",
                "code": CODE,
                "industryCode": "",
                "industry": "",
                "rating": "",
                "ratingchange": "",
                "beginTime": "2020-01-01",
                "endTime": "2026-09-28",
                "fields": "",
                "p": 1,
                "pageNum": 1,
                "pageNumber": 1,
            },
        },
        {
            "name": "no_jsonp",
            "params": {
                "pageSize": 100,
                "pageNo": 1,
                "qType": 0,
                "code": CODE,
                "beginTime": "2020-01-01",
                "endTime": "2026-09-28",
            },
        },
        {
            "name": "legacy",
            "params": {
                "cb": "datatable",
                "pageSize": 100,
                "pageNo": 1,
                "qType": 0,
                "orgCode": "",
                "code": CODE,
                "industryCode": "",
                "industry": "",
                "rating": "",
                "ratingchange": "",
                "beginTime": "2020-01-01",
                "endTime": "2026-09-28",
                "fields": "",
            },
        },
    ]
    records: list[dict[str, Any]] = []
    for variant in variants:
        try:
            response = session.get(endpoint, params=variant["params"], timeout=120)
            print("REQUEST", variant["name"], response.status_code, response.url, len(response.content), response.headers.get("content-type"), flush=True)
            response.raise_for_status()
            data = unwrap_jsonp(response.text)
            rows = iter_rows(data)
            print("ROW_COUNT", variant["name"], len(rows), flush=True)
            for row in rows:
                title = get_value(row, "title", "reportTitle", "REPORT_TITLE", "TITLE")
                info_code = get_value(row, "infoCode", "INFO_CODE", "reportId", "id")
                publish = get_value(row, "publishDate", "PUBLISH_DATE", "date")
                org = get_value(row, "orgSName", "orgName", "ORG_SNAME", "ORG_NAME")
                author = get_value(row, "researcher", "author", "RESEARCHER")
                rating = get_value(row, "emRatingName", "ratingName", "rating", "EM_RATING_NAME")
                normalized = {
                    "variant": variant["name"],
                    "title": title,
                    "info_code": info_code,
                    "publish_date": publish,
                    "org": org,
                    "author": author,
                    "rating": rating,
                    "raw": row,
                }
                records.append(normalized)
                if any(token in title for token in ("乘技术变革之风", "光伏设备平台化布局", "光伏领域三线布局", "深度", "首次覆盖")):
                    print("MATCH", json.dumps({k: normalized[k] for k in ("title", "info_code", "publish_date", "org", "author", "rating")}, ensure_ascii=False), flush=True)
            if rows:
                break
        except Exception as exc:
            print("ERROR", variant["name"], repr(exc), flush=True)
    OUT.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    print("WROTE", OUT, len(records), flush=True)


if __name__ == "__main__":
    main()

from __future__ import annotations

import time
from typing import Any

import requests

STOCK_CODE = "300699"

session = requests.Session()
session.headers.update(
    {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151 Safari/537.36"
        ),
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Referer": "https://data.eastmoney.com/report/",
    }
)


def main() -> None:
    timestamp = int(time.time() * 1000)
    response = session.get(
        "https://reportapi.eastmoney.com/report/list",
        params={
            "industryCode": "*",
            "pageSize": "100",
            "industry": "*",
            "rating": "*",
            "ratingChange": "*",
            "companyType": "*",
            "beginTime": "2000-01-01",
            "endTime": "2030-01-01",
            "pageNo": "1",
            "fields": "",
            "qType": "0",
            "orgCode": "",
            "code": STOCK_CODE,
            "rcode": "",
            "p": "1",
            "pageNum": "1",
            "pageNumber": "1",
            "_": str(timestamp),
        },
        headers={"Accept": "application/json,text/javascript,*/*;q=0.9"},
        timeout=(30, 180),
    )
    response.raise_for_status()
    payload = response.json()

    raw_records: list[Any] = []
    if isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, list):
            raw_records = data
        elif isinstance(data, dict):
            for key in ("data", "list", "items"):
                value = data.get(key)
                if isinstance(value, list):
                    raw_records = value
                    break
        if not raw_records:
            for key in ("result", "list", "items"):
                value = payload.get(key)
                if isinstance(value, list):
                    raw_records = value
                    break
    elif isinstance(payload, list):
        raw_records = payload

    if not raw_records:
        raise RuntimeError(f"No report list found; payload={str(payload)[:1000]}")

    records: list[dict[str, Any]] = []
    for raw in raw_records:
        if not isinstance(raw, dict):
            continue
        info_code = str(raw.get("infoCode") or raw.get("INFOCODE") or "").strip()
        title = str(raw.get("title") or raw.get("TITLE") or "").strip()
        if not info_code.startswith("AP") or not title:
            continue
        records.append(
            {
                "info_code": info_code,
                "publish_date": str(
                    raw.get("publishDate")
                    or raw.get("publishDateStr")
                    or raw.get("PUBLISH_DATE")
                    or ""
                )[:10],
                "broker": str(
                    raw.get("orgSName")
                    or raw.get("orgName")
                    or raw.get("ORG_SNAME")
                    or ""
                ),
                "researcher": str(
                    raw.get("researcher")
                    or raw.get("researcherName")
                    or raw.get("RESEARCHER")
                    or ""
                ),
                "pages": raw.get("attachPages"),
                "title": title,
            }
        )

    print(f"REPORT_COUNT={len(records)}")
    for record in records:
        print(
            f"{record['info_code']} | {record['publish_date']} | "
            f"{record['broker']} | pages={record['pages']} | "
            f"{record['researcher']} | {record['title']}"
        )


if __name__ == "__main__":
    main()

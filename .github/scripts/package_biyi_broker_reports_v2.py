from __future__ import annotations

import json
import time
from typing import Any

import package_biyi_broker_reports as base


def fetch_report_records() -> list[dict[str, Any]]:
    url = "https://reportapi.eastmoney.com/report/list"
    timestamp = int(time.time() * 1000)
    # The endpoint now returns JSON directly when cb is omitted. Supplying an
    # arbitrary long callback name can be rejected as "Wrong callback Function".
    params = {
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
        "code": base.STOCK_CODE,
        "rcode": "",
        "p": "1",
        "pageNum": "1",
        "pageNumber": "1",
        "_": str(timestamp),
    }
    response = base.session.get(
        url,
        params=params,
        headers={
            "Referer": "https://data.eastmoney.com/report/",
            "Accept": "application/json,text/javascript,*/*;q=0.9",
        },
        timeout=(30, 180),
    )
    if response.status_code != 200:
        raise RuntimeError(
            f"Eastmoney API HTTP {response.status_code}: {response.text[:1000]}"
        )

    text = response.text.strip()
    try:
        payload = response.json()
    except ValueError:
        if text.startswith("{") or text.startswith("["):
            payload = json.loads(text)
        else:
            left = text.find("(")
            right = text.rfind(")")
            if left < 0 or right <= left:
                raise RuntimeError(f"Unexpected API response: {text[:1000]}")
            payload = json.loads(text[left + 1 : right])

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
        raise RuntimeError(
            "Eastmoney API returned no report list; payload keys="
            + (str(list(payload.keys())) if isinstance(payload, dict) else str(type(payload)))
        )

    records: list[dict[str, Any]] = []
    for raw in raw_records:
        if not isinstance(raw, dict):
            continue
        info_code = str(
            raw.get("infoCode")
            or raw.get("infocode")
            or raw.get("INFOCODE")
            or ""
        ).strip()
        title = str(raw.get("title") or raw.get("TITLE") or "").strip()
        if not info_code.startswith("AP") or not title:
            continue
        records.append(
            {
                "info_code": info_code,
                "title": title,
                "broker": str(
                    raw.get("orgSName")
                    or raw.get("orgName")
                    or raw.get("ORG_SNAME")
                    or "未知券商"
                ).strip(),
                "publish_date": str(
                    raw.get("publishDate")
                    or raw.get("publishDateStr")
                    or raw.get("PUBLISH_DATE")
                    or ""
                ).strip()[:10],
                "researcher": str(
                    raw.get("researcher")
                    or raw.get("researcherName")
                    or raw.get("RESEARCHER")
                    or ""
                ).strip(),
                "metadata": raw,
            }
        )

    unique = {record["info_code"]: record for record in records}
    result = list(unique.values())
    print(f"Eastmoney API records: {len(result)}")
    for record in result:
        attach_pages = record["metadata"].get("attachPages")
        print(
            f"{record['info_code']} | {record['publish_date']} | "
            f"{record['broker']} | pages={attach_pages} | {record['title']}"
        )
    return result


base.fetch_report_records = fetch_report_records
base.main()

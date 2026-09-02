from __future__ import annotations

import json
import time
from typing import Any

import requests

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151 Safari/537.36"
)

session = requests.Session()
session.headers.update(
    {
        "User-Agent": UA,
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Referer": "https://data.eastmoney.com/report/stock.jshtml",
    }
)


def show_records(label: str, payload: Any) -> None:
    print(f"\n===== {label} =====")
    if not isinstance(payload, dict):
        print("NON-DICT", repr(payload)[:2000])
        return
    print("TOP_KEYS", list(payload.keys()))
    print(
        "COUNTS",
        {
            key: payload.get(key)
            for key in ("hits", "TotalCount", "total", "TotalPage", "pageNo", "size")
            if key in payload
        },
    )
    rows = payload.get("data") or payload.get("Data") or []
    print("ROWS", len(rows))
    for row in rows[:200]:
        keep = {
            key: row.get(key)
            for key in (
                "infoCode",
                "title",
                "publishDate",
                "orgSName",
                "orgName",
                "researcher",
                "stockName",
                "stockCode",
                "secuName",
                "secuCode",
                "code",
                "attachPages",
                "attachSize",
                "emRatingName",
                "ratingName",
                "reportType",
                "encodeUrl",
            )
            if key in row
        }
        text = json.dumps(keep, ensure_ascii=False)
        if any(
            marker in text
            for marker in (
                "四环医药",
                "四環醫藥",
                "00460",
                "0460.HK",
                "460.HK",
                "平台型医美新星",
                "跨越制药边界",
                "医美和创新药双轮驱动",
            )
        ):
            print("MATCH", text)
        else:
            print("ROW", text)


def post_list2(code: str, *, use_json: bool) -> None:
    payload = {
        "pageSize": 100,
        "pageNo": 1,
        "p": 1,
        "pageNum": 1,
        "pageNumber": 1,
        "beginTime": "2022-01-01",
        "endTime": "2026-09-02",
        "code": code,
        "industryCode": "*",
        "rating": None,
        "ratingChange": None,
        "orgCode": None,
        "rcode": "",
    }
    headers = {"Content-Type": "application/json"} if use_json else {}
    response = session.post(
        "https://reportapi.eastmoney.com/report/list2",
        json=payload if use_json else None,
        data=None if use_json else payload,
        headers=headers,
        timeout=(20, 120),
    )
    print(
        "REQUEST",
        "JSON" if use_json else "FORM",
        code,
        "STATUS",
        response.status_code,
        "LEN",
        len(response.content),
        "HEAD",
        response.text[:300].replace("\n", " "),
    )
    response.raise_for_status()
    show_records(f"list2 {'json' if use_json else 'form'} code={code}", response.json())


def get_list(code: str) -> None:
    params = {
        "industryCode": "*",
        "pageSize": 100,
        "industry": "*",
        "rating": "*",
        "ratingChange": "*",
        "beginTime": "2022-01-01",
        "endTime": "2026-09-02",
        "pageNo": 1,
        "fields": "",
        "qType": 0,
        "orgCode": "",
        "rcode": "",
        "code": code,
        "_": int(time.time() * 1000),
    }
    response = session.get(
        "https://reportapi.eastmoney.com/report/list",
        params=params,
        timeout=(20, 120),
    )
    print(
        "REQUEST GET list",
        code,
        "STATUS",
        response.status_code,
        "LEN",
        len(response.content),
        "HEAD",
        response.text[:300].replace("\n", " "),
    )
    response.raise_for_status()
    show_records(f"list get code={code}", response.json())


print("===== Eastmoney stock suggestions =====")
for keyword in ("四环医药", "00460", "0460"):
    response = session.get(
        "https://searchapi.eastmoney.com/api/suggest/get",
        params={
            "input": keyword,
            "type": 14,
            "token": "D43BF722C8E33BDC906FB84D85E326E8",
            "count": 20,
        },
        timeout=(20, 120),
    )
    print("SUGGEST", keyword, response.status_code, response.text[:3000])

codes = [
    "00460",
    "0460",
    "460",
    "00460.HK",
    "0460.HK",
    "HK00460",
    "116.00460",
    "116.0460",
]

for code in codes:
    for use_json in (True, False):
        try:
            post_list2(code, use_json=use_json)
        except Exception as exc:
            print("ERROR list2", code, use_json, repr(exc))
    try:
        get_list(code)
    except Exception as exc:
        print("ERROR list", code, repr(exc))

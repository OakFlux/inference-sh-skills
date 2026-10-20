#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import requests

STOCK_CODE = "300458"
BEGIN_DATE = "2015-01-01"
END_DATE = "2026-10-20"
OUT_DIR = Path("dist_discovery")
OUT_DIR.mkdir(parents=True, exist_ok=True)

session = requests.Session()
session.trust_env = False
headers = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/155 Safari/537.36",
    "Accept": "application/json,text/plain,*/*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Referer": f"https://data.eastmoney.com/report/{STOCK_CODE}.html",
}


def request_json(params: dict[str, str]) -> dict[str, Any]:
    errors: list[str] = []
    for attempt in range(1, 7):
        try:
            response = session.get(
                "https://reportapi.eastmoney.com/report/list",
                params=params,
                headers=headers,
                timeout=(20, 120),
            )
            print("HTTP", attempt, response.status_code, response.url, flush=True)
            response.raise_for_status()
            return response.json()
        except Exception as exc:  # noqa: BLE001
            errors.append(repr(exc))
            time.sleep(min(attempt * 2, 10))
    raise RuntimeError(errors[-3:])


rows: list[dict[str, Any]] = []
for page in range(1, 15):
    params = {
        "industryCode": "*",
        "pageSize": "100",
        "industry": "*",
        "rating": "*",
        "ratingChange": "*",
        "beginTime": BEGIN_DATE,
        "endTime": END_DATE,
        "pageNo": str(page),
        "fields": "",
        "qType": "0",
        "orgCode": "",
        "code": STOCK_CODE,
        "rcode": "",
        "p": str(page),
        "pageNum": str(page),
        "pageNumber": str(page),
    }
    payload = request_json(params)
    page_rows = payload.get("data") or []
    if not isinstance(page_rows, list):
        raise RuntimeError(f"Unexpected payload: {payload}")
    print("PAGE", page, "ROWS", len(page_rows), flush=True)
    rows.extend(item for item in page_rows if isinstance(item, dict))
    if len(page_rows) < 100:
        break

# Deduplicate by infoCode and normalize the fields relevant to selecting complete reports.
normalized: list[dict[str, Any]] = []
seen: set[str] = set()
for row in rows:
    info_code = str(row.get("infoCode") or "").strip()
    if not info_code or info_code in seen:
        continue
    seen.add(info_code)
    normalized.append(
        {
            "infoCode": info_code,
            "publishDate": str(row.get("publishDate") or row.get("publishDateString") or "")[:10],
            "title": str(row.get("title") or "").strip(),
            "orgSName": str(row.get("orgSName") or row.get("orgName") or "").strip(),
            "orgName": str(row.get("orgName") or "").strip(),
            "researcher": str(row.get("researcher") or "").strip(),
            "attachPages": int(row.get("attachPages") or 0),
            "attachSize": row.get("attachSize"),
            "emRatingName": str(row.get("emRatingName") or "").strip(),
            "stockName": str(row.get("stockName") or "").strip(),
            "stockCode": str(row.get("stockCode") or "").strip(),
            "detailUrl": f"https://data.eastmoney.com/report/info/{info_code}.html",
            "pdfH3": f"https://pdf.dfcfw.com/pdf/H3_{info_code}_1.pdf",
            "pdfH2": f"https://pdf.dfcfw.com/pdf/H2_{info_code}_1.pdf",
        }
    )

normalized.sort(key=lambda item: (item["publishDate"], item["attachPages"]), reverse=True)

priority_tokens = ("深度", "首次覆盖", "首次", "行业专题", "AIoT", "SoC", "端侧AI", "芯片")
priority = [
    item for item in normalized
    if item["attachPages"] >= 10 or any(token in item["title"] for token in priority_tokens)
]
priority.sort(
    key=lambda item: (
        1 if "深度" in item["title"] else 0,
        1 if "首次" in item["title"] else 0,
        item["attachPages"],
        item["publishDate"],
    ),
    reverse=True,
)

(OUT_DIR / "all_reports.json").write_text(
    json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf-8"
)
(OUT_DIR / "priority_candidates.json").write_text(
    json.dumps(priority, ensure_ascii=False, indent=2), encoding="utf-8"
)

with (OUT_DIR / "catalog.txt").open("w", encoding="utf-8") as handle:
    handle.write(f"全志科技（{STOCK_CODE}）券商报告目录\n")
    handle.write(f"查询区间：{BEGIN_DATE} 至 {END_DATE}\n")
    handle.write(f"记录数：{len(normalized)}\n\n")
    for item in normalized:
        handle.write(
            f"{item['publishDate']} | {item['orgSName']} | {item['attachPages']:>3}页 | "
            f"{item['infoCode']} | {item['title']} | {item['researcher']}\n"
        )

print("REPORT_COUNT", len(normalized), flush=True)
print("PRIORITY_COUNT", len(priority), flush=True)
for item in priority[:40]:
    print("CANDIDATE", json.dumps(item, ensure_ascii=False), flush=True)

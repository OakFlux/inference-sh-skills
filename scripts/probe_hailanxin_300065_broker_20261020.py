from __future__ import annotations

import json
import time
from typing import Any

import requests

CODE = "300065"
AS_OF_DATE = "2026-10-20"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/152 Safari/537.36",
    "Accept": "application/json,text/plain,*/*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Referer": "https://data.eastmoney.com/report/stock.jshtml",
}


def log(*args: Any) -> None:
    print(*args, flush=True)


def main() -> None:
    session = requests.Session()
    session.trust_env = False
    rows: list[dict[str, Any]] = []
    for page in range(1, 6):
        params = {
            "pageSize": "100",
            "pageNo": str(page),
            "code": CODE,
            "qType": "0",
            "industryCode": "*",
            "industry": "*",
            "rating": "*",
            "ratingChange": "*",
            "beginTime": "2010-01-01",
            "endTime": AS_OF_DATE,
            "orgCode": "",
            "rcode": "",
            "fields": "",
        }
        response = session.get(
            "https://reportapi.eastmoney.com/report/list",
            params=params,
            headers=HEADERS,
            timeout=90,
        )
        log("STATUS", page, response.status_code, response.headers.get("content-type"), len(response.content), response.url)
        response.raise_for_status()
        page_rows = response.json().get("data") or []
        log("PAGE_COUNT", page, len(page_rows))
        rows.extend(page_rows)
        if len(page_rows) < 100:
            break
        time.sleep(0.4)

    unique: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = str(row.get("infoCode") or "")
        if key:
            unique[key] = row

    candidates: list[dict[str, Any]] = []
    deep_words = ("深度", "首次覆盖", "公司研究", "公司报告", "投资价值", "海底数据中心", "海洋观探测", "海洋信息化")
    for row in unique.values():
        title = str(row.get("title") or "")
        pages = int(row.get("attachPages") or 0)
        if pages >= 15 or any(word in title for word in deep_words):
            candidates.append(row)

    candidates.sort(key=lambda row: (str(row.get("publishDate") or ""), int(row.get("attachPages") or 0)), reverse=True)
    log("TOTAL_UNIQUE", len(unique), "CANDIDATES", len(candidates))
    for row in candidates:
        output = {key: row.get(key) for key in [
            "title", "stockName", "stockCode", "orgName", "orgSName", "publishDate",
            "infoCode", "attachPages", "attachSize", "researcher", "emRatingName", "sRatingName",
        ]}
        log("ROW", json.dumps(output, ensure_ascii=False))


if __name__ == "__main__":
    main()

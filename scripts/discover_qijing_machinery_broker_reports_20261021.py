from __future__ import annotations

import csv
import json
import time
from pathlib import Path
from typing import Any

import requests

STOCK_CODE = "603677"
COMPANY = "奇精机械"
AS_OF = "2026-10-21"
OUT_DIR = Path("discovery_qijing_603677")
API = "https://reportapi.eastmoney.com/report/list"

SESSION = requests.Session()
SESSION.trust_env = False
SESSION.headers.update(
    {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "Chrome/155.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json,text/plain,*/*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Referer": f"https://data.eastmoney.com/report/{STOCK_CODE}.html",
    }
)


def request_json(params: dict[str, str]) -> dict[str, Any]:
    errors: list[str] = []
    for attempt in range(1, 8):
        try:
            response = SESSION.get(API, params=params, timeout=(20, 120))
            print("HTTP", attempt, response.status_code, response.url, flush=True)
            if response.status_code in {429, 500, 502, 503, 504}:
                response.close()
                time.sleep(min(attempt * 2, 12))
                continue
            response.raise_for_status()
            payload = response.json()
            response.close()
            if not isinstance(payload, dict):
                raise RuntimeError(f"unexpected payload type: {type(payload)!r}")
            return payload
        except Exception as exc:  # noqa: BLE001
            errors.append(repr(exc))
            time.sleep(min(attempt * 2, 12))
    raise RuntimeError(f"Eastmoney API request failed: {errors[-4:]}")


def fetch_year(year: int) -> list[dict[str, Any]]:
    collected: list[dict[str, Any]] = []
    for page in range(1, 30):
        params = {
            "industryCode": "*",
            "pageSize": "100",
            "industry": "*",
            "rating": "*",
            "ratingChange": "*",
            "beginTime": f"{year}-01-01",
            "endTime": f"{year}-12-31" if year < 2026 else AS_OF,
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
        rows = payload.get("data") or []
        if not isinstance(rows, list):
            raise RuntimeError(f"unexpected data field for {year} page {page}: {type(rows)!r}")
        print("YEAR_PAGE", year, page, "ROWS", len(rows), flush=True)
        collected.extend(row for row in rows if isinstance(row, dict))
        if len(rows) < 100:
            break
    return collected


def clean(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "infoCode": str(row.get("infoCode") or ""),
        "stockCode": str(row.get("stockCode") or ""),
        "stockName": str(row.get("stockName") or ""),
        "title": str(row.get("title") or ""),
        "orgSName": str(row.get("orgSName") or ""),
        "orgName": str(row.get("orgName") or ""),
        "researcher": str(row.get("researcher") or ""),
        "publishDate": str(row.get("publishDate") or "")[:10],
        "attachPages": int(row.get("attachPages") or 0),
        "attachSize": row.get("attachSize"),
        "emRatingName": str(row.get("emRatingName") or ""),
        "ratingChange": str(row.get("ratingChange") or ""),
        "indvInduName": str(row.get("indvInduName") or ""),
        "encodeUrl": str(row.get("encodeUrl") or ""),
    }


def priority_score(row: dict[str, Any]) -> tuple[int, str]:
    title = row["title"]
    pages = int(row["attachPages"] or 0)
    score = pages * 10
    if any(token in title for token in ("深度", "首次覆盖", "首次评级", "公司研究", "投资价值分析")):
        score += 500
    if any(token in title for token in ("点评", "快报", "季报", "年报", "业绩预告", "事件点评")):
        score -= 120
    return score, row["publishDate"]


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    all_rows: list[dict[str, Any]] = []
    for year in range(2010, 2027):
        all_rows.extend(fetch_year(year))

    dedup: dict[str, dict[str, Any]] = {}
    for raw in all_rows:
        row = clean(raw)
        info_code = row["infoCode"]
        if not info_code:
            continue
        if STOCK_CODE not in row["stockCode"] and COMPANY not in row["stockName"]:
            continue
        dedup[info_code] = row

    reports = sorted(dedup.values(), key=lambda r: (r["publishDate"], r["attachPages"]), reverse=True)
    priority = sorted(reports, key=priority_score, reverse=True)

    (OUT_DIR / "all_reports.json").write_text(
        json.dumps(reports, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (OUT_DIR / "priority_candidates.json").write_text(
        json.dumps(priority, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    fields = [
        "publishDate", "orgSName", "orgName", "researcher", "title", "attachPages",
        "attachSize", "emRatingName", "ratingChange", "infoCode", "stockCode", "stockName",
    ]
    with (OUT_DIR / "all_reports.csv").open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(reports)

    summary = {
        "company": COMPANY,
        "stock_code": STOCK_CODE,
        "checked_as_of": AS_OF,
        "report_count": len(reports),
        "long_report_count_15_pages_plus": sum(1 for row in reports if row["attachPages"] >= 15),
        "top_candidates": priority[:20],
    }
    (OUT_DIR / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("DISCOVERY_SUMMARY=" + json.dumps(summary, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()

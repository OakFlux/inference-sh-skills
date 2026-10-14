from __future__ import annotations

import json
import time
from datetime import date, timedelta
from typing import Any

import build_solex_603992_broker_deep_reports_20261014 as base


def _query_window(start: str, end: str, code: str, tag: str) -> list[dict[str, Any]]:
    endpoint = "https://reportapi.eastmoney.com/report/list"
    all_rows: list[dict[str, Any]] = []
    for page in range(1, 8):
        params = {
            "industryCode": "*",
            "pageSize": "100",
            "industry": "*",
            "rating": "*",
            "ratingChange": "*",
            "beginTime": start,
            "endTime": end,
            "pageNo": str(page),
            "fields": "",
            "qType": "0",
            "orgCode": "",
            "code": code,
            "rcode": "",
            "p": str(page),
            "pageNum": str(page),
            "pageNumber": str(page),
            # Eastmoney validates callback names; keep the known-working value fixed.
            "cb": "datatableSolex",
            "_": str(int(time.time() * 1000)),
        }
        response = base.SESSION.get(
            endpoint,
            params=params,
            headers={**base.HEADERS, "Referer": "https://data.eastmoney.com/"},
            timeout=(20, 120),
        )
        print("REPORT_WINDOW", tag, page, response.status_code, response.url, response.headers.get("content-type"), flush=True)
        response.raise_for_status()
        (base.DEBUG_DIR / f"eastmoney_{tag}_page_{page}.txt").write_text(
            response.text, encoding="utf-8", errors="replace"
        )
        obj = base.parse_json_or_jsonp(response.text)
        rows = [row for row in base.rows_from_object(obj) if isinstance(row, dict)]
        print("REPORT_WINDOW_ROWS", tag, page, len(rows), flush=True)
        if not rows:
            break
        all_rows.extend(rows)
        total_page = 0
        if isinstance(obj, dict):
            try:
                total_page = int(obj.get("TotalPage") or 0)
            except Exception:
                total_page = 0
        if total_page and page >= total_page:
            break
        if len(rows) < 100:
            break
        time.sleep(1.0)
    return all_rows


def fetch_report_rows_v2() -> list[dict[str, Any]]:
    collected: list[dict[str, Any]] = []
    errors: list[str] = []

    # First try the normal stock-specific query over a broad range.
    try:
        collected.extend(_query_window("2000-01-01", "2030-01-01", base.CODE, "stock_all"))
    except Exception as exc:  # noqa: BLE001
        errors.append(f"stock query: {exc!r}")
        print("STOCK_QUERY_ERROR", errors[-1], flush=True)

    # Some brokers are not returned by the stock-filtered endpoint. Query all reports
    # in narrow windows around the known publication dates, then filter locally.
    target_dates = [date.fromisoformat(item["date"]) for item in base.PREFERRED]
    target_dates.extend(
        [
            date(2025, 9, 30),
            date(2025, 10, 9),
            date(2025, 9, 27),
            date(2024, 4, 9),
        ]
    )
    for target in target_dates:
        start = (target - timedelta(days=2)).isoformat()
        end = (target + timedelta(days=2)).isoformat()
        tag = target.strftime("%Y%m%d")
        try:
            collected.extend(_query_window(start, end, "*", tag))
        except Exception as exc:  # noqa: BLE001
            errors.append(f"window {tag}: {exc!r}")
            print("WINDOW_QUERY_ERROR", errors[-1], flush=True)

    by_code: dict[str, dict[str, Any]] = {}
    for row in collected:
        info = str(row.get("infoCode") or row.get("infocode") or "").strip()
        if not info:
            continue
        stock_code = str(row.get("stockCode") or row.get("SECURITY_CODE") or "").strip()
        stock_name = str(row.get("stockName") or row.get("SECURITY_NAME_ABBR") or "").strip()
        title = str(row.get("title") or row.get("reportTitle") or "")
        if stock_code == base.CODE or stock_name == base.COMPANY or base.COMPANY in title:
            by_code[info] = row

    rows = list(by_code.values())
    (base.DEBUG_DIR / "eastmoney_combined_rows.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    print("COMBINED_SOLEX_ROWS", len(rows), flush=True)
    for row in sorted(rows, key=lambda item: str(item.get("publishDate") or ""), reverse=True):
        print(
            "COMBINED_REPORT",
            str(row.get("publishDate") or "")[:10],
            row.get("orgSName") or row.get("orgName"),
            row.get("infoCode"),
            row.get("attachPages"),
            row.get("title"),
            flush=True,
        )
    if not rows:
        raise RuntimeError("no 松霖科技 reports found; " + " | ".join(errors))
    return rows


base.fetch_report_rows = fetch_report_rows_v2

if __name__ == "__main__":
    base.main()

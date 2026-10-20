from __future__ import annotations

import datetime as dt
import importlib.util
import json
from pathlib import Path
from typing import Any

BASE_PATH = Path(__file__).with_name("build_henghe_precision_broker_reports_20261020.py")
spec = importlib.util.spec_from_file_location("henghe_builder", BASE_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError(f"Cannot load {BASE_PATH}")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def extract_rows(payload: Any) -> list[dict[str, Any]]:
    rows: Any = []
    if isinstance(payload, dict):
        rows = payload.get("data") or payload.get("Data") or payload.get("result") or []
        if isinstance(rows, dict):
            rows = rows.get("data") or rows.get("list") or rows.get("rows") or []
    elif isinstance(payload, list):
        rows = payload
    if not isinstance(rows, list):
        return []
    return [dict(item) for item in rows if isinstance(item, dict)]


def fetch_window(begin: str, end: str, *, code: str | None = None) -> list[dict[str, Any]]:
    params: dict[str, Any] = {
        "industryCode": "*",
        "pageSize": "5000",
        "industry": "*",
        "rating": "*",
        "ratingChange": "*",
        "beginTime": begin,
        "endTime": end,
        "pageNo": "1",
        "fields": "",
        "qType": "0",
        "orgCode": "",
        "rcode": "",
        "p": "1",
        "pageNum": "1",
        "pageNumber": "1",
    }
    if code is not None:
        params["code"] = code

    response = module.request_with_retry(module.REPORT_API, params=params)
    try:
        raw_text = response.text
        payload = module.parse_json_or_jsonp(raw_text)
    finally:
        response.close()
    rows = extract_rows(payload)
    print(
        "WINDOW",
        begin,
        end,
        "CODE",
        code,
        "ROWS",
        len(rows),
        "TARGET_ROWS",
        sum(str(item.get("stockCode") or "") == module.CODE for item in rows),
        "RAW_PREFIX",
        raw_text[:400],
        flush=True,
    )

    total_page = 1
    if isinstance(payload, dict):
        total_page = int(payload.get("TotalPage") or payload.get("totalPage") or 1)
    all_rows = list(rows)
    for page in range(2, min(total_page, 50) + 1):
        page_params = dict(params)
        page_params.update(
            {
                "pageNo": str(page),
                "p": str(page),
                "pageNum": str(page),
                "pageNumber": str(page),
            }
        )
        page_response = module.request_with_retry(module.REPORT_API, params=page_params)
        try:
            page_payload = module.parse_json_or_jsonp(page_response.text)
        finally:
            page_response.close()
        page_rows = extract_rows(page_payload)
        print("WINDOW_PAGE", begin, end, page, len(page_rows), flush=True)
        if not page_rows:
            break
        all_rows.extend(page_rows)
    return all_rows


def patched_list_reports() -> list[dict[str, Any]]:
    collected: list[dict[str, Any]] = []

    # First reproduce the currently documented Eastmoney/AKShare query exactly.
    filtered = fetch_window("2000-01-01", "2027-01-01", code=module.CODE)
    filtered_target = [
        item for item in filtered if str(item.get("stockCode") or "") == module.CODE
    ]
    if filtered_target:
        collected.extend(filtered_target)
        print("FILTERED_QUERY_ACCEPTED", len(filtered_target), flush=True)
    else:
        print("FILTERED_QUERY_IGNORED_OR_EMPTY; USING NARROW DATE WINDOWS", flush=True)

    # The public endpoint has at times ignored the stock-code parameter. Query small
    # date windows around the known publication dates, then apply the stock-code filter locally.
    for target in module.TARGETS:
        center = dt.date.fromisoformat(str(target["preferred_date"]))
        begin = (center - dt.timedelta(days=3)).isoformat()
        end = (center + dt.timedelta(days=3)).isoformat()
        rows = fetch_window(begin, end)
        window_target = [
            item for item in rows if str(item.get("stockCode") or "") == module.CODE
        ]
        print(
            "LOCAL_CODE_FILTER",
            target["preferred_date"],
            len(window_target),
            [
                {
                    "date": str(item.get("publishDate") or "")[:10],
                    "org": item.get("orgSName"),
                    "pages": item.get("attachPages"),
                    "infoCode": item.get("infoCode"),
                    "title": item.get("title"),
                }
                for item in window_target
            ],
            flush=True,
        )
        collected.extend(window_target)

    unique: dict[str, dict[str, Any]] = {}
    for item in collected:
        info_code = str(item.get("infoCode") or "")
        if info_code:
            unique[info_code] = item
    records = list(unique.values())
    if not records:
        raise RuntimeError("No Henghe Precision reports found after local stock-code filtering")

    print("REPORT_COUNT", len(records), flush=True)
    for item in sorted(records, key=lambda row: str(row.get("publishDate") or ""), reverse=True):
        print(
            "REPORT",
            str(item.get("publishDate") or "")[:10],
            item.get("stockCode"),
            item.get("stockName"),
            item.get("orgSName"),
            item.get("attachPages"),
            item.get("infoCode"),
            item.get("title"),
            flush=True,
        )
    Path("report_catalog.json").write_text(
        json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return records


module.list_reports = patched_list_reports
module.main()

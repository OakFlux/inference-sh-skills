from __future__ import annotations

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


def patched_list_reports() -> list[dict[str, Any]]:
    variants = [
        ("stockCodes", module.CODE, "2022-01-01"),
        ("stockCodes", module.CODE, "2000-01-01"),
        ("code", module.CODE, "2022-01-01"),
        ("code", module.CODE, "2000-01-01"),
    ]
    all_records: list[dict[str, Any]] = []
    selected_variant: tuple[str, str, str] | None = None

    for key, value, begin in variants:
        first_params = {
            "industryCode": "*",
            "pageSize": "100",
            "industry": "*",
            "rating": "*",
            "ratingChange": "*",
            "beginTime": begin,
            "endTime": module.AS_OF,
            "pageNo": "1",
            "fields": "",
            "qType": "0",
            "orgCode": "",
            "rcode": "",
            "p": "1",
            "pageNum": "1",
            "pageNumber": "1",
            "author": "",
            key: value,
        }
        response = module.request_with_retry(module.REPORT_API, params=first_params)
        try:
            raw_text = response.text
            payload = module.parse_json_or_jsonp(raw_text)
        finally:
            response.close()
        rows = extract_rows(payload)
        print("API_VARIANT", key, begin, "ROWS", len(rows), "RAW", raw_text[:500], flush=True)
        if not rows:
            continue

        selected_variant = (key, value, begin)
        all_records.extend(rows)
        total_page = 1
        if isinstance(payload, dict):
            total_page = int(payload.get("TotalPage") or payload.get("totalPage") or 1)
        for page in range(2, min(total_page, 20) + 1):
            params = dict(first_params)
            params.update(
                {
                    "pageNo": str(page),
                    "p": str(page),
                    "pageNum": str(page),
                    "pageNumber": str(page),
                }
            )
            page_response = module.request_with_retry(module.REPORT_API, params=params)
            try:
                page_payload = module.parse_json_or_jsonp(page_response.text)
            finally:
                page_response.close()
            page_rows = extract_rows(page_payload)
            print("REPORT_PAGE", page, len(page_rows), flush=True)
            if not page_rows:
                break
            all_records.extend(page_rows)
        break

    if not all_records:
        raise RuntimeError("Eastmoney report API returned no records for all code/stockCodes variants")

    unique: dict[str, dict[str, Any]] = {}
    for item in all_records:
        info_code = str(item.get("infoCode") or "")
        if info_code:
            unique[info_code] = item
    records = list(unique.values())
    print("SELECTED_API_VARIANT", selected_variant, flush=True)
    print("REPORT_COUNT", len(records), flush=True)
    for item in sorted(records, key=lambda row: str(row.get("publishDate") or ""), reverse=True):
        print(
            "REPORT",
            str(item.get("publishDate") or "")[:10],
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

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

import requests

OUT = Path("longban_media_report_inventory.json")
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/152.0.0.0 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
    "Referer": "https://data.eastmoney.com/report/605577.html",
}


def parse_json_or_jsonp(text: str) -> Any:
    text = text.strip()
    try:
        return json.loads(text)
    except Exception:
        match = re.search(r"^[^(]*\((.*)\)\s*;?\s*$", text, re.S)
        if not match:
            raise
        return json.loads(match.group(1))


def request_inventory(session: requests.Session) -> dict[str, Any]:
    url = "https://reportapi.eastmoney.com/report/list"
    parameter_sets = [
        {
            "industryCode": "*",
            "pageSize": "100",
            "industry": "*",
            "rating": "*",
            "ratingChange": "*",
            "beginTime": "2020-01-01",
            "endTime": "2026-10-04",
            "fields": "",
            "qType": "0",
            "orgCode": "",
            "code": "605577",
            "pageNo": "1",
        },
        {
            "cb": "datatable123456",
            "industryCode": "*",
            "pageSize": "100",
            "industry": "*",
            "rating": "*",
            "ratingChange": "*",
            "beginTime": "2020-01-01",
            "endTime": "2026-10-04",
            "fields": "",
            "qType": "0",
            "orgCode": "",
            "code": "605577",
            "pageNo": "1",
        },
    ]
    attempts: list[dict[str, Any]] = []
    payload: dict[str, Any] | None = None
    for params in parameter_sets:
        try:
            response = session.get(url, params=params, timeout=120)
            record: dict[str, Any] = {
                "url": response.url,
                "status": response.status_code,
                "bytes": len(response.content),
                "content_type": response.headers.get("content-type"),
                "prefix": response.text[:1000],
            }
            try:
                parsed = parse_json_or_jsonp(response.text)
                record["parsed_type"] = type(parsed).__name__
                if isinstance(parsed, dict):
                    record["keys"] = list(parsed.keys())
                    data = parsed.get("data") or parsed.get("result") or []
                    record["data_count"] = len(data) if isinstance(data, list) else None
                    if data:
                        payload = parsed
            except Exception as exc:
                record["parse_error"] = repr(exc)
            attempts.append(record)
            print("REPORT_API", json.dumps(record, ensure_ascii=False), flush=True)
            if payload:
                break
        except Exception as exc:
            attempts.append({"params": params, "error": repr(exc)})
            print("REPORT_API_ERROR", repr(exc), flush=True)
    if payload is None:
        return {"attempts": attempts, "records": []}
    data = payload.get("data") or payload.get("result") or []
    return {"attempts": attempts, "raw_payload": payload, "records": data}


def test_pdf_candidates(session: requests.Session, record: dict[str, Any]) -> list[dict[str, Any]]:
    info_code = str(
        record.get("infoCode")
        or record.get("infoCodeFull")
        or record.get("reportId")
        or record.get("id")
        or ""
    ).strip()
    if not info_code:
        return []
    now_ms = int(time.time() * 1000)
    candidates = [
        f"https://pdf.dfcfw.com/pdf/H3_{info_code}_1.pdf",
        f"https://pdf.dfcfw.com/pdf/H3_{info_code}_1.pdf?{now_ms}.pdf=",
        f"http://pdf.dfcfw.com/pdf/H3_{info_code}_1.pdf",
    ]
    results: list[dict[str, Any]] = []
    for candidate in candidates:
        try:
            headers = dict(HEADERS)
            headers["Range"] = "bytes=0-4095"
            response = session.get(candidate, headers=headers, timeout=90, allow_redirects=True)
            item = {
                "candidate": candidate,
                "status": response.status_code,
                "final_url": response.url,
                "bytes": len(response.content),
                "content_type": response.headers.get("content-type"),
                "content_length": response.headers.get("content-length"),
                "accept_ranges": response.headers.get("accept-ranges"),
                "prefix_hex": response.content[:16].hex(),
            }
            results.append(item)
            print("PDF_TEST", info_code, json.dumps(item, ensure_ascii=False), flush=True)
            if response.status_code in (200, 206) and response.content.startswith(b"%PDF-"):
                break
        except Exception as exc:
            item = {"candidate": candidate, "error": repr(exc)}
            results.append(item)
            print("PDF_TEST_ERROR", info_code, json.dumps(item, ensure_ascii=False), flush=True)
    return results


def main() -> None:
    session = requests.Session()
    session.headers.update(HEADERS)
    inventory = request_inventory(session)
    records = inventory.get("records") or []
    enriched: list[dict[str, Any]] = []
    for index, row in enumerate(records, start=1):
        row_copy = dict(row)
        row_copy["pdf_tests"] = test_pdf_candidates(session, row_copy)
        enriched.append(row_copy)
        print("REPORT_RECORD", index, json.dumps(row_copy, ensure_ascii=False), flush=True)
    inventory["records"] = enriched
    OUT.write_text(json.dumps(inventory, ensure_ascii=False, indent=2), encoding="utf-8")
    print("INVENTORY_WRITTEN", OUT, len(enriched), flush=True)


if __name__ == "__main__":
    main()

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import requests

OUT = Path("air_china_cargo_report_inventory.json")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/152.0.0.0 Safari/537.36"
HEADERS = {
    "User-Agent": UA,
    "Referer": "https://data.eastmoney.com/report/stock.jshtml",
    "Accept": "application/json,text/plain,*/*",
}


def decode_payload(text: str) -> Any:
    text = text.strip().lstrip("\ufeff")
    try:
        return json.loads(text)
    except Exception:
        match = re.match(r"^[^(]+\((.*)\)\s*;?\s*$", text, re.S)
        if match:
            return json.loads(match.group(1))
        raise


def collect_records(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        for key in ("data", "Data", "result", "Result"):
            if key in value:
                nested = collect_records(value[key])
                if nested:
                    return nested
        for key in ("list", "List", "records", "Records", "items", "Items"):
            rows = value.get(key)
            if isinstance(rows, list) and rows and isinstance(rows[0], dict):
                return rows
        rows: list[dict[str, Any]] = []
        for child in value.values():
            rows.extend(collect_records(child))
        return rows
    if isinstance(value, list):
        return [x for x in value if isinstance(x, dict)]
    return []


def query(session: requests.Session, method: str, endpoint: str, label: str) -> dict[str, Any]:
    params = {
        "cb": "datatable123456",
        "industryCode": "*",
        "pageSize": "100",
        "industry": "*",
        "rating": "*",
        "ratingChange": "*",
        "beginTime": "2024-01-01",
        "endTime": "2026-09-27",
        "pageNo": "1",
        "fields": "",
        "qType": "0",
        "orgCode": "",
        "code": "001391",
        "rcode": "",
        "p": "1",
        "pageNum": "1",
        "pageNumber": "1",
    }
    url = f"https://reportapi.eastmoney.com/report/{endpoint}"
    if method == "GET":
        response = session.get(url, params=params, timeout=90)
    else:
        response = session.post(url, params=params, data=params, timeout=90)
    result: dict[str, Any] = {
        "label": label,
        "method": method,
        "url": response.url,
        "status": response.status_code,
        "bytes": len(response.content),
        "content_type": response.headers.get("content-type"),
        "text_prefix": response.text[:1000],
    }
    print("QUERY", json.dumps(result, ensure_ascii=False), flush=True)
    try:
        payload = decode_payload(response.text)
        rows = collect_records(payload)
        result["payload"] = payload
        result["row_count"] = len(rows)
        result["rows"] = rows
        print("ROWS", label, len(rows), flush=True)
        for row in rows:
            print("REPORT", json.dumps(row, ensure_ascii=False), flush=True)
    except Exception as exc:
        result["parse_error"] = repr(exc)
        print("PARSE_ERROR", label, repr(exc), flush=True)
    return result


def main() -> None:
    session = requests.Session()
    session.headers.update(HEADERS)
    attempts = []
    for endpoint in ("list", "list2"):
        for method in ("GET", "POST"):
            try:
                attempts.append(query(session, method, endpoint, f"{endpoint}-{method.lower()}"))
            except Exception as exc:
                attempts.append({"label": f"{endpoint}-{method.lower()}", "error": repr(exc)})
                print("ERROR", endpoint, method, repr(exc), flush=True)
    OUT.write_text(json.dumps({"attempts": attempts}, ensure_ascii=False, indent=2), encoding="utf-8")
    print("WROTE", OUT, OUT.stat().st_size, flush=True)


if __name__ == "__main__":
    main()

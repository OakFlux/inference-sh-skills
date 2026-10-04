from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

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


def data_from_payload(parsed: Any) -> list[dict[str, Any]]:
    if not isinstance(parsed, dict):
        return []
    for key in ("data", "result", "list", "rows"):
        value = parsed.get(key)
        if isinstance(value, list):
            return value
        if isinstance(value, dict):
            for nested in ("data", "list", "rows"):
                nested_value = value.get(nested)
                if isinstance(nested_value, list):
                    return nested_value
    return []


def inspect_page_scripts(session: requests.Session) -> dict[str, Any]:
    page_url = "https://data.eastmoney.com/report/605577.html"
    result: dict[str, Any] = {"page_url": page_url, "scripts": [], "matches": []}
    try:
        response = session.get(page_url, timeout=120)
        result.update({
            "status": response.status_code,
            "bytes": len(response.content),
            "content_type": response.headers.get("content-type"),
        })
        html = response.text
        script_urls = [urljoin(response.url, src) for src in re.findall(r'<script[^>]+src=["\']([^"\']+)["\']', html, re.I)]
        result["scripts"] = script_urls
        for script_url in script_urls:
            try:
                script = session.get(script_url, timeout=120)
                text = script.text
                if any(token.lower() in text.lower() for token in ("reportapi", "/report/list", "qType", "report/list")):
                    excerpts = []
                    for token in ("reportapi", "/report/list", "qType"):
                        for match in re.finditer(re.escape(token), text, re.I):
                            excerpts.append(text[max(0, match.start() - 500): match.start() + 1200])
                            if len(excerpts) >= 8:
                                break
                        if len(excerpts) >= 8:
                            break
                    item = {
                        "url": script_url,
                        "status": script.status_code,
                        "bytes": len(script.content),
                        "excerpts": excerpts,
                    }
                    result["matches"].append(item)
                    print("SCRIPT_MATCH", json.dumps(item, ensure_ascii=False)[:8000], flush=True)
            except Exception as exc:
                result.setdefault("script_errors", []).append({"url": script_url, "error": repr(exc)})
    except Exception as exc:
        result["error"] = repr(exc)
    return result


def request_inventory(session: requests.Session) -> dict[str, Any]:
    endpoints = [
        "https://reportapi.eastmoney.com/report/list",
        "http://reportapi.eastmoney.com/report/list",
        "https://reportapi.eastmoney.com/report/list2",
    ]
    codes = ["605577", "SH605577", "sh605577", "605577.SH"]
    qtypes = ["0", "1"]
    date_ranges = [
        ("2023-01-01", "2023-12-31"),
        ("2022-01-01", "2024-12-31"),
        ("2023-01-01", "2024-12-31"),
        ("2020-01-01", "2024-12-31"),
        ("2020-01-01", "2026-10-04"),
    ]
    attempts: list[dict[str, Any]] = []
    deduped: dict[str, dict[str, Any]] = {}
    for endpoint in endpoints:
        for code in codes:
            for qtype in qtypes:
                for begin, end in date_ranges:
                    params = {
                        "industryCode": "*",
                        "pageSize": "100",
                        "industry": "*",
                        "rating": "*",
                        "ratingChange": "*",
                        "beginTime": begin,
                        "endTime": end,
                        "fields": "",
                        "qType": qtype,
                        "orgCode": "",
                        "code": code,
                        "pageNo": "1",
                    }
                    try:
                        response = session.get(endpoint, params=params, timeout=90)
                        parsed: Any = None
                        parse_error = None
                        try:
                            parsed = parse_json_or_jsonp(response.text)
                        except Exception as exc:
                            parse_error = repr(exc)
                        rows = data_from_payload(parsed)
                        record: dict[str, Any] = {
                            "endpoint": endpoint,
                            "code": code,
                            "qType": qtype,
                            "begin": begin,
                            "end": end,
                            "status": response.status_code,
                            "bytes": len(response.content),
                            "content_type": response.headers.get("content-type"),
                            "row_count": len(rows),
                            "prefix": response.text[:400],
                        }
                        if parse_error:
                            record["parse_error"] = parse_error
                        attempts.append(record)
                        if rows:
                            print("REPORT_API_HIT", json.dumps(record, ensure_ascii=False), flush=True)
                            for row in rows:
                                key = str(row.get("infoCode") or row.get("reportId") or row.get("id") or row)
                                deduped[key] = dict(row)
                        elif len(attempts) <= 20:
                            print("REPORT_API_MISS", json.dumps(record, ensure_ascii=False), flush=True)
                    except Exception as exc:
                        attempts.append({
                            "endpoint": endpoint,
                            "code": code,
                            "qType": qtype,
                            "begin": begin,
                            "end": end,
                            "error": repr(exc),
                        })
    return {"attempts": attempts, "records": list(deduped.values())}


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
    inventory["page_script_inspection"] = inspect_page_scripts(session)
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

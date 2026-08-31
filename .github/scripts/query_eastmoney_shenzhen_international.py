from __future__ import annotations

import json
import time

import requests

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151 Safari/537.36"
)

session = requests.Session()
session.headers.update(
    {
        "User-Agent": UA,
        "Referer": "https://data.eastmoney.com/report/stock.jshtml",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
)

DATE_RANGES = [
    ("2022-07-16", "2022-07-21"),
    ("2024-08-08", "2024-08-13"),
    ("2025-04-15", "2025-04-21"),
    ("2025-06-21", "2025-06-27"),
]

TITLE_MARKERS = (
    "深圳国际",
    "土地转性贡献弹性",
    "国企优质资源禀赋",
    "掌握湾区优质资产",
    "华南物流园增值添利",
)


def fetch(endpoint: str, begin: str, end: str, qtype: str) -> list[dict]:
    found: list[dict] = []
    for page in range(1, 31):
        params = {
            "pageSize": "100",
            "pageNo": str(page),
            "beginTime": begin,
            "endTime": end,
            "qType": qtype,
            "fields": "",
            "industryCode": "*",
            "industry": "*",
            "rating": "*",
            "ratingChange": "*",
            "orgCode": "",
            "code": "",
            "rcode": "",
            "p": str(page),
            "pageNum": str(page),
            "pageNumber": str(page),
        }
        response = session.get(endpoint, params=params, timeout=(20, 120))
        print("REQUEST", response.url, "STATUS", response.status_code)
        response.raise_for_status()
        payload = response.json()
        rows = payload.get("data") or []
        total = (
            payload.get("TotalCount")
            or payload.get("total")
            or payload.get("hits")
            or payload.get("count")
        )
        print("PAGE", page, "ROWS", len(rows), "TOTAL", total)
        for row in rows:
            hay = " ".join(
                str(row.get(key) or "")
                for key in (
                    "title",
                    "stockName",
                    "stockCode",
                    "secuName",
                    "secuCode",
                    "orgSName",
                    "researcher",
                )
            )
            if any(marker in hay for marker in TITLE_MARKERS):
                found.append(row)
                print("MATCH", json.dumps(row, ensure_ascii=False))
        if not rows or len(rows) < 100:
            break
        time.sleep(0.8)
    return found


all_matches: dict[str, dict] = {}
for endpoint in (
    "https://reportapi.eastmoney.com/report/list2",
    "https://reportapi.eastmoney.com/report/list",
):
    for qtype in ("0", "1", "2", "3"):
        for begin, end in DATE_RANGES:
            print("\n===", endpoint, "QTYPE", qtype, begin, end, "===")
            try:
                matches = fetch(endpoint, begin, end, qtype)
            except Exception as exc:
                print("ERROR", repr(exc))
                continue
            for row in matches:
                key = str(
                    row.get("infoCode")
                    or row.get("encodeUrl")
                    or json.dumps(row, ensure_ascii=False, sort_keys=True)
                )
                all_matches[key] = row

print("\n=== ALL UNIQUE MATCHES", len(all_matches), "===")
for key, row in all_matches.items():
    print("KEY", key)
    print(json.dumps(row, ensure_ascii=False, indent=2))
    info_code = str(row.get("infoCode") or "")
    if info_code:
        pdf_url = f"https://pdf.dfcfw.com/pdf/H3_{info_code}_1.pdf"
        try:
            response = session.get(
                pdf_url,
                headers={"Referer": "https://data.eastmoney.com/"},
                timeout=(20, 120),
                stream=True,
            )
            first = next(response.iter_content(16), b"")
            print(
                "PDF_PROBE",
                pdf_url,
                response.status_code,
                response.headers.get("Content-Type"),
                response.headers.get("Content-Length"),
                repr(first),
            )
        except Exception as exc:
            print("PDF_PROBE_ERROR", pdf_url, repr(exc))

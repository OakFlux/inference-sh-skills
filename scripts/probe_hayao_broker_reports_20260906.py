#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import time
from pathlib import Path

import requests

API = "https://reportapi.eastmoney.com/report/list"
STOCK_CODE = "600664"
COMPANY = "哈药股份"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/151 Safari/537.36"

session = requests.Session()
session.headers.update({
    "User-Agent": UA,
    "Referer": "https://data.eastmoney.com/",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
})


def query(begin: str, end: str, qtype: int, code: str) -> list[dict]:
    rows: list[dict] = []
    page = 1
    total_pages = 1
    while page <= total_pages:
        params = {
            "industryCode": "*",
            "pageSize": "100",
            "industry": "*",
            "rating": "*",
            "ratingChange": "*",
            "beginTime": begin,
            "endTime": end,
            "pageNo": str(page),
            "fields": "",
            "qType": str(qtype),
            "orgCode": "",
            "code": code,
            "rcode": "",
            "p": str(page),
            "pageNum": str(page),
            "pageNumber": str(page),
        }
        r = session.get(API, params=params, timeout=(30, 180))
        print("QUERY", begin, end, qtype, code, page, r.status_code, len(r.content), flush=True)
        r.raise_for_status()
        payload = r.json()
        total_pages = int(payload.get("TotalPage") or 1)
        batch = payload.get("data") or []
        rows.extend(batch)
        page += 1
        time.sleep(0.1)
    return rows


def fetch_pdf(info_code: str) -> dict:
    urls = [
        f"https://pdf.dfcfw.com/pdf/H3_{info_code}_1.pdf",
        f"https://pdf.dfcfw.com/pdf/H3_{info_code}_1.pdf?{int(time.time())}",
    ]
    errors = []
    for url in urls:
        try:
            r = session.get(
                url,
                headers={
                    "User-Agent": UA,
                    "Referer": "https://data.eastmoney.com/report/",
                    "Accept": "application/pdf,application/octet-stream;q=0.9,*/*;q=0.8",
                },
                timeout=(30, 300),
                allow_redirects=True,
            )
            ok = r.status_code == 200 and r.content.startswith(b"%PDF-")
            print("PDF", info_code, r.status_code, r.headers.get("content-type"), len(r.content), ok, url, flush=True)
            if ok:
                path = Path("hayao-probe-pdfs") / f"{info_code}.pdf"
                path.parent.mkdir(exist_ok=True)
                path.write_bytes(r.content)
                return {"ok": True, "url": r.url, "bytes": len(r.content), "path": str(path)}
            errors.append(f"{url}: {r.status_code}/{len(r.content)}")
        except Exception as exc:
            errors.append(f"{url}: {exc!r}")
    return {"ok": False, "errors": errors}


def main() -> None:
    collected: dict[str, dict] = {}

    # First query the company directly in yearly windows. This is the cleanest route.
    for year in range(2015, 2027):
        end = "2026-09-06" if year == 2026 else f"{year}-12-31"
        begin = f"{year}-01-01"
        for qtype in (0, 1, 2):
            try:
                rows = query(begin, end, qtype, STOCK_CODE)
            except Exception as exc:
                print("DIRECT QUERY ERROR", year, qtype, repr(exc), flush=True)
                continue
            for row in rows:
                info = str(row.get("infoCode") or "").strip()
                if not info:
                    continue
                hay = " ".join(str(row.get(k) or "") for k in ("stockName", "stockCode", "title"))
                if COMPANY in hay or STOCK_CODE in hay:
                    collected[info] = row

    # Fallback broad windows around known report publication dates and recent years.
    fallback_windows = [
        ("2025-01-01", "2025-12-31"),
        ("2024-01-01", "2024-12-31"),
        ("2023-01-01", "2023-12-31"),
        ("2022-01-01", "2022-12-31"),
        ("2021-01-01", "2021-12-31"),
        ("2020-01-01", "2020-12-31"),
        ("2019-01-01", "2019-12-31"),
    ]
    for begin, end in fallback_windows:
        for qtype in (0, 1, 2):
            try:
                rows = query(begin, end, qtype, "")
            except Exception as exc:
                print("BROAD QUERY ERROR", begin, end, qtype, repr(exc), flush=True)
                continue
            for row in rows:
                info = str(row.get("infoCode") or "").strip()
                if not info:
                    continue
                hay = " ".join(str(row.get(k) or "") for k in ("stockName", "stockCode", "title"))
                if COMPANY in hay or STOCK_CODE in hay:
                    collected[info] = row

    reports = list(collected.values())
    reports.sort(
        key=lambda r: (
            int(r.get("attachPages") or 0),
            str(r.get("publishDate") or ""),
        ),
        reverse=True,
    )

    print("TOTAL REPORTS", len(reports), flush=True)
    for row in reports:
        print("REPORT", json.dumps(row, ensure_ascii=False, default=str), flush=True)

    # Probe up to the 20 longest reports with at least 6 pages.
    probed = []
    for row in [r for r in reports if int(r.get("attachPages") or 0) >= 6][:20]:
        info = str(row.get("infoCode") or "")
        result = fetch_pdf(info)
        probed.append({"record": row, "download": result})

    Path("hayao-broker-report-probe.json").write_text(
        json.dumps({"reports": reports, "probed": probed}, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()

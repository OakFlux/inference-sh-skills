from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import package_biyi_broker_reports as base


# Reuse the verified downloader/validator, but replace all company-specific state.
base.PACKAGE = base.ROOT / "hengxuan_broker_reports_verified"
base.REPORT_DIR = base.PACKAGE / "01_券商深度报告"
base.REPORT_DIR.mkdir(parents=True, exist_ok=True)
base.OUTPUT = base.ROOT / "恒玄科技_券商深度报告_精选_完整PDF.zip"
base.STOCK_CODE = "688608"
base.COMPANY = "恒玄科技（上海）股份有限公司"
base.SHORT_NAME = "恒玄科技"
base.PREPARED_DATE = "2026-08-30"


def fetch_report_records() -> list[dict[str, Any]]:
    url = "https://reportapi.eastmoney.com/report/list"
    timestamp = int(time.time() * 1000)
    params = {
        "industryCode": "*",
        "pageSize": "100",
        "industry": "*",
        "rating": "*",
        "ratingChange": "*",
        "companyType": "*",
        "beginTime": "2000-01-01",
        "endTime": "2030-01-01",
        "pageNo": "1",
        "fields": "",
        "qType": "0",
        "orgCode": "",
        "code": base.STOCK_CODE,
        "rcode": "",
        "p": "1",
        "pageNum": "1",
        "pageNumber": "1",
        "_": str(timestamp),
    }
    response = base.session.get(
        url,
        params=params,
        headers={
            "Referer": "https://data.eastmoney.com/report/",
            "Accept": "application/json,text/javascript,*/*;q=0.9",
        },
        timeout=(30, 180),
    )
    if response.status_code != 200:
        raise RuntimeError(
            f"Eastmoney API HTTP {response.status_code}: {response.text[:1000]}"
        )

    text = response.text.strip()
    if text.startswith("{"):
        payload = json.loads(text)
    else:
        left = text.find("(")
        right = text.rfind(")")
        if left < 0 or right <= left:
            raise RuntimeError(f"Unexpected API response: {text[:1000]}")
        payload = json.loads(text[left + 1 : right])

    raw_records: list[Any] = []
    if isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, list):
            raw_records = data
        elif isinstance(data, dict):
            for key in ("data", "list", "items"):
                value = data.get(key)
                if isinstance(value, list):
                    raw_records = value
                    break
        if not raw_records:
            for key in ("result", "list", "items"):
                value = payload.get(key)
                if isinstance(value, list):
                    raw_records = value
                    break
    elif isinstance(payload, list):
        raw_records = payload

    if not raw_records:
        raise RuntimeError(
            "Eastmoney API returned no report list; payload keys="
            + (str(list(payload.keys())) if isinstance(payload, dict) else str(type(payload)))
        )

    records: list[dict[str, Any]] = []
    for raw in raw_records:
        if not isinstance(raw, dict):
            continue
        info_code = str(
            raw.get("infoCode")
            or raw.get("infocode")
            or raw.get("INFOCODE")
            or ""
        ).strip()
        title = str(raw.get("title") or raw.get("TITLE") or "").strip()
        if not info_code.startswith("AP") or not title:
            continue
        records.append(
            {
                "info_code": info_code,
                "title": title,
                "broker": str(
                    raw.get("orgSName")
                    or raw.get("orgName")
                    or raw.get("ORG_SNAME")
                    or "未知券商"
                ).strip(),
                "publish_date": str(
                    raw.get("publishDate")
                    or raw.get("publishDateStr")
                    or raw.get("PUBLISH_DATE")
                    or ""
                ).strip()[:10],
                "researcher": str(
                    raw.get("researcher")
                    or raw.get("researcherName")
                    or raw.get("RESEARCHER")
                    or ""
                ).strip(),
                "metadata": raw,
            }
        )

    unique = {record["info_code"]: record for record in records}
    result = list(unique.values())
    print(f"Eastmoney API records: {len(result)}")
    for record in result:
        attach_pages = record["metadata"].get("attachPages")
        print(
            f"{record['info_code']} | {record['publish_date']} | "
            f"{record['broker']} | pages={attach_pages} | {record['title']}"
        )
    return result


def quality_score(record: dict[str, Any], pages: int) -> float:
    title = base.normalize(record["title"])
    score = float(pages)
    if "深度" in title:
        score += 160
    if "首次覆盖" in title or "新股专题" in title or "专题覆盖" in title:
        score += 110
    if any(keyword in title for keyword in (
        "智能音频", "蓝牙", "可穿戴", "端侧ai", "低功耗", "soc", "芯片平台"
    )):
        score += 35
    if any(keyword in title for keyword in (
        "点评", "一季报", "半年报", "三季报", "年报点评", "快报",
        "股权激励", "调研", "业绩预告", "业绩快报"
    )):
        score -= 130
    if pages >= 35:
        score += 60
    elif pages >= 25:
        score += 45
    elif pages >= 18:
        score += 25
    elif pages >= 12:
        score += 10
    return score


base.fetch_report_records = fetch_report_records
base.quality_score = quality_score
base.main()

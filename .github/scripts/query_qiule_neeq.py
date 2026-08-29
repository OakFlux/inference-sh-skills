from __future__ import annotations

import json
from typing import Any

import requests

ENDPOINT = "https://www.neeq.com.cn/disclosureInfoController/companyAnnouncement.do"
NEED_FIELDS = [
    "companyCd",
    "companyName",
    "disclosureTitle",
    "disclosurePostTitle",
    "destFilePath",
    "publishDate",
    "xxfcbj",
    "fileExt",
    "xxzrlx",
]


def parse_jsonp(text: str) -> dict[str, Any]:
    start = text.find("(")
    end = text.rfind(")")
    if start < 0 or end <= start:
        raise RuntimeError(f"Invalid JSONP response: {text[:500]!r}")
    payload = json.loads(text[start + 1 : end])
    if isinstance(payload, list):
        if not payload:
            return {}
        payload = payload[0]
    if not isinstance(payload, dict):
        raise RuntimeError(f"Unexpected payload type: {type(payload)!r}")
    return payload


def query(company_code: str, keyword: str = "") -> list[dict[str, Any]]:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/151 Safari/537.36",
            "Accept-Language": "zh-CN,zh;q=0.9",
        }
    )
    records: list[dict[str, Any]] = []
    page_number = 0
    total_pages = 1
    while page_number < total_pages:
        data: list[tuple[str, str]] = [
            ("noticeType[]", "5"),
            ("disclosureType[]", "5"),
            ("disclosureSubtype[]", ""),
            ("page", "" if page_number == 0 else str(page_number)),
            ("companyCd", company_code),
            ("isNewThree", "1"),
            ("keyword", keyword),
            ("xxfcbj[]", "3"),
            ("hyType[]", ""),
        ]
        data.extend(("needFields[]", field) for field in NEED_FIELDS)
        data.extend(
            [
                ("siteId", "1"),
                ("sortfield", "xxssdq"),
                ("sorttype", "asc"),
            ]
        )
        response = session.post(
            ENDPOINT,
            params={"callback": "qiuleCallback"},
            data=data,
            headers={
                "Referer": "https://www.neeq.com.cn/disclosure/announcement.html",
                "X-Requested-With": "XMLHttpRequest",
                "Accept": "text/javascript, application/javascript, */*; q=0.01",
            },
            timeout=(25, 120),
        )
        response.raise_for_status()
        payload = parse_jsonp(response.text)
        list_info = payload.get("listInfo") or {}
        content = list_info.get("content") or []
        if not isinstance(content, list):
            raise RuntimeError("Invalid content list")
        records.extend(content)
        total_pages = int(list_info.get("totalPages") or 1)
        page_number += 1
    return records


def main() -> None:
    all_records: list[dict[str, Any]] = []
    for code in ("831087", "920087"):
        for keyword in ("2014年年度报告", "年度报告", "半年度报告"):
            try:
                records = query(code, keyword)
                print(f"QUERY code={code} keyword={keyword!r}: {len(records)} records")
                all_records.extend(records)
            except Exception as exc:
                print(f"QUERY_ERROR code={code} keyword={keyword!r}: {exc!r}")

    unique: dict[str, dict[str, Any]] = {}
    for record in all_records:
        key = str(record.get("destFilePath") or "") + "|" + str(record.get("disclosureTitle") or "")
        unique[key] = record

    selected = []
    for record in unique.values():
        title = str(record.get("disclosureTitle") or "") + str(record.get("disclosurePostTitle") or "")
        if "秋乐种业" not in title and "河南秋乐种业科技" not in title:
            continue
        if "年度报告" not in title and "半年度报告" not in title:
            continue
        selected.append(record)

    selected.sort(key=lambda item: (str(item.get("publishDate") or ""), str(item.get("disclosureTitle") or "")))
    print("SELECTED_RECORDS_JSON_BEGIN")
    print(json.dumps(selected, ensure_ascii=False, indent=2))
    print("SELECTED_RECORDS_JSON_END")


if __name__ == "__main__":
    main()

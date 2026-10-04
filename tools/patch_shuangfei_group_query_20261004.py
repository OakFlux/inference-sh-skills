from pathlib import Path
import re

path = Path("tools/package_shuangfei_group_filings_20261004.py")
text = path.read_text(encoding="utf-8")

new_query_once = r'''def query_once(
    session: requests.Session,
    *,
    category: str,
    searchkey: str,
    date_range: str = DATE_RANGE,
    max_pages: int = 30,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    seen_page_fingerprints: set[tuple[str, ...]] = set()
    page_num = 1
    while True:
        data = {
            "pageNum": str(page_num),
            "pageSize": "50",
            "column": "szse",
            "tabName": "fulltext",
            "plate": "sz",
            "stock": "",
            "searchkey": searchkey,
            "secid": "",
            "category": category,
            "trade": "",
            "seDate": date_range,
            "sortName": "",
            "sortType": "",
            "isHLtitle": "true",
        }
        response = session.post(CNINFO_QUERY_URL, data=data, headers=HEADERS, timeout=(30, 120))
        print("QUERY", category or "ALL", searchkey, page_num, response.status_code, len(response.content), flush=True)
        response.raise_for_status()
        payload = response.json()
        rows = payload.get("announcements") or []
        print("QUERY_ROWS", category or "ALL", searchkey, page_num, len(rows), flush=True)
        fingerprint = tuple(str(row.get("announcementId") or row.get("adjunctUrl") or "") for row in rows)
        if fingerprint and fingerprint in seen_page_fingerprints:
            print("QUERY_REPEATED_PAGE_BREAK", category or "ALL", searchkey, page_num, flush=True)
            break
        if fingerprint:
            seen_page_fingerprints.add(fingerprint)
        records.extend(rows)
        total_pages = int(payload.get("totalpages") or 1)
        if page_num >= total_pages or not rows:
            break
        page_num += 1
        if page_num > max_pages:
            raise RuntimeError(f"CNINFO pagination exceeded safety limit: category={category!r} search={searchkey!r}")
    return records
'''

new_query_company = r'''def query_company(session: requests.Session, category: str, *, allow_all_category: bool = False) -> list[dict[str, Any]]:
    # The issuer changed from 浙江双飞无油轴承股份有限公司 to
    # 双飞无油轴承集团股份有限公司, while the stock abbreviation also changed.
    # Query every historical/current name rather than stopping after the first hit.
    search_terms = [
        "双飞集团",
        "双飞股份",
        "浙江双飞",
        "双飞无油轴承",
        "300817",
    ]
    combined: dict[str, dict[str, Any]] = {}

    def collect(cat: str) -> None:
        for term in search_terms:
            rows = query_once(session, category=cat, searchkey=term)
            for row in rows:
                sec_code = str(row.get("secCode") or "")
                if sec_code != STOCK_CODE:
                    continue
                key = str(row.get("announcementId") or row.get("adjunctUrl") or "")
                if key:
                    combined[key] = row

    collect(category)
    # The historical CNINFO prospectus category can return unrelated or incomplete rows.
    # For prospectuses, always supplement it with a full-text company search.
    if allow_all_category:
        collect("")
    print("QUERY_COMPANY_RESULT", category or "ALL", len(combined), flush=True)
    return list(combined.values())
'''

pattern_once = r"def query_once\(.*?(?=\ndef query_company)"
text, count_once = re.subn(pattern_once, new_query_once.rstrip() + "\n", text, count=1, flags=re.S)
if count_once != 1:
    raise SystemExit(f"query_once patch count={count_once}")

pattern_company = r"def query_company\(.*?(?=\ndef normalized_record)"
text, count_company = re.subn(pattern_company, new_query_company.rstrip() + "\n", text, count=1, flags=re.S)
if count_company != 1:
    raise SystemExit(f"query_company patch count={count_company}")

path.write_text(text, encoding="utf-8")
print("Patched Shuangfei historical-name queries, repeated-page detection, and full-text prospectus search")

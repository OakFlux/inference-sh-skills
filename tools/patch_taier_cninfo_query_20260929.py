from pathlib import Path
import re

path = Path("tools/package_taier_filings_20260929.py")
text = path.read_text(encoding="utf-8")

new_function = r'''def query_cninfo(session: requests.Session, category: str) -> list[dict[str, Any]]:
    strategies = [
        {"stock": f"{STOCK_CODE},{ORG_ID}", "searchkey": "", "label": "stock_org"},
        {"stock": "", "searchkey": COMPANY_SHORT, "label": "search_short"},
        {"stock": "", "searchkey": "泰尔重工", "label": "search_full"},
        {"stock": STOCK_CODE, "searchkey": "", "label": "stock_only"},
    ]
    for strategy in strategies:
        records: list[dict[str, Any]] = []
        page_num = 1
        while True:
            data = {
                "pageNum": str(page_num),
                "pageSize": "50",
                "column": "szse",
                "tabName": "fulltext",
                "plate": "sz",
                "stock": strategy["stock"],
                "searchkey": strategy["searchkey"],
                "secid": "",
                "category": category,
                "trade": "",
                "seDate": DATE_RANGE,
                "sortName": "",
                "sortType": "",
                "isHLtitle": "true",
            }
            response = session.post(CNINFO_QUERY_URL, data=data, headers=HEADERS, timeout=(30, 90))
            print("QUERY", category, strategy["label"], page_num, response.status_code, len(response.content), flush=True)
            response.raise_for_status()
            payload = response.json()
            rows = payload.get("announcements") or []
            print("QUERY_ROWS", category, strategy["label"], page_num, len(rows), flush=True)
            records.extend(rows)
            total_pages = int(payload.get("totalpages") or 1)
            if page_num >= total_pages or not rows:
                break
            page_num += 1
            if page_num > 20:
                raise RuntimeError(f"CNINFO pagination exceeded safety limit for {category}")
        filtered = [row for row in records if str(row.get("secCode") or "") == STOCK_CODE]
        if filtered:
            print("QUERY_STRATEGY_SUCCESS", category, strategy["label"], len(filtered), flush=True)
            return filtered
    return []
'''

pattern = r"def query_cninfo\(session: requests\.Session, category: str\) -> list\[dict\[str, Any\]\]:.*?(?=\ndef normalized_record)"
updated, count = re.subn(pattern, new_function.rstrip() + "\n", text, count=1, flags=re.S)
if count != 1:
    raise SystemExit(f"query_cninfo patch count={count}")
path.write_text(updated, encoding="utf-8")
print("Patched Taier CNINFO query fallbacks")

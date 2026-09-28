from pathlib import Path

path = Path("tools/package_jiejiaweic_filings_20260928.py")
text = path.read_text(encoding="utf-8")

start = text.index("def get_org_id(")
end = text.index("\ndef query_announcements(", start)
new_get_org = r'''def get_org_id(session: requests.Session) -> str:
    mapping_urls = [
        "https://www.cninfo.com.cn/new/data/szse_stock.json",
        "http://www.cninfo.com.cn/new/data/szse_stock.json",
    ]
    for url in mapping_urls:
        try:
            r = session.get(url, headers=HEADERS, timeout=120)
            print("STOCK_MAP", r.status_code, r.url, len(r.content), r.headers.get("content-type"), flush=True)
            r.raise_for_status()
            data = r.json()
            rows = data.get("stockList") if isinstance(data, dict) else data
            rows = rows or []
            for row in rows:
                if not isinstance(row, dict):
                    continue
                raw_code = str(row.get("code") or row.get("secCode") or row.get("stockCode") or "")
                sec_code = raw_code.zfill(6) if raw_code.isdigit() else raw_code
                sec_name = str(row.get("zwjc") or row.get("secName") or row.get("name") or "")
                org_id = str(row.get("orgId") or row.get("orgid") or row.get("orgID") or "")
                if org_id and (sec_code == CODE or COMPANY in sec_name):
                    print("ORG_ID_FROM_MAP", sec_code, sec_name, org_id, flush=True)
                    return org_id
        except Exception as exc:
            print("STOCK_MAP_ERROR", url, repr(exc), flush=True)

    # Current CNINFO installations may expose either detailOfQuery or query.
    endpoints = [
        "https://www.cninfo.com.cn/new/information/topSearch/detailOfQuery",
        "https://www.cninfo.com.cn/new/information/topSearch/query",
    ]
    for endpoint in endpoints:
        for keyword in (CODE, COMPANY):
            try:
                r = session.post(
                    endpoint,
                    data={"keyWord": keyword, "maxNum": 20},
                    headers={**HEADERS, "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"},
                    timeout=90,
                )
                print("TOP_SEARCH_POST", endpoint, keyword, r.status_code, len(r.content), flush=True)
                r.raise_for_status()
                data = r.json()
                rows = data if isinstance(data, list) else data.get("data") or data.get("result") or data.get("stockList") or []
                for row in rows:
                    if not isinstance(row, dict):
                        continue
                    sec_code = str(row.get("secCode") or row.get("stockCode") or row.get("code") or "")
                    sec_name = str(row.get("zwjc") or row.get("secName") or row.get("name") or "")
                    org_id = str(row.get("orgId") or row.get("orgid") or row.get("orgID") or "")
                    # Some versions put the internal org id in a field named code.
                    if not org_id and str(row.get("code") or "").startswith(("gssz", "gssh", "gsbj", "990")):
                        org_id = str(row.get("code"))
                    if org_id and (CODE in sec_code or COMPANY in sec_name or len(rows) == 1):
                        print("ORG_ID_FROM_SEARCH", sec_code, sec_name, org_id, flush=True)
                        return org_id
            except Exception as exc:
                print("TOP_SEARCH_POST_ERROR", endpoint, keyword, repr(exc), flush=True)

    fallback = f"gssz0{CODE}"
    print("ORG_ID_HEURISTIC_FALLBACK", fallback, flush=True)
    return fallback
'''
text = text[:start] + new_get_org + text[end:]

start = text.index("def query_announcements(")
end = text.index("\ndef announcement_time(", start)
new_query = r'''def query_announcements(
    session: requests.Session,
    org_id: str,
    category: str,
    searchkey: str,
    date_range: str,
    page_size: int = 30,
) -> list[dict[str, Any]]:
    category_base = category.rstrip(";")
    category_variants = []
    for value in (category_base, category_base + ";" if category_base else "", category):
        if value not in category_variants:
            category_variants.append(value)
    stock_values = [f"{CODE},{org_id}", CODE]
    layout_variants = [("", ""), ("szse", ""), ("szse", "sz")]

    for stock_value in stock_values:
        for column, plate in layout_variants:
            for category_value in category_variants:
                all_rows: list[dict[str, Any]] = []
                for page_num in range(1, 10):
                    payload = {
                        "pageNum": str(page_num),
                        "pageSize": str(page_size),
                        "column": column,
                        "tabName": "fulltext",
                        "plate": plate,
                        "stock": stock_value,
                        "searchkey": searchkey,
                        "secid": "",
                        "category": category_value,
                        "trade": "",
                        "seDate": date_range,
                        "sortName": "",
                        "sortType": "",
                        "isHLtitle": "true",
                    }
                    last_exc: Exception | None = None
                    rows: list[dict[str, Any]] = []
                    total_pages = 1
                    for attempt in range(1, 5):
                        try:
                            r = session.post(
                                CNINFO_QUERY,
                                data=payload,
                                headers={
                                    **HEADERS,
                                    "Accept": "application/json, text/javascript, */*; q=0.01",
                                    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                                    "Origin": "https://www.cninfo.com.cn",
                                    "X-Requested-With": "XMLHttpRequest",
                                    "Referer": f"https://www.cninfo.com.cn/new/disclosure/stock?stockCode={CODE}&orgId={org_id}",
                                },
                                timeout=120,
                            )
                            print(
                                "QUERY",
                                stock_value,
                                f"column={column!r}",
                                f"plate={plate!r}",
                                f"category={category_value!r}",
                                f"search={searchkey!r}",
                                page_num,
                                attempt,
                                r.status_code,
                                len(r.content),
                                flush=True,
                            )
                            r.raise_for_status()
                            data = r.json()
                            rows = data.get("announcements") or []
                            total_pages = int(data.get("totalpages") or data.get("totalPages") or 1)
                            if not rows and page_num == 1:
                                print("QUERY_EMPTY_BODY", r.text[:1200], flush=True)
                            last_exc = None
                            break
                        except Exception as exc:
                            last_exc = exc
                            print("QUERY_RETRY", repr(exc), flush=True)
                            time.sleep(attempt * 2)
                    if last_exc is not None:
                        raise last_exc
                    if rows:
                        all_rows.extend(rows)
                    if page_num >= total_pages or not rows:
                        break
                if all_rows:
                    dedup: dict[str, dict[str, Any]] = {}
                    for row in all_rows:
                        key = str(row.get("announcementId") or row.get("adjunctUrl") or json.dumps(row, sort_keys=True, ensure_ascii=False))
                        dedup[key] = row
                    result = list(dedup.values())
                    print("QUERY_RESULT_COUNT", category_value, searchkey, len(result), flush=True)
                    for row in result[:120]:
                        print(
                            "ANN",
                            row.get("announcementId"),
                            clean_title(str(row.get("announcementTitle") or "")),
                            row.get("announcementTime"),
                            row.get("adjunctUrl"),
                            flush=True,
                        )
                    return result
    print("QUERY_RESULT_COUNT", category, searchkey, 0, flush=True)
    return []
'''
text = text[:start] + new_query + text[end:]

text = text.replace('category="category_ndbg_szsh;"', 'category="category_ndbg_szsh"')
text = text.replace('category="category_yjdbg_szsh;category_sjdbg_szsh;"', 'category="category_jdbg_szsh"')

path.write_text(text, encoding="utf-8")
print("Patched CNINFO org-id lookup and query variants in", path)

from pathlib import Path

path = Path("tools/package_cssc_shipping_filings_20260927.py")
text = path.read_text(encoding="utf-8")

old_initial = '''    try:
        client.get(search_page, params={"lang": "en"}, timeout=60)
    except Exception as exc:
        print("INITIAL_SEARCH_PAGE_WARNING", repr(exc), flush=True)
'''
new_initial = '''    try:
        initial_response = client.get(
            search_page,
            params={"category": "0", "market": "SEHK", "stockId": HKEX_STOCK_ID, "lang": "EN"},
            timeout=120,
        )
        initial_response.raise_for_status()
        initial_rows = parse_html_rows(initial_response.text, str(initial_response.url))
        print("HKEX_INITIAL_ROWS", len(initial_rows), str(initial_response.url), flush=True)
        all_rows.extend(initial_rows)
    except Exception as exc:
        print("INITIAL_SEARCH_PAGE_WARNING", repr(exc), flush=True)
'''
if old_initial not in text:
    raise SystemExit("Initial-search patch anchor not found")
text = text.replace(old_initial, new_initial, 1)

old_selector = '''        if "ANNUALREPORT" not in norm:
            continue
        if "ANNUALRESULT" in norm or "ESGREPORT" in norm or "SUSTAINABILITY" in norm or "ENVIRONMENTAL" in norm:
            continue
'''
new_selector = '''        if "FINANCIALSTATEMENTSESGINFORMATIONANNUALREPORT" not in norm:
            continue
        if (
            "ANNUALRESULT" in norm
            or "ESGREPORT" in norm
            or "SUSTAINABILITY" in norm
            or "ENVIRONMENTAL" in norm
            or "SUPPLEMENTAL" in norm
            or "ANNOUNCEMENT" in norm
        ):
            continue
'''
if old_selector not in text:
    raise SystemExit("Annual-selector patch anchor not found")
text = text.replace(old_selector, new_selector, 1)

old_annual_loop = '''        records: list[dict[str, Any]] = []
        for fiscal_year in range(2020, 2026):
            selected = find_annual(annual_rows, fiscal_year)
'''
new_annual_loop = '''        annual_official = {
            2020: {
                "title": "ANNUAL REPORT 2020",
                "row_text": "Financial Statements/ESG Information - [Annual Report / Environmental, Social and Governance Information/Report] ANNUAL REPORT 2020",
                "release_date": "2021-04-26",
                "url": "https://www1.hkexnews.hk/listedco/listconews/sehk/2021/0426/2021042601333.pdf",
            },
            2021: {
                "title": "ANNUAL REPORT 2021",
                "row_text": "Financial Statements/ESG Information - [Annual Report / Environmental, Social and Governance Information/Report] ANNUAL REPORT 2021",
                "release_date": "2022-04-27",
                "url": "https://www1.hkexnews.hk/listedco/listconews/sehk/2022/0427/2022042700505.pdf",
            },
            2022: {
                "title": "ANNUAL REPORT 2022",
                "row_text": "Financial Statements/ESG Information - [Annual Report] ANNUAL REPORT 2022",
                "release_date": "2023-04-25",
                "url": "https://www1.hkexnews.hk/listedco/listconews/sehk/2023/0425/2023042502787.pdf",
            },
            2023: {
                "title": "ANNUAL REPORT 2023",
                "row_text": "Financial Statements/ESG Information - [Annual Report] ANNUAL REPORT 2023",
                "release_date": "2024-04-26",
                "url": "https://www1.hkexnews.hk/listedco/listconews/sehk/2024/0426/2024042601200.pdf",
            },
            2024: {
                "title": "ANNUAL REPORT 2024",
                "row_text": "Financial Statements/ESG Information - [Annual Report] ANNUAL REPORT 2024",
                "release_date": "2025-04-28",
                "url": "https://www1.hkexnews.hk/listedco/listconews/sehk/2025/0428/2025042800709.pdf",
            },
            2025: {
                "title": "ANNUAL REPORT 2025",
                "row_text": "Financial Statements/ESG Information - [Annual Report] ANNUAL REPORT 2025",
                "release_date": "2026-04-28",
                "url": "https://www1.hkexnews.hk/listedco/listconews/sehk/2026/0428/2026042802857.pdf",
            },
        }

        records: list[dict[str, Any]] = []
        for fiscal_year in range(2020, 2026):
            selected = annual_official[fiscal_year]
'''
if old_annual_loop not in text:
    raise SystemExit("Annual-loop patch anchor not found")
text = text.replace(old_annual_loop, new_annual_loop, 1)

old_latest = '''        latest_rows = search_hkex(client, "20260701", "20261231")
        latest_selected, latest_label = find_latest(latest_rows)
'''
new_latest = '''        latest_selected = {
            "title": "INTERIM RESULTS ANNOUNCEMENT FOR THE SIX MONTHS ENDED 30 JUNE 2026",
            "row_text": "Announcements and Notices - [Interim Results / Dividend or Distribution] INTERIM RESULTS ANNOUNCEMENT FOR THE SIX MONTHS ENDED 30 JUNE 2026",
            "release_date": "2026-08-24",
            "url": "https://www1.hkexnews.hk/listedco/listconews/sehk/2026/0824/2026082401261.pdf",
        }
        latest_label = "2026年中期业绩公告"
'''
if old_latest not in text:
    raise SystemExit("Latest-document patch anchor not found")
text = text.replace(old_latest, new_latest, 1)

path.write_text(text, encoding="utf-8")
print("Patched", path)

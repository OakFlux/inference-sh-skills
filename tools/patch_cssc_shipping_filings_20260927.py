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

path.write_text(text, encoding="utf-8")
print("Patched", path)

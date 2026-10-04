from pathlib import Path

path = Path("tools/package_longban_media_filings_20261004.py")
text = path.read_text(encoding="utf-8")

old_query = '    prospectus_rows = query_company(session, "category_zgsms_szsh", allow_unlisted=True)\n'
new_query = '    prospectus_rows: list[dict[str, Any]] = []  # final prospectus supplied from verified Sina bulletin attachment\n'
if old_query not in text:
    raise SystemExit("Prospectus query anchor not found")
text = text.replace(old_query, new_query, 1)

old_select = '    prospectus = select_prospectus(prospectus_rows)\n'
new_select = '''    prospectus = {
        "title": "龙版传媒首次公开发行股票招股说明书",
        "announcement_id": "7390878",
        "announcement_time_ms": 1626825600000,
        "announcement_date": "2021-07-21",
        "adjunct_size_kb": 0,
        "source_url": "http://file.finance.sina.com.cn/211.154.219.97:9494/MRGG/CNSESH_STOCK/2021/2021-7/2021-07-21/7390878.PDF",
        "adjunct_url": "",
        "sec_code": STOCK_CODE,
        "sec_name": COMPANY_SHORT,
        "source_provider": "新浪财经公司公告附件（交易所披露原文镜像）",
        "referer": "https://money.finance.sina.com.cn/corp/view/vCB_AllBulletinDetail.php?id=7390878&stockid=605577",
    }
    print("SELECT_PROSPECTUS_VERIFIED", json.dumps(prospectus, ensure_ascii=False), flush=True)
'''
if old_select not in text:
    raise SystemExit("Prospectus selection anchor not found")
text = text.replace(old_select, new_select, 1)

old_referer = '                "Referer": "https://www.cninfo.com.cn/",\n'
new_referer = '                "Referer": str(record.get("referer") or "https://www.cninfo.com.cn/"),\n'
if old_referer not in text:
    raise SystemExit("Download referer anchor not found")
text = text.replace(old_referer, new_referer, 1)

path.write_text(text, encoding="utf-8")
print("Patched package to use the verified final Longban prospectus attachment")

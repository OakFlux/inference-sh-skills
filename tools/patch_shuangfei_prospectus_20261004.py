from pathlib import Path

path = Path("tools/package_shuangfei_group_filings_20261004.py")
text = path.read_text(encoding="utf-8")

old_query = '    prospectus_rows = query_company(session, "category_zgsms_szsh", allow_all_category=True)\n'
new_query = '    prospectus_rows: list[dict[str, Any]] = []  # Final prospectus is supplied from its verified public attachment below.\n'
if old_query not in text:
    raise SystemExit("Prospectus-query anchor not found")
text = text.replace(old_query, new_query, 1)

old_select = '    prospectus = select_prospectus(prospectus_rows)\n'
new_select = '''    prospectus = {
        "title": "首次公开发行股票并在创业板上市招股说明书",
        "announcement_id": "5885348",
        "announcement_time_ms": 1580860800000,
        "announcement_date": "2020-02-05",
        "adjunct_size_kb": 21515,
        "source_url": "http://file.finance.sina.com.cn/211.154.219.97:9494/MRGG/CNSESZ_STOCK/2020/2020-2/2020-02-05/5885348.PDF",
        "adjunct_url": "",
        "sec_code": STOCK_CODE,
        "sec_name": "双飞股份",
        "source_provider": "新浪财经公司公告附件（券商/交易所披露原文镜像）",
        "referer": "https://money.finance.sina.com.cn/corp/view/vCB_AllBulletinDetail.php?id=5885348&stockid=300817",
    }
    print("SELECT_PROSPECTUS_VERIFIED", json.dumps(prospectus, ensure_ascii=False), flush=True)
'''
if old_select not in text:
    raise SystemExit("Prospectus-select anchor not found")
text = text.replace(old_select, new_select, 1)

old_headers = '''            headers = {
                **HEADERS,
                "Accept": "application/pdf,application/octet-stream;q=0.9,*/*;q=0.8",
                "Referer": "https://www.cninfo.com.cn/",
            }
'''
new_headers = '''            headers = {
                **HEADERS,
                "Accept": "application/pdf,application/octet-stream;q=0.9,*/*;q=0.8",
                "Referer": record.get("referer", "https://www.cninfo.com.cn/"),
            }
            if "file.finance.sina.com.cn" in record["source_url"]:
                headers.pop("Origin", None)
'''
if old_headers not in text:
    raise SystemExit("Download-header anchor not found")
text = text.replace(old_headers, new_headers, 1)

text = text.replace(
    '        "source": "巨潮资讯网官方披露PDF",\n',
    '        "source": "年度报告及定期报告来自巨潮资讯网官方PDF；最终招股说明书来自新浪财经公司公告所附披露原文PDF。",\n',
    1,
)
text = text.replace(
    '        "资料来源：巨潮资讯网官方披露PDF",\n',
    '        "资料来源：年度报告及定期报告来自巨潮资讯网官方PDF；最终招股说明书来自新浪财经公司公告附件。",\n',
    1,
)
text = text.replace(
    '            "- 招股说明书优先选择最终发行版本，排除摘要、意向书、提示性公告和申报稿；",\n',
    '            "- 招股说明书为2020年2月5日披露的最终发行版本，未使用招股意向书或申报稿替代；",\n',
    1,
)

path.write_text(text, encoding="utf-8")
print("Patched package to use the verified final Shuangfei prospectus attachment")

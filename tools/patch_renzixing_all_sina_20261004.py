from pathlib import Path

path = Path("tools/package_renzixing_broker_reports_20261004.py")
text = path.read_text(encoding="utf-8")

old_report = '''    {
        "order": 2,
        "kind": "fxbaogao_page_images",
        "doc_id": 71024,
        "date": "2016-04-21",
        "date_path": "2016/04/21",
        "institution": "太平洋证券",
        "authors": "张学、徐中华",
        "rating": "买入（首次）",
        "title": "行业景气外延助力，持续高成长可期",
        "filename": "02_太平洋证券_2016-04-21_行业景气外延助力_持续高成长可期_公开逐页图像重建版.pdf",
        "source_url": "https://www.fxbaogao.com/detail/71024",
    },
'''
new_report = '''    {
        "order": 2,
        "kind": "sina_text_archive",
        "rptid": "617386628499",
        "date": "2016-04-21",
        "institution": "太平洋证券",
        "authors": "张学、徐中华",
        "rating": "买入（首次）",
        "title": "行业景气外延助力，持续高成长可期",
        "filename": "02_太平洋证券_2016-04-21_行业景气外延助力_持续高成长可期_公开网页全文存档版.pdf",
        "source_url": "https://stock.finance.sina.com.cn/stock/go.php/vReport_Show/kind/search/rptid/617386628499/index.phtml",
    },
'''
if old_report not in text:
    raise SystemExit("Taipingyang report block not found")
text = text.replace(old_report, new_report, 1)

old_scope = '"scope_note": "公开渠道可稳定取得的任子行券商原始PDF有限。本包收录1份保留券商原页面的逐页图像重建PDF，以及2份新浪财经公开研报正文存档版。文件名和清单已明确标注文件类型。",'
new_scope = '"scope_note": "公开渠道可稳定取得的任子行券商原始排版PDF有限。本包收录3份新浪财经公开展示研报正文的离线存档版；文件名和资料清单均已明确标注文件类型。",'
if old_scope not in text:
    raise SystemExit("scope note anchor not found")
text = text.replace(old_scope, new_scope, 1)

old_notes = '''        "- 太平洋证券报告由公开平台逐页报告图像按原顺序重建，页面内容保持原样。",
        "- 华金证券和平安证券文件依据新浪财经公开展示的研报正文制作，便于离线归档；不是券商原始版式PDF，可能不含原报告未公开展示的图表与附录。",
'''
new_notes = '''        "- 三份文件均依据新浪财经公开展示的券商研报正文制作，便于离线归档。",
        "- 这些文件不是券商原始版式PDF，可能不含原报告未在公开网页展示的图表、附录或完整分页。",
'''
if old_notes not in text:
    raise SystemExit("notes anchor not found")
text = text.replace(old_notes, new_notes, 1)

path.write_text(text, encoding="utf-8")
print("Patched package to use three Sina public-text archives")

from __future__ import annotations

from pathlib import Path
import py_compile


BUILDER = Path("scripts/build_huaxin_filings_package.py")


def main() -> None:
    text = BUILDER.read_text(encoding="utf-8")

    validation_old = "path.stat().st_size < 10_000"
    if validation_old not in text:
        raise RuntimeError("Expected PDF validation threshold was not found")
    text = text.replace(validation_old, "path.stat().st_size < 500", 1)

    list_start = text.index("html_docs = [")
    loop_marker = "\nfor html_name, pdf_name, title, dtype, year, pubdate, url, outdir, note in html_docs:"
    list_end = text.index(loop_marker, list_start)
    annual_summary_only = """html_docs = [
    ('1993_华新水泥_年度报告摘要_官方原始网页.html','1993_华新水泥_年度报告摘要_可读版.pdf','华新水泥1993年年度报告摘要','年度报告摘要',1993,'1994-05-12','https://static.cninfo.com.cn/finalpage/1994-05-12/11368154.html',annual_dir,'官方公开电子档案仅检索到摘要，未检索到完整年报电子版'),
]"""
    text = text[:list_start] + annual_summary_only + text[list_end:]

    h_marker = "\nh_listing = equity_dir / '2022_华新水泥_H股以介绍方式上市_上市文件_港交所中文版.pdf'"
    insert_at = text.index(h_marker)
    index_record_code = r'''
def create_index_record_pdf(dest: Path, title: str, publication_date: str, announcement_id: str, indexed_url: str, explanatory_lines: list[str]) -> None:
    doc = SimpleDocTemplate(
        str(dest), pagesize=A4, rightMargin=18*mm, leftMargin=18*mm,
        topMargin=18*mm, bottomMargin=18*mm, title=title,
        author='华新建材历史公告索引记录'
    )
    story = [
        Paragraph(html.escape(title), title_style),
        Paragraph('文件性质：官方公告索引记录转制PDF，非原公告全文', meta_style),
        Spacer(1, 4*mm),
        Paragraph(html.escape('披露日期：' + publication_date), body_style),
        Paragraph(html.escape('公告编号：' + announcement_id), body_style),
        Paragraph(html.escape('官方索引所记录的原始路径：' + indexed_url), body_style),
        Spacer(1, 3*mm),
    ]
    for line in explanatory_lines:
        story.append(Paragraph(html.escape(line), body_style))
    doc.build(story)

legacy_index_docs = [
    {
        'filename': '1993_华新水泥_A股招股说明书概要_官方索引记录_原文件现不可下载.pdf',
        'title': '华新水泥股份有限公司招股说明书概要——官方索引记录',
        'document_type': '招股说明书概要索引记录',
        'publication_date': '1993-11-03',
        'announcement_id': '158103',
        'indexed_url': 'https://static.cninfo.com.cn/finalpage/1993-11-03/158103.html',
        'lines': [
            '巨潮资讯历史公告索引能够检索到该公告标题、披露日期、公告编号及原始路径。',
            '截至2026年9月22日，官方索引所记录的原始HTML路径返回404，无法取得原公告全文。',
            '本记录仅用于说明该历史招股文件的存在及当前电子档案状态，不替代招股说明书原文。',
        ],
    },
    {
        'filename': '1993_华新水泥_A股股票上市公告书_官方索引记录_原文件现不可下载.pdf',
        'title': '华新水泥股份有限公司股票上市公告书——官方索引记录',
        'document_type': '股票上市公告书索引记录',
        'publication_date': '1993-12-16',
        'announcement_id': '148870',
        'indexed_url': 'https://static.cninfo.com.cn/finalpage/1993-12-16/148870.html',
        'lines': [
            '巨潮资讯历史公告索引能够检索到该公告标题、披露日期、公告编号及原始路径。',
            '截至2026年9月22日，官方索引所记录的原始HTML路径返回404，无法取得原公告全文。',
            '本记录仅用于说明该历史上市文件的存在及当前电子档案状态，不替代上市公告书原文。',
        ],
    },
]
for item in legacy_index_docs:
    pdf_path = equity_dir / item['filename']
    create_index_record_pdf(
        pdf_path, item['title'], item['publication_date'], item['announcement_id'],
        item['indexed_url'], item['lines']
    )
    add_pdf(
        pdf_path, title=item['title'], doc_type=item['document_type'], fiscal_year=None,
        publication_date=item['publication_date'], source='巨潮资讯网历史公告索引',
        source_url=item['indexed_url'], source_form='官方公告索引记录转制PDF；非原公告全文',
        notes='原始HTML链接截至2026年9月22日返回404；已明确标注，不作为原公告全文使用',
        min_pages=1
    )
    txt_path = equity_dir / item['filename'].replace('.pdf', '.txt')
    txt_path.write_text(
        '\n'.join([
            item['title'],
            '文件性质：官方公告索引记录，非原公告全文',
            '披露日期：' + item['publication_date'],
            '公告编号：' + item['announcement_id'],
            '官方索引所记录的原始路径：' + item['indexed_url'],
            *item['lines'],
        ]) + '\n', encoding='utf-8'
    )
    raw_records.append({
        'relative_path': str(txt_path.relative_to(root)),
        'filename': txt_path.name,
        'title': item['title'],
        'document_type': item['document_type'],
        'publication_date': item['publication_date'],
        'source': '巨潮资讯网历史公告索引',
        'source_url': item['indexed_url'],
        'bytes': txt_path.stat().st_size,
        'sha256': sha256(txt_path),
        'notes': '索引信息文本记录；非原公告全文',
    })
'''
    text = text[:insert_at] + "\n" + index_record_code + text[insert_at:]

    text = text.replace(
        "4. 股权发行与上市文件方面，官方公开电子档案可获得1993年A股《招股说明书概要》和《股票上市公告书》；未检索到1994年B股原始招股说明书的官方公开电子文件。",
        "4. 股权发行与上市文件方面，巨潮资讯官方索引可检索到1993年A股《招股说明书概要》和《股票上市公告书》，但两项原始HTML链接于2026年9月22日均返回404；本包仅附官方索引记录转制PDF，不将其冒充原公告全文。未检索到1994年B股原始招股说明书的官方公开电子文件。",
    )
    text = text.replace(
        "'equity_documents': '1993年A股招股说明书概要、A股股票上市公告书、2022年H股介绍上市文件'",
        "'equity_documents': '1993年A股招股说明书概要及股票上市公告书的官方索引记录、2022年H股介绍上市文件原件'",
    )
    text = text.replace(
        "- 招股及上市文件：1993年A股招股说明书概要、A股股票上市公告书、2022年H股介绍上市文件。",
        "- 招股及上市文件：1993年A股招股说明书概要和股票上市公告书的官方索引记录（原始链接现为404），以及2022年H股介绍上市文件原件。",
    )

    BUILDER.write_text(text, encoding="utf-8")
    py_compile.compile(str(BUILDER), doraise=True)
    print(f"Patched {BUILDER}: {BUILDER.stat().st_size} bytes")


if __name__ == "__main__":
    main()

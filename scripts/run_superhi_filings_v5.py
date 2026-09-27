from pathlib import Path

source_path = Path('scripts/build_superhi_filings_20260927.py')
source = source_path.read_text(encoding='utf-8')

# Widen the first listed-year annual-report search window.
source = source.replace(
    'rows = hkex_links("20230320", "20230415")',
    'rows = hkex_links("20230320", "20230531")',
    1,
)

annual_start = source.index('# 2023-2025 annual reports from official IR direct files.')
annual_end = source.index('# 2022 Hong Kong listing document by way of introduction.')
annual_replacement = '''# 2023-2025 annual reports from HKEX official filings.
annual_windows = [
    (2023, "2024-04-25", "20240401", "20240515"),
    (2024, "2025-04-24", "20250401", "20250515"),
    (2025, "2026-04-13", "20260401", "20260430"),
]
for year, publication_date, start_date, end_date in annual_windows:
    rows = hkex_links(start_date, end_date)
    selected = choose_hkex_link(rows, (str(year), "annual report"))
    path = annual_dir / f"{year}_特海国际_年度报告_港交所官方.pdf"
    final_url = download_pdf(
        selected["href"],
        path,
        referer=selected["page"],
        min_bytes=500_000,
    )
    register(
        path,
        title=f"特海国际{year}年度报告",
        document_type="年度报告",
        publication_date=publication_date,
        source="香港交易所披露易",
        source_url=final_url,
        min_pages=150,
    )

'''
source = source[:annual_start] + annual_replacement + source[annual_end:]

prospectus_start = source.index('# 2024 U.S. ADS final prospectus.')
prospectus_end = source.index('# 2026 formal interim report.')
prospectus_replacement = '''# 2024 U.S. ADS final prospectus from the official IR-hosted filing PDF.
path = offering_dir / "2024_特海国际_美国ADS首次公开发行最终招股说明书_Form424B4.pdf"
final_url = download_pdf(
    "https://ir.superhiinternational.com/static-files/91d5e3ed-d02c-48a4-894a-aac27c671555",
    path,
    referer="https://ir.superhiinternational.com/sec-filings/sec-filing/424b4/0001104659-24-062760",
    min_bytes=500_000,
)
register(
    path,
    title="特海国际美国ADS首次公开发行最终招股说明书（Form 424B4）",
    document_type="美国IPO最终招股说明书",
    publication_date="2024-05-17",
    source="特海国际投资者关系网站/美国SEC申报",
    source_url=final_url,
    notes="NASDAQ代码HDL。",
    min_pages=150,
    identity_terms=("super hi", "prospectus", "american depositary"),
)

'''
source = source[:prospectus_start] + prospectus_replacement + source[prospectus_end:]

exec(
    compile(source, str(source_path), 'exec'),
    {'__name__': '__main__', '__file__': str(source_path)},
)

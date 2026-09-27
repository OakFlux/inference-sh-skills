from pathlib import Path

v7_path = Path('scripts/run_superhi_filings_v7.py')
script = v7_path.read_text(encoding='utf-8')

start_marker = "prospectus_replacement = '''# 2024 U.S. ADS final prospectus from the official IR-hosted filing PDF."
start = script.index(start_marker)
content_start = start + len("prospectus_replacement = '''")
end_marker = "'''\nsource = source[:prospectus_start] + prospectus_replacement + source[prospectus_end:]"
end = script.index(end_marker, content_start)

replacement = '''# 2024 U.S. ADS final prospectus rendered from the official IR-hosted SEC filing HTML.
from playwright.sync_api import sync_playwright

prospectus_html_url = "https://ir.superhiinternational.com/node/6776/html"
path = offering_dir / "2024_特海国际_美国ADS首次公开发行最终招股说明书_Form424B4_官方HTML打印版.pdf"
with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True)
    context = browser.new_context(
        user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/151 Safari/537.36"
    )
    page = context.new_page()
    page.goto(prospectus_html_url, wait_until="domcontentloaded", timeout=180000)
    page.wait_for_timeout(10000)
    page.emulate_media(media="print")
    page.pdf(
        path=str(path),
        format="A4",
        print_background=True,
        display_header_footer=False,
        margin={"top": "10mm", "bottom": "10mm", "left": "8mm", "right": "8mm"},
        prefer_css_page_size=True,
    )
    browser.close()
register(
    path,
    title="特海国际美国ADS首次公开发行最终招股说明书（Form 424B4）",
    document_type="美国IPO最终招股说明书",
    publication_date="2024-05-17",
    source="特海国际投资者关系网站/美国SEC申报",
    source_url=prospectus_html_url,
    notes="由公司IR网站公开的官方SEC申报HTML打印生成PDF；内容对应Form 424B4，NASDAQ代码HDL。",
    min_pages=150,
    identity_terms=("super hi", "prospectus", "american depositary"),
)

'''

script = script[:content_start] + replacement + script[end:]
exec(compile(script, str(v7_path), 'exec'), {'__name__': '__main__', '__file__': str(v7_path)})

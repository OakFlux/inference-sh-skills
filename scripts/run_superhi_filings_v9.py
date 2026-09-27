from pathlib import Path

v7_path = Path('scripts/run_superhi_filings_v7.py')
script = v7_path.read_text(encoding='utf-8')

start_marker = "prospectus_replacement = '''# 2024 U.S. ADS final prospectus from the official IR-hosted filing PDF."
start = script.index(start_marker)
content_start = start + len("prospectus_replacement = '''")
end_marker = "'''\nsource = source[:prospectus_start] + prospectus_replacement + source[prospectus_end:]"
end = script.index(end_marker, content_start)

replacement = r'''# 2024 U.S. ADS final prospectus rendered from the official SEC 424B4 HTML.
from playwright.sync_api import sync_playwright

sec_html_url = "https://www.sec.gov/Archives/edgar/data/1995306/000110465924062760/tm2331649-27_424b4.htm"
sec_base_url = "https://www.sec.gov/Archives/edgar/data/1995306/000110465924062760/"
raw_html_path = offering_dir / "2024_特海国际_美国ADS首次公开发行最终招股说明书_Form424B4_SEC官方原始HTML.htm"
render_html_path = Path("_superhi_sec_424b4_render.html")
path = offering_dir / "2024_特海国际_美国ADS首次公开发行最终招股说明书_Form424B4_SEC官方HTML打印版.pdf"

sec_headers = {
    "User-Agent": "OpenAI Research research@openai.com",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate",
}
sec_response = requests.get(
    sec_html_url,
    headers=sec_headers,
    timeout=(20, 300),
    allow_redirects=True,
)
print(
    "SEC_HTML",
    sec_response.status_code,
    sec_response.headers.get("content-type"),
    len(sec_response.content),
    sec_response.url,
    flush=True,
)
sec_response.raise_for_status()
raw_html = sec_response.content
if len(raw_html) < 1_000_000:
    raise RuntimeError(f"SEC prospectus HTML unexpectedly small: {len(raw_html)} bytes")
raw_html_path.write_bytes(raw_html)

html_text = raw_html.decode("utf-8", errors="replace")
base_and_print_css = f"""
<base href="{sec_base_url}">
<style id="openai-print-normalization">
@media print {{
  html, body {{ height: auto !important; min-height: 0 !important; overflow: visible !important; }}
  body {{ margin: 0 !important; }}
  iframe {{ display: none !important; }}
  * {{ max-height: none !important; }}
}}
</style>
"""
if re.search(r"<head[^>]*>", html_text, flags=re.I):
    html_text = re.sub(
        r"(<head[^>]*>)",
        r"\1" + base_and_print_css,
        html_text,
        count=1,
        flags=re.I,
    )
else:
    html_text = base_and_print_css + html_text
render_html_path.write_text(html_text, encoding="utf-8")

with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True)
    context = browser.new_context(
        user_agent="OpenAI Research research@openai.com",
        locale="en-US",
        viewport={"width": 1280, "height": 1600},
    )
    page = context.new_page()
    page.goto(render_html_path.resolve().as_uri(), wait_until="load", timeout=240000)
    page.wait_for_timeout(15000)
    body_text_length = page.evaluate("document.body ? document.body.innerText.length : 0")
    scroll_height = page.evaluate("document.documentElement.scrollHeight")
    print("SEC_RENDER_PAGE", body_text_length, scroll_height, flush=True)
    if body_text_length < 500_000:
        browser.close()
        raise RuntimeError(
            f"SEC prospectus body text unexpectedly short: {body_text_length} characters"
        )
    page.emulate_media(media="print")
    page.add_style_tag(
        content="""
        html, body { height: auto !important; min-height: 0 !important; overflow: visible !important; }
        body { margin: 0 !important; }
        [style*='position: fixed'], [style*='position:fixed'] { position: absolute !important; }
        """
    )
    page.pdf(
        path=str(path),
        format="Letter",
        print_background=True,
        display_header_footer=False,
        prefer_css_page_size=False,
        scale=0.82,
        margin={"top": "7mm", "bottom": "7mm", "left": "6mm", "right": "6mm"},
        timeout=300000,
    )
    browser.close()

rendered_pages = len(PdfReader(str(path), strict=False).pages)
print("SEC_RENDERED_PAGES", rendered_pages, path.stat().st_size, flush=True)
if rendered_pages < 100:
    raise RuntimeError(f"Rendered SEC prospectus has too few pages: {rendered_pages}")

register(
    path,
    title="特海国际美国ADS首次公开发行最终招股说明书（Form 424B4）",
    document_type="美国IPO最终招股说明书",
    publication_date="2024-05-17",
    source="美国证券交易委员会EDGAR官方申报",
    source_url=sec_html_url,
    notes="由SEC官方424B4主文档HTML完整打印生成PDF；包内同时保留SEC官方原始HTML。NASDAQ代码HDL。",
    min_pages=100,
    identity_terms=("super hi", "prospectus", "american depositary"),
)

'''

script = script[:content_start] + replacement + script[end:]
exec(
    compile(script, str(v7_path), 'exec'),
    {'__name__': '__main__', '__file__': str(v7_path)},
)

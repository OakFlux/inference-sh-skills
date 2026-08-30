from __future__ import annotations

import re
import textwrap
from urllib.parse import parse_qs, urljoin, urlsplit

import requests
from bs4 import BeautifulSoup

SOURCE_URL = (
    "https://raw.githubusercontent.com/OakFlux/inference-sh-skills/"
    "0b28ae8e239c88caf102c2b835ff9c7dd6c73cca/"
    ".github/scripts/package_hehe_information_final.py"
)

STOCK_ID = "688689"
COMPANY = "常州银河世纪微电子股份有限公司"
SHORT_NAME = "银河微电"
TICKER = "688689.SH"
PROSPECTUS_DATE = "2021-01-19"
LATEST_HALF_DATE = "2026-08-10"


def decode_html(response: requests.Response) -> str:
    candidates = [response.encoding, response.apparent_encoding, "gb18030", "utf-8"]
    best = ""
    best_score = -10**9
    for encoding in candidates:
        if not encoding:
            continue
        try:
            text = response.content.decode(encoding, errors="replace")
        except LookupError:
            continue
        score = (
            text.count("银河微电") * 20
            + text.count("招股说明书") * 10
            + text.count("2021-01-19") * 10
            - text.count("�") * 5
        )
        if score > best_score:
            best = text
            best_score = score
    return best or response.text


def discover_prospectus_detail_id() -> int:
    urls = [
        f"https://vip.stock.finance.sina.com.cn/corp/go.php/vISSUE_RaiseExplanation/stockid/{STOCK_ID}.phtml",
        f"https://money.finance.sina.com.cn/corp/go.php/vISSUE_RaiseExplanation/stockid/{STOCK_ID}.phtml",
    ]
    errors: list[str] = []
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151 Safari/537.36"
            ),
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }
    )
    for url in urls:
        try:
            response = session.get(url, timeout=(20, 120))
            response.raise_for_status()
            soup = BeautifulSoup(decode_html(response), "html.parser")
            for anchor in soup.find_all("a", href=True):
                title = "".join(anchor.get_text(" ", strip=True).split())
                if "首次公开发行股票并在科创板上市招股说明书" not in title:
                    continue
                if any(marker in title for marker in ("意向书", "申报稿", "注册稿")):
                    continue
                href = urljoin(response.url, anchor["href"])
                values = parse_qs(urlsplit(href).query).get("id") or []
                if values and values[0].isdigit():
                    detail_id = int(values[0])
                    print(f"Discovered formal prospectus detail ID: {detail_id}; title={title}")
                    return detail_id
                match = re.search(r"[?&]id=(\d+)", href)
                if match:
                    detail_id = int(match.group(1))
                    print(f"Discovered formal prospectus detail ID: {detail_id}; title={title}")
                    return detail_id
            errors.append(f"{url}: formal prospectus anchor not found")
        except Exception as exc:
            errors.append(f"{url}: {exc}")
    raise RuntimeError("Unable to discover formal prospectus ID: " + " | ".join(errors))


def main() -> None:
    prospectus_id = discover_prospectus_detail_id()

    response = requests.get(SOURCE_URL, timeout=120)
    response.raise_for_status()
    code = response.text

    replacements = [
        ("hehe_information_verified_package", "galaxy_microelectronics_verified_package"),
        ('STOCK_ID = "688615"', f'STOCK_ID = "{STOCK_ID}"'),
        (
            'COMPANY = "上海合合信息科技股份有限公司"',
            f'COMPANY = "{COMPANY}"',
        ),
        ('SHORT_NAME = "合合信息"', f'SHORT_NAME = "{SHORT_NAME}"'),
        ('TICKER = "688615.SH"', f'TICKER = "{TICKER}"'),
        ("上海合合信息科技股份有限公司", COMPANY),
        ("合合信息", SHORT_NAME),
        ('"intsig"', '"gmesemi"'),
        ("PROSPECTUS_DETAIL_ID = 10494386", f"PROSPECTUS_DETAIL_ID = {prospectus_id}"),
        ('PROSPECTUS_PUBLISHED_DATE = "2024-09-23"', f'PROSPECTUS_PUBLISHED_DATE = "{PROSPECTUS_DATE}"'),
        ('LATEST_HALF_PUBLISHED_DATE = "2026-08-20"', f'LATEST_HALF_PUBLISHED_DATE = "{LATEST_HALF_DATE}"'),
        ("if years != [2024, 2025]:", "if years != list(range(2020, 2026)):") ,
        ("for 2024 and 2025, found {years}.", "for 2020 through 2025, found {years}."),
        ("prospectus_target, expected_year=2024, kind=\"prospectus\"", "prospectus_target, expected_year=2021, kind=\"prospectus\""),
        ('"year": 2024,\n        "label": "银河微电：首次公开发行股票并在科创板上市招股说明书"', '"year": 2021,\n        "label": "银河微电：首次公开发行股票并在科创板上市招股说明书"'),
        ("公司于2024年9月在上海证券交易所科创板上市；上市后独立年度报告为2024年和2025年，共2份。", "公司于2021年1月27日在上海证券交易所科创板上市；收录2020—2025年共6份完整年度报告。"),
        ("if len(documents) != 4:", "if len(documents) != 8:"),
        ("Expected 4 documents", "Expected 8 documents"),
        ("if len(pdfs) != 4:", "if len(pdfs) != 8:"),
        ("Expected 4 PDFs", "Expected 8 PDFs"),
    ]
    for old, new in replacements:
        code = code.replace(old, new)

    original_inspection = '''    if kind == "prospectus":
        if "招股说明书" not in front_compact:
            raise RuntimeError(f"Prospectus marker missing: {path}")
        if "科创板" not in front_compact and "上海证券交易所" not in front_compact:
            raise RuntimeError(f"STAR Market marker missing in prospectus: {path}")
        if any(marker in front_compact for marker in ("申报稿", "招股意向书")):
            raise RuntimeError(f"Non-final prospectus version detected: {path}")
'''
    replacement_inspection = '''    if kind == "prospectus":
        cover_text = "\\n".join(
            document.load_page(index).get_text("text")
            for index in range(min(12, pages))
        )
        cover_compact = normalize(cover_text)
        if "招股说明书" not in cover_compact:
            raise RuntimeError(f"Prospectus marker missing: {path}")
        if "科创板" not in cover_compact and "上海证券交易所" not in cover_compact:
            raise RuntimeError(f"STAR Market marker missing in prospectus: {path}")
        if any(marker in cover_compact for marker in ("申报稿", "招股意向书")):
            raise RuntimeError(f"Non-final prospectus version detected: {path}")
'''
    if original_inspection not in code:
        raise RuntimeError("Prospectus inspection block was not found")
    code = code.replace(original_inspection, replacement_inspection, 1)

    original_download = '''prospectus_url, prospectus_detail_url, prospectus_context = extract_pdf_from_pages(
    prospectus_detail_variants()
)
prospectus_target = PROSPECTUS_DIR / f"{SHORT_NAME}_首次公开发行股票并在科创板上市招股说明书_正式版.pdf"
prospectus_used_url = download_pdf(
    download_candidates(prospectus_url), prospectus_target, prospectus_detail_url
)
'''
    direct_encoded = (
        "https://file.finance.sina.com.cn/211.154.219.97%3A9494/"
        f"MRGG/CNSESH_STOCK/2021/2021-1/{PROSPECTUS_DATE}/{prospectus_id}.PDF"
    )
    direct_plain = (
        "https://file.finance.sina.com.cn/211.154.219.97:9494/"
        f"MRGG/CNSESH_STOCK/2021/2021-1/{PROSPECTUS_DATE}/{prospectus_id}.PDF"
    )
    direct_http = direct_plain.replace("https://", "http://", 1)
    replacement_download = f'''prospectus_detail_url = prospectus_detail_variants()[0]
prospectus_context = (
    "新浪财经招股说明页面列示：{PROSPECTUS_DATE} 银河微电首次公开发行股票并在科创板上市招股说明书；"
    "正式发行版详情编号{prospectus_id}。"
)
prospectus_candidates = [
    "{direct_encoded}",
    "{direct_plain}",
    "{direct_http}",
]
prospectus_target = PROSPECTUS_DIR / f"{{SHORT_NAME}}_首次公开发行股票并在科创板上市招股说明书_正式版.pdf"
prospectus_used_url = download_pdf(
    prospectus_candidates, prospectus_target, prospectus_detail_url
)
prospectus_url = prospectus_used_url
'''
    if original_download not in code:
        raise RuntimeError("Prospectus download block was not found")
    code = code.replace(original_download, replacement_download, 1)

    required = [
        f'STOCK_ID = "{STOCK_ID}"',
        f'COMPANY = "{COMPANY}"',
        f'SHORT_NAME = "{SHORT_NAME}"',
        "list(range(2020, 2026))",
        "expected_year=2021, kind=\"prospectus\"",
        f'PROSPECTUS_PUBLISHED_DATE = "{PROSPECTUS_DATE}"',
        f'LATEST_HALF_PUBLISHED_DATE = "{LATEST_HALF_DATE}"',
        f"{prospectus_id}.PDF",
        "银河微电_全部年报_招股说明书_2026年最新半年报_完整PDF.zip",
    ]
    missing = [token for token in required if token not in code]
    if missing:
        raise RuntimeError(f"Required transformations missing: {missing}")

    compiled = compile(code, "galaxy_microelectronics_generated_packaging.py", "exec")
    exec(compiled, {"__name__": "__main__"})


if __name__ == "__main__":
    main()

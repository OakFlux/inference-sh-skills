from __future__ import annotations

import re
from urllib.parse import parse_qs, urljoin, urlsplit

import requests
from bs4 import BeautifulSoup

SOURCE_URL = (
    "https://raw.githubusercontent.com/OakFlux/inference-sh-skills/"
    "3b83f75be82e0b46e8b1c29a2e4edfeef37b648d/"
    ".github/scripts/package_actions_technology_final.py"
)

STOCK_ID = "301155"
COMPANY = "江苏海力风电设备科技股份有限公司"
SHORT_NAME = "海力风电"
TICKER = "301155.SZ"
PROSPECTUS_DATE = "2021-11-19"
LATEST_HALF_DATE = "2026-08-29"


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
            text.count(SHORT_NAME) * 20
            + text.count("招股说明书") * 10
            + text.count(PROSPECTUS_DATE) * 10
            - text.count("�") * 5
        )
        if score > best_score:
            best = text
            best_score = score
    return best or response.text


def discover_formal_prospectus_detail_id() -> int:
    urls = [
        f"https://vip.stock.finance.sina.com.cn/corp/go.php/vISSUE_RaiseExplanation/stockid/{STOCK_ID}.phtml",
        f"https://money.finance.sina.com.cn/corp/go.php/vISSUE_RaiseExplanation/stockid/{STOCK_ID}.phtml",
    ]
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
    errors: list[str] = []
    for url in urls:
        try:
            response = session.get(url, timeout=(20, 120))
            response.raise_for_status()
            soup = BeautifulSoup(decode_html(response), "html.parser")
            for anchor in soup.find_all("a", href=True):
                title = "".join(anchor.get_text(" ", strip=True).split())
                if SHORT_NAME not in title:
                    continue
                if "首次公开发行股票" not in title or "招股说明书" not in title:
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
    raise RuntimeError("Unable to discover formal prospectus detail ID: " + " | ".join(errors))


def main() -> None:
    prospectus_id = discover_formal_prospectus_detail_id()

    response = requests.get(SOURCE_URL, timeout=120)
    response.raise_for_status()
    code = response.text

    replacements = [
        ("actions_technology_verified_package", "haili_wind_verified_package"),
        ('STOCK_ID = "688049"', f'STOCK_ID = "{STOCK_ID}"'),
        ('COMPANY = "炬芯科技股份有限公司"', f'COMPANY = "{COMPANY}"'),
        ('SHORT_NAME = "炬芯科技"', f'SHORT_NAME = "{SHORT_NAME}"'),
        ('TICKER = "688049.SH"', f'TICKER = "{TICKER}"'),
        ('PROSPECTUS_DATE = "2021-11-24"', f'PROSPECTUS_DATE = "{PROSPECTUS_DATE}"'),
        ("PROSPECTUS_DETAIL_ID = 7675376", f"PROSPECTUS_DETAIL_ID = {prospectus_id}"),
        ('LATEST_HALF_DATE = "2026-08-25"', f'LATEST_HALF_DATE = "{LATEST_HALF_DATE}"'),
        ("炬芯科技股份有限公司", COMPANY),
        ("炬芯科技", SHORT_NAME),
        ('"actions"', '"haili"'),
        ("科创板", "创业板"),
        ("上海证券交易所", "深圳证券交易所"),
        ("CNSESH_STOCK", "CNSESZ_STOCK"),
        ("2021年11月29日", "2021年11月24日"),
        (
            "招股说明书采用2021年11月24日披露的正式发行版，排除招股意向书、申报稿、注册稿和问询回复。",
            "招股说明书采用2021年11月19日披露的正式发行版，排除招股意向书、申报稿、注册稿和问询回复。",
        ),
        (
            "最新半年报为2026年8月25日披露、覆盖截至2026年6月30日止六个月的完整报告。",
            "最新半年报为2026年8月29日披露、覆盖截至2026年6月30日止六个月的完整报告。",
        ),
        ('"prepared_date": "2026-08-29"', '"prepared_date": "2026-08-30"'),
        ('"整理日期：2026-08-29"', '"整理日期：2026-08-30"'),
        (
            "    code = response.text\n\n    replacements = [",
            "    code = (\n"
            "        response.text\n"
            "        .replace(\"科创板\", \"创业板\")\n"
            "        .replace(\"上海证券交易所\", \"深圳证券交易所\")\n"
            "        .replace(\"CNSESH_STOCK\", \"CNSESZ_STOCK\")\n"
            "    )\n\n"
            "    replacements = [",
        ),
    ]
    for old, new in replacements:
        code = code.replace(old, new)

    required = [
        f'STOCK_ID = "{STOCK_ID}"',
        f'COMPANY = "{COMPANY}"',
        f'SHORT_NAME = "{SHORT_NAME}"',
        f'TICKER = "{TICKER}"',
        f'PROSPECTUS_DATE = "{PROSPECTUS_DATE}"',
        f'PROSPECTUS_DETAIL_ID = {prospectus_id}',
        f'LATEST_HALF_DATE = "{LATEST_HALF_DATE}"',
        "[2021, 2022, 2023, 2024, 2025]",
        "首次公开发行股票并在创业板上市招股说明书",
        "CNSESZ_STOCK",
        "海力风电_全部年报_招股说明书_2026年最新半年报_完整PDF.zip",
        '.replace("科创板", "创业板")',
    ]
    missing = [token for token in required if token not in code]
    if missing:
        raise RuntimeError(f"Required transformations missing: {missing}")

    compiled = compile(code, "haili_wind_generated_packaging.py", "exec")
    exec(compiled, {"__name__": "__main__"})


if __name__ == "__main__":
    main()

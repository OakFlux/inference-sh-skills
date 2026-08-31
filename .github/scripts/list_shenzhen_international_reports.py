from __future__ import annotations

import html
import re

import requests
from bs4 import BeautifulSoup

session = requests.Session()
session.headers.update(
    {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151 Safari/537.36"
        ),
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Referer": "https://www.fxbaogao.com/",
    }
)

REPORTS = [
    {
        "id": 4788440,
        "date": "2025/04/17",
        "expected_title": "华南物流园增值添利，高比例分红回报股东",
    },
    {
        "id": 4438234,
        "date": "2024/08/10",
        "expected_title": "土地转性贡献弹性 高股息价值凸显",
    },
    {
        "id": 5041109,
        "date": "2025/09/02",
        "expected_title": "REIT缺席拖累盈利 公司不增资深航",
    },
]

for report in REPORTS:
    report_id = report["id"]
    print("\n================ REPORT", report_id, "================")
    detail_url = f"https://www.fxbaogao.com/detail/{report_id}"
    response = session.get(detail_url, timeout=(15, 90), allow_redirects=True)
    print("DETAIL", response.status_code, len(response.content), response.url)
    response.raise_for_status()
    text = html.unescape(response.text).replace("\\/", "/")
    soup = BeautifulSoup(text, "html.parser")
    print("TITLE", soup.title.get_text(" ", strip=True) if soup.title else "")

    # Surface useful metadata and all report image URLs found in the page.
    image_urls: list[str] = []
    for tag in soup.find_all("img", src=True):
        src = tag["src"]
        if str(report_id) in src or "report-image" in src:
            image_urls.append(src)
    for match in re.findall(r'https?://[^\"\'<>\s]+', text, flags=re.I):
        if str(report_id) in match and "report-image" in match:
            image_urls.append(match)
    print("HTML_IMAGE_URLS", list(dict.fromkeys(image_urls))[:30])

    for keyword in (
        "pageCount",
        "page_count",
        "pages",
        "report-image",
        str(report_id),
        report["expected_title"],
    ):
        positions = [m.start() for m in re.finditer(re.escape(keyword), text, flags=re.I)]
        print("KEY", keyword, "COUNT", len(positions))
        for pos in positions[:4]:
            snippet = re.sub(r"\s+", " ", text[max(0, pos - 250):pos + 750])
            print(snippet[:1100])

    # Probe sequential public preview pages. Stop only after three consecutive misses.
    misses = 0
    found_pages: list[tuple[int, int, str]] = []
    for page_no in range(1, 81):
        image_url = (
            "https://public.fxbaogao.com/report-image/"
            f"{report['date']}/{report_id}-{page_no}.png"
        )
        try:
            image_response = session.get(
                image_url,
                headers={"Range": "bytes=0-127"},
                timeout=(10, 45),
                allow_redirects=True,
            )
            content_type = image_response.headers.get("Content-Type", "")
            size = int(image_response.headers.get("Content-Length") or len(image_response.content))
            valid = (
                image_response.status_code in (200, 206)
                and "image" in content_type.lower()
                and image_response.content[:8] == b"\x89PNG\r\n\x1a\n"
            )
            print(
                "PAGE", page_no,
                "STATUS", image_response.status_code,
                "TYPE", content_type,
                "SIZE", size,
                "VALID", valid,
            )
            if valid:
                found_pages.append((page_no, size, image_url))
                misses = 0
            else:
                misses += 1
        except Exception as exc:
            print("PAGE", page_no, "ERROR", repr(exc))
            misses += 1
        if misses >= 3 and found_pages:
            break
    print("FOUND_PAGE_COUNT", len(found_pages))
    print("FOUND_PAGES", found_pages)

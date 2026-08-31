from __future__ import annotations

import html as html_lib
import json
import re
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

REPORT_IDS = [4788440, 4438234, 4069371]
BASE = "https://www.fxbaogao.com"

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

all_assets: set[str] = set()

for report_id in REPORT_IDS:
    for suffix in (f"/detail/{report_id}", f"/view?id={report_id}"):
        url = BASE + suffix
        response = session.get(url, timeout=(20, 180), allow_redirects=True)
        print("\nPAGE", report_id, suffix, "STATUS", response.status_code, "FINAL", response.url, "BYTES", len(response.content))
        response.raise_for_status()
        text = html_lib.unescape(response.text).replace("\\/", "/")
        soup = BeautifulSoup(text, "html.parser")
        print("TITLE", soup.title.get_text(" ", strip=True) if soup.title else "")

        image_matches = sorted(
            set(
                re.findall(
                    rf"https?://public\.fxbaogao\.com/report-image/[^\"'<>\s]+?/{report_id}-(\d+)\.(?:png|jpg|jpeg|webp)",
                    text,
                    flags=re.I,
                )
            ),
            key=int,
        )
        print("IMAGE PAGE NUMBERS", image_matches)

        for tag in soup.find_all("script"):
            src = tag.get("src")
            if src:
                all_assets.add(urljoin(response.url, src))
            body = tag.string or tag.get_text() or ""
            if not body.strip():
                continue
            if any(
                keyword in body.lower()
                for keyword in (
                    str(report_id),
                    "report-image",
                    "pagecount",
                    "page_count",
                    "viewreport",
                    "download",
                )
            ):
                compact = re.sub(r"\s+", " ", body)
                print("INLINE SCRIPT", tag.get("id"), tag.get("type"), compact[:12000])

        for keyword in (
            "report-image",
            "pageCount",
            "page_count",
            "totalPage",
            "downloadUrl",
            "fileUrl",
            "preview",
            "pages",
            "__NEXT_DATA__",
        ):
            positions = [match.start() for match in re.finditer(re.escape(keyword), text, flags=re.I)]
            if positions:
                print("KEY", keyword, "COUNT", len(positions))
            for pos in positions[:6]:
                snippet = re.sub(r"\s+", " ", text[max(0, pos - 500):pos + 1300])
                print("CTX", snippet[:1900])

print("\nASSETS", len(all_assets))
for asset in sorted(all_assets):
    print("ASSET URL", asset)

for asset in sorted(all_assets):
    try:
        response = session.get(asset, timeout=(20, 180))
        if response.status_code != 200:
            continue
        text = response.text
        if not any(
            keyword in text.lower()
            for keyword in (
                "report-image",
                "reportimage",
                "/api/report",
                "pagecount",
                "view?id",
                "downloadreport",
            )
        ):
            continue
        print("\nRELEVANT ASSET", asset, "BYTES", len(response.content))
        for keyword in (
            "report-image",
            "/api/report",
            "pageCount",
            "page_count",
            "download",
            "getReport",
            "viewReport",
            "reportId",
        ):
            positions = [match.start() for match in re.finditer(re.escape(keyword), text, flags=re.I)]
            if positions:
                print("ASSET KEY", keyword, "COUNT", len(positions))
            for pos in positions[:12]:
                snippet = re.sub(r"\s+", " ", text[max(0, pos - 700):pos + 1600])
                print("ASSET CTX", snippet[:2400])
    except Exception as exc:
        print("ASSET ERROR", asset, repr(exc))

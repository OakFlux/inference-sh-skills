#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import csv
import hashlib
import json
import re
import shutil
import time
import zipfile
from pathlib import Path

import pymupdf
import requests
from pypdf import PdfReader

ROOT = Path("dist_liaogang_public_research")
PKG = ROOT / "辽港股份_601880_券商研究公开资料包"
FULL = PKG / "01_可直接取得的完整PDF"
INDEX = PKG / "02_券商研报索引与公开入口"
META = PKG / "03_说明与校验"
RENDER = ROOT / "_verify_renders"
ZIP_PATH = ROOT / "辽港股份_601880_券商研究公开资料包_20261016.zip"
SUMMARY = ROOT / "package_summary.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download_pdf(session: requests.Session, info_code: str, destination: Path) -> str:
    source_page = f"https://data.eastmoney.com/report/info/{info_code}.html"
    urls = [
        f"https://pdf.dfcfw.com/pdf/H3_{info_code}_1.pdf",
        f"https://pdf.dfcfw.com/pdf/H2_{info_code}_1.pdf",
        f"https://pdf.dfcfw.com/pdf/H3_{info_code}_1.pdf?{int(time.time() * 1000)}.pdf=",
        f"https://pdf.dfcfw.com/pdf/H2_{info_code}_1.pdf?{int(time.time() * 1000)}.pdf=",
    ]
    errors: list[str] = []
    for url in urls:
        try:
            response = session.get(
                url,
                headers={"Referer": source_page},
                timeout=180,
                allow_redirects=True,
            )
            print(
                "PDF_TRY",
                response.status_code,
                response.headers.get("content-type"),
                len(response.content),
                response.url,
                flush=True,
            )
            response.raise_for_status()
            if not response.content.startswith(b"%PDF-") or len(response.content) < 40_000:
                raise RuntimeError("Invalid PDF payload")
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(response.content)
            return str(response.url)
        except Exception as exc:  # noqa: BLE001
            errors.append(repr(exc))
            destination.unlink(missing_ok=True)
    raise RuntimeError("Unable to download institutional PDF: " + " | ".join(errors))


def main() -> None:
    if ROOT.exists():
        shutil.rmtree(ROOT)
    for directory in (FULL, INDEX, META, RENDER):
        directory.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 Chrome/155 Safari/537.36"
            ),
            "Accept": "application/pdf,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }
    )

    pdf_dest = FULL / "补充_20240930_亿渡数据_辽港股份机构研究报告_非券商.pdf"
    pdf_url = download_pdf(session, "AP202409301640100556", pdf_dest)

    reader = PdfReader(str(pdf_dest), strict=False)
    pages = len(reader.pages)
    if pages != 8:
        raise RuntimeError(f"Unexpected page count for 亿渡数据 PDF: {pages}")

    sampled: list[str] = []
    for index in sorted({0, 1, min(3, pages - 1), pages - 1}):
        try:
            sampled.append(reader.pages[index].extract_text() or "")
        except Exception:  # noqa: BLE001
            pass
    normalized = re.sub(r"\s+", "", "\n".join(sampled))
    if not any(marker in normalized for marker in ("辽港股份", "辽宁港口股份有限公司", "601880")):
        raise RuntimeError("Company identity missing in institutional PDF")

    with pymupdf.open(pdf_dest) as document:
        for page_index, label in ((0, "first"), (len(document) - 1, "last")):
            pixmap = document[page_index].get_pixmap(
                matrix=pymupdf.Matrix(1.4, 1.4),
                alpha=False,
            )
            image = RENDER / f"yidu_{label}.png"
            pixmap.save(image)
            if image.stat().st_size < 5_000:
                raise RuntimeError(f"Rendered page is unexpectedly small: {image}")

    records = [
        {
            "sequence": 1,
            "institution": "招商证券",
            "date": "2025-08-05",
            "title": "东北地区最大码头运营商，业务综合性强",
            "type": "正式公司深度报告",
            "verified_pages": 22,
            "analysts": "王春环、孙修远、肖欣晨、刘若琮、张瑜玲",
            "status": (
                "已核实题目、机构、日期与22页记录；原PDF公开附件需要登录或付费，"
                "本包未绕过访问限制，未收录全文"
            ),
            "primary_url": "https://finance.sina.com.cn/roll/2025-08-06/doc-infiywak1190454.shtml",
            "archive_url": "https://www.ifxh.com/2732.html",
        },
        {
            "sequence": 2,
            "institution": "招商证券",
            "date": "2026-03-30",
            "title": "25年业绩稳健增长，归母净利同比+14%",
            "type": "公司跟踪/年报点评",
            "verified_pages": "",
            "analysts": "",
            "status": "公开全文网页可阅读；未找到可直接下载且可验证的原始PDF附件",
            "primary_url": (
                "https://stock.finance.sina.com.cn/stock/go.php/"
                "vReport_Show/kind/search/rptid/828179450864/index.phtml"
            ),
            "archive_url": "",
        },
        {
            "sequence": 3,
            "institution": "招商证券",
            "date": "2026-09-08",
            "title": "集装箱业务表现稳健，Q2业绩环比向好",
            "type": "公司跟踪/中报点评",
            "verified_pages": 4,
            "analysts": "",
            "status": (
                "公开全文网页可阅读；历史附件记录为4页，但原PDF下载入口受限，"
                "本包未绕过访问限制"
            ),
            "primary_url": (
                "https://stock.finance.sina.com.cn/stock/go.php/"
                "vReport_Show/kind/search/rptid/842168040243/index.phtml"
            ),
            "archive_url": "",
        },
    ]

    for record in records:
        sequence = int(record["sequence"])
        date = str(record["date"]).replace("-", "")
        safe_title = re.sub(r"[\\/:*?\"<>|]", "_", str(record["title"]))
        text_path = INDEX / (
            f"{sequence:02d}_{date}_{record['institution']}_{safe_title}_索引记录_非全文.txt"
        )
        lines = [
            "辽港股份券商研报索引记录（非报告全文）",
            "",
            f"机构：{record['institution']}",
            f"日期：{record['date']}",
            f"题目：{record['title']}",
            f"类型：{record['type']}",
            f"已核实页数：{record['verified_pages'] or '未确认'}",
            f"分析师：{record['analysts'] or '公开页面未列明'}",
            f"文件状态：{record['status']}",
            f"公开入口：{record['primary_url']}",
        ]
        if record["archive_url"]:
            lines.append(f"附件索引页：{record['archive_url']}")
        lines.extend(["", "本文件仅为来源与状态记录，不是券商报告全文。"])
        text_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        shortcut = INDEX / (
            f"{sequence:02d}_{date}_{record['institution']}_{safe_title}_公开入口.url"
        )
        shortcut.write_text(
            "[InternetShortcut]\nURL=" + str(record["primary_url"]) + "\n",
            encoding="utf-8",
        )

    readme_lines = [
        "辽港股份（601880）券商研究公开资料包",
        "整理日期：2026-10-16",
        "",
        "重要说明",
        "========",
        "1. 严格按“券商公司深度报告完整PDF”口径检索，已确认招商证券2025-08-05",
        "   《东北地区最大码头运营商，业务综合性强》为22页正式深度报告。",
        "2. 该22页原始PDF目前可见的附件入口需要登录、积分或付费。本包没有绕过访问限制，",
        "   也没有用预览页或网页摘要冒充报告全文。",
        "3. 另收录招商证券2026-03-30与2026-09-08两份公司跟踪报告的公开阅读快捷入口",
        "   及索引记录；它们不是20页以上长篇深度报告。",
        "4. 包内唯一完整PDF为亿渡数据2024-09-30的8页机构研究报告。亿渡数据不是证券公司，",
        "   该文件仅作补充材料，不能视为券商深度报告。",
        "",
        "目录",
        "====",
        "01_可直接取得的完整PDF",
        "- 补充_20240930_亿渡数据_辽港股份机构研究报告_非券商.pdf（8页，完整PDF）",
        "",
        "02_券商研报索引与公开入口",
        "- 招商证券2025年22页深度报告：索引记录与公开来源入口，非全文",
        "- 招商证券2026年年报点评：公开网页快捷入口，非原始PDF",
        "- 招商证券2026年中报点评：公开网页快捷入口，非原始PDF",
        "",
        "校验",
        "====",
        "- 亿渡数据PDF：文件头、实际页数、公司身份、首页与末页渲染、SHA-256",
        "- ZIP：CRC完整性测试",
        "- 券商索引：题目、机构、日期、公开页数记录与访问状态核对",
        "",
        "资料仅供个人研究参考，不构成投资建议。报告版权归相应机构与作者所有。",
    ]
    (PKG / "00_重要说明与文件清单.txt").write_text(
        "\n".join(readme_lines) + "\n",
        encoding="utf-8",
    )

    with (META / "券商研报索引.csv").open(
        "w",
        encoding="utf-8-sig",
        newline="",
    ) as handle:
        fields = [
            "sequence",
            "institution",
            "date",
            "title",
            "type",
            "verified_pages",
            "analysts",
            "status",
            "primary_url",
            "archive_url",
        ]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(records)

    yidu_sha = sha256(pdf_dest)
    manifest = {
        "company": "辽港股份",
        "company_full_name": "辽宁港口股份有限公司",
        "stock_code": "601880",
        "as_of": "2026-10-16",
        "strict_complete_broker_pdf_count": 0,
        "verified_broker_report_records": records,
        "supplementary_complete_pdf": {
            "institution": "亿渡数据",
            "is_broker": False,
            "date": "2024-09-30",
            "title": "持续推进国企改革与资产优化，价值有望重估",
            "pages": pages,
            "source_page": "https://data.eastmoney.com/report/info/AP202409301640100556.html",
            "pdf_url": pdf_url,
            "relative_path": str(pdf_dest.relative_to(PKG)),
            "bytes": pdf_dest.stat().st_size,
            "sha256": yidu_sha,
        },
        "scope_note": "未绕过任何登录、付费、积分或会员限制；索引记录明确标注非全文。",
    }
    (META / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (META / "SHA256SUMS.txt").write_text(
        f"{yidu_sha}  {pdf_dest.relative_to(PKG)}\n",
        encoding="utf-8",
    )

    ZIP_PATH.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(
        ZIP_PATH,
        "w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=6,
    ) as archive:
        for path in sorted(PKG.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(ROOT))

    with zipfile.ZipFile(ZIP_PATH, "r") as archive:
        bad = archive.testzip()
        if bad:
            raise RuntimeError(f"ZIP CRC failed: {bad}")
        pdfs = [name for name in archive.namelist() if name.lower().endswith(".pdf")]
        if len(pdfs) != 1:
            raise RuntimeError(f"Unexpected PDF count: {pdfs}")

    summary = {
        "zip": str(ZIP_PATH),
        "zip_bytes": ZIP_PATH.stat().st_size,
        "zip_sha256": sha256(ZIP_PATH),
        "complete_pdf_count": 1,
        "strict_broker_complete_pdf_count": 0,
        "broker_index_record_count": 3,
        "supplementary_pdf_pages": pages,
        "records": records,
    }
    SUMMARY.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()

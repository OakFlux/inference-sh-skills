from __future__ import annotations

import json
import shutil
import zipfile
from pathlib import Path
from typing import Any

import package_biyi_broker_reports as base


ROOT = Path.cwd()
PACKAGE = ROOT / "hengxuan_broker_reports_verified"
REPORT_DIR = PACKAGE / "01_券商深度报告"
OUTPUT = ROOT / "恒玄科技_券商深度报告_精选_完整PDF.zip"

STOCK_CODE = "688608"
COMPANY = "恒玄科技（上海）股份有限公司"
SHORT_NAME = "恒玄科技"
PREPARED_DATE = "2026-08-30"

# 三份均为2025年发布、篇幅完整的公司深度/专题研究报告。
REPORTS: list[dict[str, Any]] = [
    {
        "info_code": "AP202506251697539456",
        "broker": "东海证券",
        "publish_date": "2025-06-26",
        "researcher": "方霁",
        "title": "公司深度报告：高制程打造长期壁垒，端侧AI布局多条成长路径",
        "expected_pages": 23,
    },
    {
        "info_code": "AP202505241678370953",
        "broker": "东吴证券",
        "publish_date": "2025-05-24",
        "researcher": "",
        "title": "平台型SoC芯片龙头，AI眼镜再探可穿戴市场新机遇",
        "expected_pages": 25,
    },
    {
        "info_code": "AP202504241661534261",
        "broker": "国金证券",
        "publish_date": "2025-04-24",
        "researcher": "",
        "title": "低功耗计算SoC龙头，端侧新周期再出发",
        "expected_pages": 22,
    },
]


def main() -> None:
    if PACKAGE.exists():
        shutil.rmtree(PACKAGE)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT.unlink(missing_ok=True)

    # Override the validated downloader/inspector's company-specific globals.
    base.STOCK_CODE = STOCK_CODE
    base.COMPANY = COMPANY
    base.SHORT_NAME = SHORT_NAME

    documents: list[dict[str, Any]] = []
    checksum_lines: list[str] = []

    for index, record in enumerate(REPORTS, 1):
        filename = base.safe_filename(
            f"{index:02d}_{record['broker']}_{record['publish_date'].replace('-', '')}_"
            f"{record['title']}.pdf"
        )
        target = REPORT_DIR / filename
        source_pdf = base.download_pdf(record, target)
        metadata = base.inspect_pdf(target, record)

        if int(metadata["pages"]) != int(record["expected_pages"]):
            raise RuntimeError(
                f"Page-count mismatch for {record['title']}: "
                f"{metadata['pages']} != {record['expected_pages']}"
            )

        # 标题特征必须出现在前部，避免只在同业比较中提及恒玄科技的误收。
        import fitz

        document = fitz.open(target)
        front_text = "\n".join(
            document.load_page(page_index).get_text("text")
            for page_index in range(min(8, document.page_count))
        )
        document.close()
        compact = base.normalize(front_text)
        title_markers = {
            "AP202506251697539456": ("高制程打造长期壁垒", "端侧ai"),
            "AP202505241678370953": ("平台型soc芯片龙头", "ai眼镜"),
            "AP202504241661534261": ("低功耗计算soc龙头", "端侧新周期"),
        }[record["info_code"]]
        if not all(base.normalize(marker) in compact for marker in title_markers):
            raise RuntimeError(f"Title markers missing from report front: {target}")

        rel_path = str(target.relative_to(PACKAGE))
        item = {
            "company": SHORT_NAME,
            "stock_code": STOCK_CODE,
            "broker": record["broker"],
            "title": record["title"],
            "publish_date": record["publish_date"],
            "researcher": record["researcher"],
            "file": rel_path,
            "pages": metadata["pages"],
            "bytes": metadata["bytes"],
            "sha256": metadata["sha256"],
            "source_page": (
                f"https://data.eastmoney.com/report/info/{record['info_code']}.html"
            ),
            "source_pdf": source_pdf,
            "info_code": record["info_code"],
        }
        documents.append(item)
        checksum_lines.append(f"{item['sha256']}  {rel_path}")

    if len(documents) != 3:
        raise RuntimeError(f"Expected 3 reports, found {len(documents)}")

    total_pages = sum(int(item["pages"]) for item in documents)
    total_bytes = sum(int(item["bytes"]) for item in documents)

    readme_lines = [
        f"{COMPANY}（{STOCK_CODE}.SH，{SHORT_NAME}）券商深度研究报告",
        f"整理日期：{PREPARED_DATE}",
        "",
        "筛选口径",
        "1. 仅收录公开可下载、正文篇幅完整的公司深度或系统性专题报告。",
        "2. 本包优先选择2025年报告，排除仅数页的季报点评、业绩快报和资讯摘要。",
        "3. 三份报告来自不同券商，便于比较研究框架、业务假设和盈利预测。",
        "",
        "文件清单",
    ]
    for index, item in enumerate(documents, 1):
        readme_lines.extend(
            [
                f"{index}. {item['broker']}：{item['title']}",
                f"   发布日期：{item['publish_date']}",
                f"   研究员：{item['researcher'] or 'PDF正文所列团队'}",
                f"   页数：{item['pages']}",
                f"   文件：{item['file']}",
                f"   来源页面：{item['source_page']}",
                f"   SHA-256：{item['sha256']}",
                "",
            ]
        )

    readme_lines.extend(
        [
            "完整性检查",
            f"- 共3份PDF，合计{total_pages}页，未压缩总大小{total_bytes / 1024 / 1024:.2f} MiB。",
            "- 每份PDF均检查文件头、结构、页数、公司名称、标题特征及证券研究报告标识。",
            "- 已渲染抽查每份PDF的首页、中间页和末页。",
            "- ZIP已通过CRC完整性测试，逐文件哈希见SHA256SUMS.txt。",
        ]
    )

    (PACKAGE / "README_来源与校验.txt").write_text(
        "\n".join(readme_lines), encoding="utf-8"
    )
    (PACKAGE / "SHA256SUMS.txt").write_text(
        "\n".join(checksum_lines) + "\n", encoding="utf-8"
    )
    (PACKAGE / "manifest.json").write_text(
        json.dumps(
            {
                "company": COMPANY,
                "short_name": SHORT_NAME,
                "stock_code": STOCK_CODE,
                "ticker": f"{STOCK_CODE}.SH",
                "prepared_date": PREPARED_DATE,
                "selection_policy": "2025年公开可下载的完整公司深度/专题报告",
                "documents": documents,
                "total_pages": total_pages,
                "total_bytes": total_bytes,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    with zipfile.ZipFile(
        OUTPUT, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
    ) as archive:
        for path in sorted(PACKAGE.rglob("*")):
            if path.is_file():
                archive.write(path, arcname=str(path.relative_to(PACKAGE)))

    with zipfile.ZipFile(OUTPUT, "r") as archive:
        bad = archive.testzip()
        if bad:
            raise RuntimeError(f"ZIP CRC failure: {bad}")
        pdfs = [name for name in archive.namelist() if name.lower().endswith(".pdf")]
        if len(pdfs) != 3:
            raise RuntimeError(f"Expected 3 PDFs, found {len(pdfs)}")

    print("\n".join(readme_lines))
    print(f"ZIP_FILE={OUTPUT}")
    print(f"ZIP_BYTES={OUTPUT.stat().st_size}")
    print(f"ZIP_SHA256={base.sha256(OUTPUT)}")


if __name__ == "__main__":
    main()

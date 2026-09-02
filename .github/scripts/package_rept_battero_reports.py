from __future__ import annotations

import csv
import hashlib
import io
import json
import subprocess
import time
import zipfile
from pathlib import Path

import img2pdf
import requests
from PIL import Image
from pypdf import PdfReader

PACKAGE = "瑞浦兰钧_00666HK_券商深度报告_2份_完整公开版"
OUT = Path(PACKAGE)
WORK = Path("_rept_final_work")
RENDERS = WORK / "renders"
OUT.mkdir(exist_ok=True)
RENDERS.mkdir(parents=True, exist_ok=True)

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/151 Safari/537.36"
SESSION = requests.Session()

REPORTS = [
    {
        "order": 1,
        "institution": "海通国际",
        "date": "2024-05-31",
        "pages": 22,
        "report_type": "首次覆盖报告",
        "rating": "优于大市",
        "researchers": "陈兆庆、曾彪",
        "title": "青山集团旗下锂电池公司，海外营收快速增长",
        "detail_url": "https://www.sdyanbao.com/detail/768016",
        "image_base": "https://oss.sdyanbao.com/page/2024/5/31/1017103",
        "filename": "01_海通国际_瑞浦兰钧_首次覆盖_青山集团旗下锂电池公司海外营收快速增长_2024-05-31_22页.pdf",
    },
    {
        "order": 2,
        "institution": "华龙证券",
        "date": "2024-07-26",
        "pages": 24,
        "report_type": "公司深度报告",
        "rating": "未标注",
        "researchers": "未标注",
        "title": "动力电池老兵焕发新活力，多元赛道助力全球布局",
        "detail_url": "https://www.sdyanbao.com/detail/780251",
        "image_base": "https://oss.sdyanbao.com/page/2024/7/26/1032354",
        "filename": "02_华龙证券_瑞浦兰钧_动力电池老兵焕发新活力多元赛道助力全球布局_2024-07-26_24页.pdf",
    },
]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def fetch_image(url: str, referer: str) -> tuple[bytes, str, str]:
    errors: list[str] = []
    for attempt in range(1, 5):
        try:
            response = SESSION.get(
                url,
                headers={
                    "User-Agent": UA,
                    "Accept": "image/avif,image/webp,image/apng,image/png,image/jpeg,image/*,*/*;q=0.8",
                    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
                    "Referer": referer,
                    "Cache-Control": "no-cache",
                },
                timeout=(20, 180),
                allow_redirects=True,
            )
            print(
                "GET",
                url,
                response.status_code,
                response.headers.get("content-type"),
                len(response.content),
                response.url,
                flush=True,
            )
            if response.status_code == 200 and len(response.content) > 5_000:
                return response.content, response.url, response.headers.get("content-type", "")
            errors.append(f"HTTP {response.status_code}; {len(response.content)} bytes")
        except Exception as exc:
            errors.append(repr(exc))
        time.sleep(attempt)
    raise RuntimeError(f"Failed to fetch {url}: {errors}")


def build_report(spec: dict) -> dict:
    page_dir = WORK / f"pages_{spec['order']:02d}"
    page_dir.mkdir(parents=True, exist_ok=True)
    normalized_pages: list[Path] = []
    page_manifest: list[dict] = []

    for index in range(spec["pages"]):
        source_url = f"{spec['image_base']}/{index}.png"
        body, final_url, content_type = fetch_image(source_url, spec["detail_url"])

        with Image.open(io.BytesIO(body)) as image:
            image.verify()
        with Image.open(io.BytesIO(body)) as image:
            width, height = image.size
            source_format = (image.format or "").upper()
            if width < 500 or height < 700:
                raise RuntimeError(f"Page {index + 1} is too small: {width}x{height}")
            normalized_path = page_dir / f"{index + 1:03d}.png"
            image.convert("RGB").save(normalized_path, format="PNG", optimize=False)

        normalized_pages.append(normalized_path)
        page_manifest.append(
            {
                "page": index + 1,
                "source_url": final_url,
                "source_content_type": content_type,
                "source_format": source_format,
                "width": width,
                "height": height,
                "source_bytes": len(body),
                "source_sha256": hashlib.sha256(body).hexdigest(),
                "normalized_sha256": sha256_file(normalized_path),
            }
        )
        print(
            "PAGE_OK",
            spec["order"],
            index + 1,
            source_format,
            width,
            height,
            len(body),
            flush=True,
        )

    if len(normalized_pages) != spec["pages"]:
        raise RuntimeError("Incomplete report page set")
    if len({item["source_sha256"] for item in page_manifest}) != spec["pages"]:
        raise RuntimeError("Duplicate source page image detected")

    pdf_path = OUT / spec["filename"]
    pdf_path.write_bytes(img2pdf.convert([str(path) for path in normalized_pages]))
    with pdf_path.open("rb") as handle:
        if handle.read(5) != b"%PDF-":
            raise RuntimeError("PDF signature missing")

    reader = PdfReader(str(pdf_path), strict=False)
    actual_pages = len(reader.pages)
    if actual_pages != spec["pages"]:
        raise RuntimeError(f"PDF has {actual_pages} pages; expected {spec['pages']}")

    qpdf_result = subprocess.run(
        ["qpdf", "--check", str(pdf_path)],
        capture_output=True,
        text=True,
    )
    if qpdf_result.returncode not in (0, 3):
        raise RuntimeError(f"qpdf check failed: {qpdf_result.stderr[-1000:]}")

    render_checks: list[dict] = []
    for label, page_number in (("first", 1), ("last", actual_pages)):
        prefix = RENDERS / f"{pdf_path.stem}_{label}"
        subprocess.run(
            [
                "pdftoppm",
                "-f",
                str(page_number),
                "-singlefile",
                "-png",
                "-r",
                "120",
                str(pdf_path),
                str(prefix),
            ],
            check=True,
            capture_output=True,
        )
        rendered_path = Path(str(prefix) + ".png")
        if not rendered_path.exists() or rendered_path.stat().st_size < 10_000:
            raise RuntimeError(f"Render failed for {pdf_path.name}, {label}")
        with Image.open(rendered_path) as rendered:
            render_width, render_height = rendered.size
        if render_width < 700 or render_height < 900:
            raise RuntimeError(
                f"Rendered page is too small for {pdf_path.name}: "
                f"{render_width}x{render_height}"
            )
        render_checks.append(
            {
                "label": label,
                "page": page_number,
                "file": rendered_path.name,
                "bytes": rendered_path.stat().st_size,
                "width": render_width,
                "height": render_height,
            }
        )

    return {
        **spec,
        "company": "瑞浦兰钧能源股份有限公司",
        "company_en": "REPT BATTERO Energy Co., Ltd.",
        "ticker": "00666.HK",
        "source_type": "公开逐页原版图像按原页序无损合成PDF",
        "source_image_pattern": spec["image_base"] + "/{page_index_0_based}.png",
        "image_manifest": page_manifest,
        "pdf_bytes": pdf_path.stat().st_size,
        "pdf_sha256": sha256_file(pdf_path),
        "render_checks": render_checks,
    }


def main() -> None:
    records = [build_report(spec) for spec in REPORTS]
    if len(records) != 2 or len({record["pdf_sha256"] for record in records}) != 2:
        raise RuntimeError("Report count or uniqueness validation failed")
    if sum(record["pages"] for record in records) != 46:
        raise RuntimeError("Combined page count must be 46")

    readme_lines = [
        "瑞浦兰钧能源股份有限公司（REPT BATTERO，00666.HK）券商深度报告合集",
        "整理日期：2026-09-02",
        "",
        "一、收录报告",
    ]
    for record in records:
        readme_lines.extend(
            [
                f"{record['order']}. {record['institution']}｜{record['date']}｜"
                f"{record['report_type']}｜{record['pages']}页",
                f"   标题：{record['title']}",
                f"   评级：{record['rating']}；分析师：{record['researchers']}",
                f"   文件：{record['filename']}",
                f"   SHA-256：{record['pdf_sha256']}",
                "",
            ]
        )
    readme_lines.extend(
        [
            "二、版本说明",
            "两份报告均由公开详情页对应的逐页原版图像，按照报告原页序逐页无损合成为PDF；未改写、删页或重排。",
            "公开渠道中另有2025年及2026年跟踪报告，但目前只开放前两页预览，因此未混入本包。",
            "",
            "三、完整性核验",
            "已核验逐页数量与顺序、图像格式与尺寸、重复页、PDF文件头、实际页数、qpdf结构、首页及末页渲染、SHA-256、PDF去重及ZIP CRC。",
            "资料仅供研究参考，版权归原研究机构及作者所有，不构成投资建议。",
        ]
    )
    (OUT / "00_报告清单与核验说明.txt").write_text(
        "\n".join(readme_lines), encoding="utf-8"
    )

    with (OUT / "报告清单.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        fields = [
            "序号",
            "机构",
            "报告日期",
            "报告类型",
            "标题",
            "评级",
            "分析师",
            "页数",
            "文件大小_字节",
            "版本",
            "SHA256",
            "来源页面",
            "文件名",
        ]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for record in records:
            writer.writerow(
                {
                    "序号": record["order"],
                    "机构": record["institution"],
                    "报告日期": record["date"],
                    "报告类型": record["report_type"],
                    "标题": record["title"],
                    "评级": record["rating"],
                    "分析师": record["researchers"],
                    "页数": record["pages"],
                    "文件大小_字节": record["pdf_bytes"],
                    "版本": record["source_type"],
                    "SHA256": record["pdf_sha256"],
                    "来源页面": record["detail_url"],
                    "文件名": record["filename"],
                }
            )

    (OUT / "manifest.json").write_text(
        json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (OUT / "SHA256SUMS.txt").write_text(
        "".join(
            f"{record['pdf_sha256']}  {record['filename']}\n" for record in records
        ),
        encoding="utf-8",
    )

    zip_path = Path(PACKAGE + ".zip")
    with zipfile.ZipFile(
        zip_path,
        "w",
        zipfile.ZIP_DEFLATED,
        compresslevel=9,
        allowZip64=True,
    ) as archive:
        for path in sorted(OUT.iterdir()):
            archive.write(path, arcname=f"{PACKAGE}/{path.name}")

    with zipfile.ZipFile(zip_path, "r") as archive:
        bad_member = archive.testzip()
        if bad_member:
            raise RuntimeError(f"ZIP CRC failure: {bad_member}")
        pdf_names = [name for name in archive.namelist() if name.lower().endswith(".pdf")]
        if len(pdf_names) != 2:
            raise RuntimeError(f"ZIP contains {len(pdf_names)} PDFs instead of 2")

    bundle_hash = sha256_file(zip_path)
    Path("FINAL_ZIP_SHA256.txt").write_text(
        f"{bundle_hash}  {zip_path.name}\n", encoding="utf-8"
    )
    print(
        "FINAL_ZIP",
        zip_path.name,
        zip_path.stat().st_size,
        bundle_hash,
        flush=True,
    )
    print(
        "FINAL_RECORDS",
        json.dumps(
            [
                {
                    key: record[key]
                    for key in (
                        "order",
                        "institution",
                        "date",
                        "title",
                        "pages",
                        "pdf_bytes",
                        "pdf_sha256",
                    )
                }
                for record in records
            ],
            ensure_ascii=False,
            indent=2,
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()

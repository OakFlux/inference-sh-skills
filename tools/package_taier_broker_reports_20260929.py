from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import time
import zipfile
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any

import requests
from PIL import Image
from pypdf import PdfReader

COMPANY_CURRENT = "泰尔股份"
COMPANY_FORMER = "泰尔重工"
STOCK_CODE = "002347"
ROOT = Path("泰尔股份_002347_券商研究报告_3份")
REPORT_DIR = ROOT / "01_券商报告"
NOTES_DIR = ROOT / "02_资料说明"
TMP_DIR = Path("_tmp_taier_broker_reports")
PREVIEW_DIR = Path("_previews_taier_broker_reports")
ZIP_PATH = Path("泰尔股份_002347_券商研究报告_3份.zip")
RESULT_JSON = Path("taier_broker_reports_result.json")

REPORTS = [
    {
        "order": 1,
        "doc_id": 1531832,
        "date": "2010-01-14",
        "date_path": "2010/01/14",
        "institution": "安信证券",
        "authors": "林晟",
        "title": "泰尔重工：联轴器细分龙头，受冶金业影响较大",
        "filename": "01_安信证券_2010-01-14_联轴器细分龙头_受冶金业影响较大_公开逐页图像重建版.pdf",
        "detail_url": "https://www.fxbaogao.com/detail/1531832",
    },
    {
        "order": 2,
        "doc_id": 1531967,
        "date": "2010-01-14",
        "date_path": "2010/01/14",
        "institution": "国信证券",
        "authors": "黄海培",
        "title": "泰尔重工：产能扩张，巩固龙头地位",
        "filename": "02_国信证券_2010-01-14_产能扩张_巩固龙头地位_公开逐页图像重建版.pdf",
        "detail_url": "https://www.fxbaogao.com/detail/1531967",
    },
    {
        "order": 3,
        "doc_id": 1532060,
        "date": "2010-01-15",
        "date_path": "2010/01/15",
        "institution": "长城证券",
        "authors": "徐星月",
        "title": "泰尔重工：冶金联轴器龙头，立足于进口替代",
        "filename": "03_长城证券_2010-01-15_冶金联轴器龙头_立足于进口替代_公开逐页图像重建版.pdf",
        "detail_url": "https://www.fxbaogao.com/detail/1532060",
    },
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/152.0.0.0 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def reset_outputs() -> None:
    for path in (ROOT, TMP_DIR, PREVIEW_DIR):
        if path.exists():
            shutil.rmtree(path)
    for path in (ZIP_PATH, RESULT_JSON):
        if path.exists():
            path.unlink()
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    NOTES_DIR.mkdir(parents=True, exist_ok=True)
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    PREVIEW_DIR.mkdir(parents=True, exist_ok=True)


def flatten_on_white(image: Image.Image) -> Image.Image:
    rgba = image.convert("RGBA")
    white = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
    white.alpha_composite(rgba)
    return white.convert("RGB")


def download_report_pages(session: requests.Session, report: dict[str, Any]) -> tuple[list[Image.Image], list[dict[str, Any]]]:
    images: list[Image.Image] = []
    records: list[dict[str, Any]] = []
    consecutive_misses = 0
    for page_number in range(1, 81):
        url = (
            f"https://public.fxbaogao.com/report-image/{report['date_path']}/"
            f"{report['doc_id']}-{page_number}.png"
        )
        response = session.get(
            url,
            headers={
                **HEADERS,
                "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
                "Referer": f"https://www.fxbaogao.com/view?id={report['doc_id']}",
            },
            timeout=(20, 90),
            allow_redirects=True,
        )
        record: dict[str, Any] = {
            "page": page_number,
            "url": url,
            "status": response.status_code,
            "bytes": len(response.content),
            "content_type": response.headers.get("content-type"),
        }
        if response.status_code == 200 and len(response.content) > 10_000:
            image = Image.open(BytesIO(response.content))
            image.load()
            if image.width < 700 or image.height < 900:
                raise RuntimeError(f"{report['institution']}第{page_number}页尺寸异常：{image.size}")
            rgb = flatten_on_white(image)
            record.update(
                {
                    "format": image.format,
                    "width": image.width,
                    "height": image.height,
                    "mode": image.mode,
                }
            )
            images.append(rgb)
            records.append(record)
            consecutive_misses = 0
            print("PAGE_OK", report["doc_id"], json.dumps(record, ensure_ascii=False), flush=True)
        else:
            records.append(record)
            consecutive_misses += 1
            print("PAGE_MISS", report["doc_id"], json.dumps(record, ensure_ascii=False), flush=True)
            if consecutive_misses >= 3:
                break
    if len(images) < 2:
        raise RuntimeError(f"{report['institution']}仅取得{len(images)}页公开报告图像")
    return images, records


def images_to_pdf(images: list[Image.Image], destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    first, rest = images[0], images[1:]
    first.save(
        destination,
        "PDF",
        resolution=150.0,
        save_all=True,
        append_images=rest,
        quality=95,
        optimize=False,
    )


def validate_pdf(path: Path, expected_pages: int) -> dict[str, Any]:
    if not path.exists() or path.stat().st_size < 80_000:
        raise RuntimeError(f"PDF不存在或文件过小：{path}")
    with path.open("rb") as stream:
        if stream.read(5) != b"%PDF-":
            raise RuntimeError(f"PDF文件头无效：{path}")
    reader = PdfReader(str(path), strict=False)
    pages = len(reader.pages)
    if pages != expected_pages:
        raise RuntimeError(f"{path.name}页数{pages}，预期{expected_pages}")

    qpdf = subprocess.run(
        ["qpdf", "--check", str(path)],
        capture_output=True,
        text=True,
        timeout=180,
    )
    if qpdf.returncode not in (0, 3):
        raise RuntimeError(f"qpdf校验失败：{path.name}: {qpdf.stderr[-1000:]}")

    first_base = PREVIEW_DIR / f"{path.stem}_page1"
    last_base = PREVIEW_DIR / f"{path.stem}_page{pages}"
    subprocess.run(
        ["pdftoppm", "-f", "1", "-l", "1", "-singlefile", "-png", "-r", "140", str(path), str(first_base)],
        check=True,
        capture_output=True,
        timeout=180,
    )
    subprocess.run(
        ["pdftoppm", "-f", str(pages), "-l", str(pages), "-singlefile", "-png", "-r", "140", str(path), str(last_base)],
        check=True,
        capture_output=True,
        timeout=180,
    )
    first_preview = first_base.with_suffix(".png")
    last_preview = last_base.with_suffix(".png")
    for preview in (first_preview, last_preview):
        if not preview.exists() or preview.stat().st_size < 8_000:
            raise RuntimeError(f"页面渲染失败：{preview}")

    result = {
        "pages": pages,
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
        "qpdf_return_code": qpdf.returncode,
        "first_page_preview": str(first_preview),
        "last_page_preview": str(last_preview),
    }
    print("PDF_VALIDATED", path.name, json.dumps(result, ensure_ascii=False), flush=True)
    return result


def build_package() -> None:
    reset_outputs()
    session = requests.Session()
    session.headers.update(HEADERS)
    records: list[dict[str, Any]] = []

    for report in REPORTS:
        images: list[Image.Image] = []
        try:
            images, page_records = download_report_pages(session, report)
            temp_pdf = TMP_DIR / report["filename"]
            images_to_pdf(images, temp_pdf)
            validation = validate_pdf(temp_pdf, len(images))
            final_pdf = REPORT_DIR / report["filename"]
            shutil.move(str(temp_pdf), str(final_pdf))
            record = {
                **report,
                **validation,
                "filename": str(final_pdf.relative_to(ROOT)),
                "viewer_url": f"https://www.fxbaogao.com/view?id={report['doc_id']}",
                "page_image_records": page_records,
                "document_type": "公开逐页报告图像重建PDF（页面内容保持原样，非券商原始PDF容器）",
                "historical_name_note": "报告发布时公司证券简称为泰尔重工，现证券简称为泰尔股份。",
            }
            records.append(record)
        finally:
            for image in images:
                try:
                    image.close()
                except Exception:
                    pass

    records.sort(key=lambda item: int(item["order"]))
    manifest = {
        "company_current_name": COMPANY_CURRENT,
        "company_name_at_report_date": COMPANY_FORMER,
        "stock_code": STOCK_CODE,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "report_count": len(records),
        "reports": records,
        "scope_note": (
            "公开可直接取得的泰尔股份长篇公司深度报告较少。本包筛选三份上市初期的单家公司研究报告。"
            "公开平台提供逐页原始报告图像，第三页均不存在，因此按现有两页顺序重建PDF；文件名和清单中已明确标注。"
        ),
        "validation": "所有PDF均完成文件头、实际页数、qpdf结构及首末页渲染检查，ZIP完成CRC测试。",
    }
    (NOTES_DIR / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (NOTES_DIR / "SHA256SUMS.txt").write_text(
        "\n".join(f"{item['sha256']}  {item['filename']}" for item in records) + "\n",
        encoding="utf-8",
    )

    lines = [
        f"公司：{COMPANY_CURRENT}（{STOCK_CODE}.SZ；报告发布时简称：{COMPANY_FORMER}）",
        f"券商研究报告：{len(records)}份",
        "",
        "说明：",
        "- 公开渠道中可稳定取得的泰尔股份长篇公司深度全文较少；本包收录三份上市初期公司研究报告。",
        "- 来源平台公开提供逐页原始报告图像；各报告均仅存在第1—2页，第3页起返回不存在。",
        "- 本次按原页序、原尺寸重建为PDF，页面内容未改写；并非券商原始PDF文件容器。",
        "",
        "文件明细：",
    ]
    for index, item in enumerate(records, start=1):
        lines.extend(
            [
                f"{index}. {item['institution']} | {item['date']} | {item['authors']} | {item['title']}",
                f"   页数：{item['pages']}页；文件：{item['filename']}",
                f"   报告详情：{item['detail_url']}",
            ]
        )
    lines.extend(
        [
            "",
            "校验：",
            "- PDF文件头、页数及qpdf结构检查通过；",
            "- 每份报告首末页均已重新渲染验证；",
            "- SHA-256见SHA256SUMS.txt，完整元数据见manifest.json。",
        ]
    )
    (NOTES_DIR / "资料清单与来源说明.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")

    if ZIP_PATH.exists():
        ZIP_PATH.unlink()
    with zipfile.ZipFile(ZIP_PATH, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(ROOT.rglob("*")):
            if path.is_file():
                archive.write(path, path.as_posix())
    with zipfile.ZipFile(ZIP_PATH, "r") as archive:
        bad = archive.testzip()
        if bad:
            raise RuntimeError(f"ZIP CRC校验失败：{bad}")

    result = {
        "zip_filename": ZIP_PATH.name,
        "zip_bytes": ZIP_PATH.stat().st_size,
        "zip_sha256": sha256(ZIP_PATH),
        "report_count": len(records),
        "reports": records,
    }
    RESULT_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print("PACKAGE_COMPLETE", json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    build_package()

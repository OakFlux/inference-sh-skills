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

COMPANY = "任子行"
STOCK_CODE = "300311"
ROOT = Path("任子行_300311_券商研究报告_2份")
REPORT_DIR = ROOT / "01_券商报告"
NOTES_DIR = ROOT / "02_资料说明"
TMP_DIR = Path("_tmp_renzixing_broker_reports")
PREVIEW_DIR = Path("_previews_renzixing_broker_reports")
ZIP_PATH = Path("任子行_300311_券商研究报告_2份.zip")
RESULT_JSON = Path("renzixing_broker_reports_result.json")

REPORT_2018 = {
    "order": 1,
    "institution": "新时代证券",
    "date": "2018-08-29",
    "title": "上半年净利润增速62.65%，网络信息安全业务增速显著",
    "authors": "田杰华、刘航、孙业亮",
    "rating": "增持",
    "info_code": "AP201808291184449051",
    "filename": "01_新时代证券_2018-08-29_上半年净利润增速62.65%_网络信息安全业务增速显著.pdf",
    "pdf_urls": [
        "https://pdf.dfcfw.com/pdf/H3_AP201808291184449051_1.pdf?1535520000000.pdf=",
        "https://pdf.dfcfw.com/pdf/H3_AP201808291184449051_1.pdf",
    ],
    "page_url": "https://data.eastmoney.com/report/info/AP201808291184449051.html",
    "classification": "公司研究报告",
}

REPORT_2016 = {
    "order": 2,
    "institution": "太平洋证券",
    "date": "2016-04-21",
    "title": "行业景气外延助力，持续高成长可期",
    "authors": "张学、徐中华",
    "rating": "买入（首次）",
    "doc_id": 71024,
    "filename": "02_太平洋证券_2016-04-21_行业景气外延助力_持续高成长可期_公开2页重建版.pdf",
    "detail_url": "https://www.fxbaogao.com/detail/71024",
    "viewer_url": "https://www.fxbaogao.com/view?id=71024",
    "image_base": "https://public.fxbaogao.com/report-image/2016/04/21/71024-{page}.png",
    "original_report_pages": 4,
    "public_pages_available": 2,
    "classification": "公司点评报告",
}

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


def download_original_pdf(session: requests.Session, report: dict[str, Any], destination: Path) -> str:
    last_error: Exception | None = None
    for url in report["pdf_urls"]:
        for attempt in range(1, 5):
            part = destination.with_suffix(destination.suffix + ".part")
            try:
                if part.exists():
                    part.unlink()
                headers = {
                    **HEADERS,
                    "Accept": "application/pdf,application/octet-stream;q=0.9,*/*;q=0.8",
                    "Referer": report["page_url"],
                }
                with session.get(url, headers=headers, stream=True, timeout=(30, 180), allow_redirects=True) as response:
                    print(
                        "PDF_RESPONSE",
                        report["info_code"],
                        attempt,
                        response.status_code,
                        response.url,
                        response.headers.get("content-type"),
                        response.headers.get("content-length"),
                        flush=True,
                    )
                    response.raise_for_status()
                    with part.open("wb") as stream:
                        for chunk in response.iter_content(1024 * 1024):
                            if chunk:
                                stream.write(chunk)
                if part.stat().st_size < 100_000:
                    raise RuntimeError(f"PDF文件过小：{part.stat().st_size}")
                with part.open("rb") as stream:
                    if stream.read(5) != b"%PDF-":
                        raise RuntimeError("下载内容不是PDF")
                part.replace(destination)
                print("PDF_DOWNLOADED", destination, destination.stat().st_size, url, flush=True)
                return url
            except Exception as exc:
                last_error = exc
                print("PDF_RETRY", report["info_code"], attempt, url, repr(exc), flush=True)
                time.sleep(attempt * 2)
    raise RuntimeError(f"无法下载{report['title']}：{last_error!r}")


def white_background(image: Image.Image) -> Image.Image:
    rgba = image.convert("RGBA")
    white = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
    white.alpha_composite(rgba)
    return white.convert("RGB")


def build_public_page_pdf(session: requests.Session, report: dict[str, Any], destination: Path) -> tuple[list[str], list[dict[str, Any]]]:
    images: list[Image.Image] = []
    urls: list[str] = []
    records: list[dict[str, Any]] = []
    try:
        for page in range(1, int(report["public_pages_available"]) + 1):
            url = report["image_base"].format(page=page)
            response = session.get(
                url,
                headers={
                    **HEADERS,
                    "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
                    "Referer": report["viewer_url"],
                },
                timeout=120,
                allow_redirects=True,
            )
            rec: dict[str, Any] = {
                "page": page,
                "url": url,
                "status": response.status_code,
                "bytes": len(response.content),
                "content_type": response.headers.get("content-type"),
            }
            if response.status_code != 200 or len(response.content) < 20_000:
                raise RuntimeError(f"公开第{page}页图像不可用：{rec}")
            image = Image.open(BytesIO(response.content))
            image.load()
            if image.width < 700 or image.height < 900:
                raise RuntimeError(f"公开第{page}页图像尺寸异常：{image.size}")
            rec.update({"format": image.format, "width": image.width, "height": image.height, "mode": image.mode})
            print("IMAGE_PAGE", json.dumps(rec, ensure_ascii=False), flush=True)
            images.append(white_background(image))
            urls.append(url)
            records.append(rec)
        destination.parent.mkdir(parents=True, exist_ok=True)
        images[0].save(
            destination,
            "PDF",
            resolution=150.0,
            save_all=True,
            append_images=images[1:],
            quality=95,
            optimize=False,
        )
        print("IMAGE_PDF_CREATED", destination, len(images), destination.stat().st_size, flush=True)
        return urls, records
    finally:
        for image in images:
            try:
                image.close()
            except Exception:
                pass


def validate_pdf(path: Path, min_pages: int, require_identity: bool) -> dict[str, Any]:
    if not path.exists() or path.stat().st_size < 50_000:
        raise RuntimeError(f"PDF不存在或文件过小：{path}")
    with path.open("rb") as stream:
        if stream.read(5) != b"%PDF-":
            raise RuntimeError(f"PDF文件头无效：{path}")
    reader = PdfReader(str(path), strict=False)
    pages = len(reader.pages)
    if pages < min_pages:
        raise RuntimeError(f"{path.name}页数仅{pages}，最低要求{min_pages}")

    qpdf = subprocess.run(["qpdf", "--check", str(path)], capture_output=True, text=True, timeout=180)
    if qpdf.returncode not in (0, 3):
        raise RuntimeError(f"qpdf校验失败：{path.name}: {qpdf.stderr[-1200:]}")

    identity_match = False
    if require_identity:
        text_result = subprocess.run(
            ["pdftotext", "-f", "1", "-l", str(min(pages, 4)), str(path), "-"],
            capture_output=True,
            timeout=120,
        )
        compact = re.sub(r"\s+", "", text_result.stdout.decode("utf-8", errors="ignore"))
        identity_match = COMPANY in compact or STOCK_CODE in compact
        if len(compact) > 300 and not identity_match:
            raise RuntimeError(f"报告文本未识别到{COMPANY}或{STOCK_CODE}：{path.name}")

    first_stem = PREVIEW_DIR / f"{path.stem}_page1"
    subprocess.run(
        ["pdftoppm", "-f", "1", "-singlefile", "-png", "-r", "150", str(path), str(first_stem)],
        check=True,
        capture_output=True,
        timeout=180,
    )
    first_png = first_stem.with_suffix(".png")
    if not first_png.exists() or first_png.stat().st_size < 8_000:
        raise RuntimeError(f"首页渲染失败：{path.name}")

    last_stem = PREVIEW_DIR / f"{path.stem}_page{pages}"
    subprocess.run(
        ["pdftoppm", "-f", str(pages), "-l", str(pages), "-singlefile", "-png", "-r", "120", str(path), str(last_stem)],
        check=True,
        capture_output=True,
        timeout=180,
    )
    last_png = last_stem.with_suffix(".png")
    if not last_png.exists() or last_png.stat().st_size < 6_000:
        raise RuntimeError(f"末页渲染失败：{path.name}")

    validation = {
        "pages": pages,
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
        "qpdf_return_code": qpdf.returncode,
        "identity_text_match": identity_match,
        "first_page_preview": str(first_png),
        "last_page_preview": str(last_png),
    }
    print("PDF_VALIDATED", path.name, json.dumps(validation, ensure_ascii=False), flush=True)
    return validation


def build_package() -> None:
    reset_outputs()
    session = requests.Session()
    session.headers.update(HEADERS)

    records: list[dict[str, Any]] = []

    original_tmp = TMP_DIR / REPORT_2018["filename"]
    source_pdf_url = download_original_pdf(session, REPORT_2018, original_tmp)
    original_validation = validate_pdf(original_tmp, 2, True)
    original_final = REPORT_DIR / REPORT_2018["filename"]
    shutil.move(str(original_tmp), str(original_final))
    records.append(
        {
            **{k: v for k, v in REPORT_2018.items() if k != "pdf_urls"},
            **original_validation,
            "filename": str(original_final.relative_to(ROOT)),
            "source_pdf_url": source_pdf_url,
            "document_type": "券商原始排版PDF",
        }
    )

    image_tmp = TMP_DIR / REPORT_2016["filename"]
    page_urls, page_records = build_public_page_pdf(session, REPORT_2016, image_tmp)
    image_validation = validate_pdf(image_tmp, 2, False)
    image_final = REPORT_DIR / REPORT_2016["filename"]
    shutil.move(str(image_tmp), str(image_final))
    records.append(
        {
            **REPORT_2016,
            **image_validation,
            "filename": str(image_final.relative_to(ROOT)),
            "page_image_urls": page_urls,
            "page_image_records": page_records,
            "document_type": "公开逐页图像重建PDF（仅公开可取得的前2页，原报告共4页，非券商原始PDF容器）",
        }
    )

    records.sort(key=lambda item: int(item["order"]))
    manifest = {
        "company": COMPANY,
        "stock_code": STOCK_CODE,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "report_count": len(records),
        "reports": records,
        "scope_note": (
            "公开渠道中可稳定获取的任子行长篇公司深度全文较少。本包收录1份券商原始排版公司研究PDF，"
            "以及1份根据公开逐页报告图像重建的公司点评PDF。后者原报告共4页，但公开页面仅提供前2页，"
            "已在文件名和清单中明确标注，未将其作为完整原始报告处理。"
        ),
        "validation": "所有PDF均完成文件头、页数、qpdf结构和首末页渲染检查；可提取文本的原始PDF完成公司名称或证券代码匹配。",
    }
    (NOTES_DIR / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (NOTES_DIR / "SHA256SUMS.txt").write_text(
        "\n".join(f"{item['sha256']}  {item['filename']}" for item in records) + "\n",
        encoding="utf-8",
    )

    lines = [
        f"公司：{COMPANY}（{STOCK_CODE}.SZ）",
        "券商研究资料：2份",
        "",
        "1. 新时代证券，2018-08-29，《上半年净利润增速62.65%，网络信息安全业务增速显著》：券商原始排版PDF。",
        "2. 太平洋证券，2016-04-21，《行业景气外延助力，持续高成长可期》：公开逐页图像重建PDF。",
        "   公开来源显示原报告共4页；目前公开逐页图像仅能稳定取得前2页，因此本文件不是完整原始报告，文件名已明确标注。",
        "",
        "公开渠道中任子行长篇公司深度全文较少，本包按可核验、可下载原则收录上述两份公司研究/点评材料，未使用无关行业报告凑数。",
        "",
        "校验：",
        "- PDF文件头、页数和qpdf结构检查；",
        "- 首页与末页渲染检查；",
        "- 原始PDF公司名称/证券代码匹配；",
        "- ZIP CRC完整性测试。",
    ]
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

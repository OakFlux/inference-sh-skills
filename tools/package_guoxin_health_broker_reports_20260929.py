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

COMPANY = "国新健康"
CODE = "000503"
ROOT = Path("国新健康_000503_券商研究报告_3份")
REPORT_DIR = ROOT / "01_券商报告"
NOTES_DIR = ROOT / "02_资料说明"
TMP_DIR = Path("_tmp_guoxin_health_broker_reports")
PREVIEW_DIR = Path("_previews_guoxin_health_broker_reports")
ZIP_PATH = Path("国新健康_000503_券商研究报告_3份.zip")
RESULT_JSON = Path("guoxin_health_broker_reports_result.json")

ORIGINAL_REPORTS = [
    {
        "order": 1,
        "info_code": "AP202410151640312605",
        "institution": "东吴证券",
        "date": "2024-10-15",
        "title": "医保IT国家队，公共数据运营率先落地",
        "authors": "王紫敬",
        "rating": "买入（首次）",
        "filename": "01_东吴证券_2024-10-15_医保IT国家队_公共数据运营率先落地.pdf",
        "min_pages": 15,
        "known_pdf_urls": [
            "https://pdf.dfcfw.com/pdf/H3_AP202410151640312605_1.pdf?1729061505000.pdf=",
            "https://pdf.dfcfw.com/pdf/H3_AP202410151640312605_1.pdf",
        ],
        "classification": "公司深度研究",
    },
    {
        "order": 3,
        "info_code": "AP202410271640525989",
        "institution": "东吴证券",
        "date": "2024-10-27",
        "title": "2024三季报点评：业绩符合预期，医保数据要素业务推进有望加速",
        "authors": "王紫敬",
        "rating": "买入",
        "filename": "03_东吴证券_2024-10-27_2024三季报点评_医保数据要素业务推进有望加速.pdf",
        "min_pages": 3,
        "known_pdf_urls": [
            "https://pdf.dfcfw.com/pdf/H3_AP202410271640525989_1.pdf?1730035231000.pdf=",
            "https://pdf.dfcfw.com/pdf/H3_AP202410271640525989_1.pdf",
        ],
        "classification": "公司跟踪点评（补充材料）",
    },
]

IMAGE_REPORT = {
    "order": 2,
    "institution": "财信证券",
    "date": "2022-09-27",
    "title": "定增助力公司发展，长期盈利修复可期",
    "authors": "邓睿祺",
    "rating": "增持",
    "filename": "02_财信证券_2022-09-27_定增助力公司发展_长期盈利修复可期_公开分页图像重建版.pdf",
    "detail_url": "https://www.fxbaogao.com/detail/3392613",
    "viewer_url": "https://www.fxbaogao.com/view?id=3392613",
    "image_base": "https://public.fxbaogao.com/report-image/2022/09/27/3392613-{page}.png",
    "classification": "公司研究（公开分页图像重建版）",
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36",
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
    page_url = f"https://data.eastmoney.com/report/info/{report['info_code']}.html"
    candidates = list(report["known_pdf_urls"])
    stamp = int(time.time() * 1000)
    candidates.extend(
        [
            f"https://pdf.dfcfw.com/pdf/H3_{report['info_code']}_1.pdf?{stamp}.pdf=",
            f"https://pdf.dfcfw.com/pdf/H3_{report['info_code']}_1.pdf?{report['info_code']}.pdf=",
        ]
    )
    last_error: Exception | None = None
    for url in dict.fromkeys(candidates):
        for attempt in range(1, 4):
            part = destination.with_suffix(".pdf.part")
            try:
                if part.exists():
                    part.unlink()
                headers = {
                    **HEADERS,
                    "Accept": "application/pdf,application/octet-stream;q=0.9,*/*;q=0.8",
                    "Referer": page_url,
                }
                with session.get(url, headers=headers, stream=True, timeout=(45, 240), allow_redirects=True) as response:
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


def download_image_report(session: requests.Session, destination: Path) -> tuple[list[str], list[dict[str, Any]]]:
    image_urls: list[str] = []
    image_records: list[dict[str, Any]] = []
    images: list[Image.Image] = []
    consecutive_misses = 0
    try:
        for page in range(1, 41):
            url = IMAGE_REPORT["image_base"].format(page=page)
            response = session.get(
                url,
                headers={
                    **HEADERS,
                    "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
                    "Referer": IMAGE_REPORT["viewer_url"],
                },
                timeout=120,
                allow_redirects=True,
            )
            record: dict[str, Any] = {
                "page": page,
                "url": url,
                "status": response.status_code,
                "bytes": len(response.content),
                "content_type": response.headers.get("content-type"),
            }
            if response.status_code == 200 and len(response.content) > 10_000:
                image = Image.open(BytesIO(response.content))
                image.load()
                if image.width < 500 or image.height < 700:
                    raise RuntimeError(f"第{page}页图像尺寸异常：{image.size}")
                rgb = image.convert("RGB")
                images.append(rgb)
                image_urls.append(url)
                record.update({"width": image.width, "height": image.height, "format": image.format})
                consecutive_misses = 0
                print("IMAGE_PAGE", json.dumps(record, ensure_ascii=False), flush=True)
            else:
                consecutive_misses += 1
                print("IMAGE_MISS", json.dumps(record, ensure_ascii=False), flush=True)
                if consecutive_misses >= 3:
                    break
            image_records.append(record)
        if len(images) < 2:
            raise RuntimeError(f"仅取得{len(images)}页公开分页图像")
        destination.parent.mkdir(parents=True, exist_ok=True)
        first, rest = images[0], images[1:]
        first.save(
            destination,
            "PDF",
            resolution=150.0,
            save_all=True,
            append_images=rest,
            quality=95,
            optimize=True,
        )
        print("IMAGE_REPORT_CREATED", destination, len(images), destination.stat().st_size, flush=True)
        return image_urls, image_records
    finally:
        for image in images:
            try:
                image.close()
            except Exception:
                pass


def validate_pdf(path: Path, min_pages: int, require_text_identity: bool) -> dict[str, Any]:
    if not path.exists() or path.stat().st_size < 50_000:
        raise RuntimeError(f"PDF不存在或文件过小：{path}")
    with path.open("rb") as stream:
        if stream.read(5) != b"%PDF-":
            raise RuntimeError(f"PDF文件头无效：{path}")
    reader = PdfReader(str(path), strict=False)
    pages = len(reader.pages)
    if pages < min_pages:
        raise RuntimeError(f"{path.name}页数仅{pages}，最低要求{min_pages}")
    text_parts: list[str] = []
    for page in reader.pages[: min(pages, 12)]:
        try:
            text_parts.append(page.extract_text() or "")
        except Exception as exc:
            print("TEXT_WARNING", path.name, repr(exc), flush=True)
    compact_text = re.sub(r"\s+", "", "".join(text_parts))
    identity_match = COMPANY in compact_text or CODE in compact_text
    if require_text_identity and len(compact_text) > 500 and not identity_match:
        raise RuntimeError(f"报告文本未识别到{COMPANY}或{CODE}：{path.name}")
    qpdf = subprocess.run(
        ["qpdf", "--check", str(path)],
        capture_output=True,
        text=True,
        timeout=240,
    )
    if qpdf.returncode not in (0, 3):
        raise RuntimeError(f"qpdf校验失败：{path.name}: {qpdf.stderr[-1000:]}")
    preview_base = PREVIEW_DIR / path.stem
    subprocess.run(
        ["pdftoppm", "-f", "1", "-singlefile", "-png", "-r", "140", str(path), str(preview_base)],
        check=True,
        capture_output=True,
        timeout=240,
    )
    preview = preview_base.with_suffix(".png")
    if not preview.exists() or preview.stat().st_size < 8_000:
        raise RuntimeError(f"首页渲染失败：{path.name}")
    result = {
        "pages": pages,
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
        "qpdf_return_code": qpdf.returncode,
        "identity_text_match": identity_match,
        "first_page_preview": str(preview),
    }
    print("PDF_VALIDATED", path.name, json.dumps(result, ensure_ascii=False), flush=True)
    return result


def build_package() -> None:
    reset_outputs()
    session = requests.Session()
    session.headers.update(HEADERS)
    records: list[dict[str, Any]] = []

    deep_report = ORIGINAL_REPORTS[0]
    deep_tmp = TMP_DIR / deep_report["filename"]
    deep_source = download_original_pdf(session, deep_report, deep_tmp)
    deep_validation = validate_pdf(deep_tmp, int(deep_report["min_pages"]), True)
    deep_final = REPORT_DIR / deep_report["filename"]
    shutil.move(str(deep_tmp), str(deep_final))
    records.append(
        {
            **{k: v for k, v in deep_report.items() if k not in {"known_pdf_urls", "min_pages"}},
            **deep_validation,
            "filename": str(deep_final.relative_to(ROOT)),
            "report_page_url": f"https://data.eastmoney.com/report/info/{deep_report['info_code']}.html",
            "source_pdf_url": deep_source,
            "document_type": "券商原始排版PDF",
        }
    )

    image_tmp = TMP_DIR / IMAGE_REPORT["filename"]
    image_urls, image_records = download_image_report(session, image_tmp)
    image_validation = validate_pdf(image_tmp, 2, False)
    image_final = REPORT_DIR / IMAGE_REPORT["filename"]
    shutil.move(str(image_tmp), str(image_final))
    records.append(
        {
            **IMAGE_REPORT,
            **image_validation,
            "filename": str(image_final.relative_to(ROOT)),
            "page_image_urls": image_urls,
            "page_image_records": image_records,
            "document_type": "公开分页图像重建PDF（非券商原始PDF容器）",
        }
    )

    comment_report = ORIGINAL_REPORTS[1]
    comment_tmp = TMP_DIR / comment_report["filename"]
    comment_source = download_original_pdf(session, comment_report, comment_tmp)
    comment_validation = validate_pdf(comment_tmp, int(comment_report["min_pages"]), True)
    comment_final = REPORT_DIR / comment_report["filename"]
    shutil.move(str(comment_tmp), str(comment_final))
    records.append(
        {
            **{k: v for k, v in comment_report.items() if k not in {"known_pdf_urls", "min_pages"}},
            **comment_validation,
            "filename": str(comment_final.relative_to(ROOT)),
            "report_page_url": f"https://data.eastmoney.com/report/info/{comment_report['info_code']}.html",
            "source_pdf_url": comment_source,
            "document_type": "券商原始排版PDF",
        }
    )

    records.sort(key=lambda item: int(item["order"]))
    manifest = {
        "company": COMPANY,
        "stock_code": CODE,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "report_count": len(records),
        "reports": records,
        "scope_note": "公开可直接获取的国新健康单家公司券商深度全文较少。本包收录1份17页公司深度研究、1份2页公司研究公开分页图像重建版，以及1份3页公司跟踪点评作为补充。",
        "validation": "所有PDF均完成文件头、页数、qpdf结构与首页渲染检查；可提取文本的原始PDF还完成公司名称或证券代码匹配。",
    }
    (NOTES_DIR / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (NOTES_DIR / "SHA256SUMS.txt").write_text(
        "\n".join(f"{item['sha256']}  {item['filename']}" for item in records) + "\n",
        encoding="utf-8",
    )

    lines = [
        f"公司：{COMPANY}（{CODE}.SZ）",
        f"券商研究资料：{len(records)}份",
        "",
        "资料口径说明：",
        "- 第1份为17页公司深度研究，属于本包的核心深度报告。",
        "- 第2份为财信证券公司研究，公开站点仅提供逐页图像；本包按原始公开页序重建为PDF，未将其标作券商原始PDF容器。",
        "- 第3份为3页三季报跟踪点评，作为最新公开补充材料，不等同于长篇深度报告。",
        "",
    ]
    for index, item in enumerate(records, start=1):
        lines.extend(
            [
                f"{index}. {item['institution']}《{item['title']}》",
                f"   日期：{item['date']}；作者：{item['authors']}；评级：{item['rating']}",
                f"   类型：{item['classification']}；页数：{item['pages']}页；文件大小：{item['bytes'] / 1024 / 1024:.2f} MB",
                f"   文档形式：{item['document_type']}",
                f"   文件：{item['filename']}",
                "",
            ]
        )
    lines.extend(
        [
            "校验说明：",
            "- PDF文件头、页数、qpdf结构和首页渲染均已检查。",
            "- 原始PDF的公司身份信息已通过可提取文本核对。",
            "- 详细来源、页图地址及校验值见manifest.json与SHA256SUMS.txt。",
        ]
    )
    (NOTES_DIR / "资料清单与来源说明.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")

    with zipfile.ZipFile(ZIP_PATH, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(ROOT.rglob("*")):
            if path.is_file():
                archive.write(path, path.as_posix())
    with zipfile.ZipFile(ZIP_PATH) as archive:
        bad_member = archive.testzip()
        if bad_member:
            raise RuntimeError(f"ZIP成员损坏：{bad_member}")
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

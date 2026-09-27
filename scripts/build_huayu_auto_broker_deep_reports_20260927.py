from __future__ import annotations

import csv
import hashlib
import json
import re
import subprocess
import time
import zipfile
from pathlib import Path
from typing import Any

import requests
from pypdf import PdfReader

PACKAGE = "华域汽车_600741_券商深度报告_2份"
ROOT = Path(PACKAGE)
REPORT_DIR = ROOT / "01_券商深度报告"
VERIFY_DIR = ROOT / "02_说明与校验"
WORK_DIR = Path("_huayu_auto_broker_work")
RENDER_DIR = WORK_DIR / "renders"
for directory in (REPORT_DIR, VERIFY_DIR, RENDER_DIR):
    directory.mkdir(parents=True, exist_ok=True)

SESSION = requests.Session()
SESSION.trust_env = False
HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/152 Safari/537.36",
    "Accept": "application/pdf,application/octet-stream;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Referer": "https://data.eastmoney.com/",
}

TARGETS: list[dict[str, Any]] = [
    {
        "date": "2021-05-10",
        "title": "行业之锚，拾级而上，穿越牛熊",
        "url": "https://pdf.dfcfw.com/pdf/H3_AP202105101490886205_1.pdf",
        "destination": REPORT_DIR / "2021-05-10_华域汽车_公司深度_行业之锚拾级而上穿越牛熊.pdf",
        "min_pages": 20,
        "expected_terms": ["华域汽车", "行业之锚", "穿越牛熊"],
    },
    {
        "date": "2021-08-18",
        "title": "综合性汽车零部件龙头，电动化、智能化多点布局",
        "url": "https://pdf.dfcfw.com/pdf/H3_AP202108191511040555_1.pdf",
        "destination": REPORT_DIR / "2021-08-18_开源证券_华域汽车首次覆盖_综合性汽车零部件龙头.pdf",
        "min_pages": 20,
        "expected_terms": ["华域汽车", "综合性汽车零部件龙头", "首次覆盖"],
    },
]

BROKER_PATTERNS: list[tuple[str, list[str]]] = [
    ("开源证券", ["开源证券", "kysec.cn"]),
    ("中信证券", ["中信证券", "citics.com"]),
    ("中信建投证券", ["中信建投", "csc.com.cn"]),
    ("华泰证券", ["华泰证券", "htsc.com"]),
    ("广发证券", ["广发证券", "gf.com.cn"]),
    ("招商证券", ["招商证券", "cmschina.com.cn"]),
    ("中国银河证券", ["中国银河证券", "chinastock.com.cn"]),
    ("国泰海通证券", ["国泰海通", "国泰君安", "海通证券"]),
    ("申万宏源证券", ["申万宏源", "swsresearch.com"]),
    ("国金证券", ["国金证券", "gjzq.com.cn"]),
    ("东吴证券", ["东吴证券", "dwzq.com.cn"]),
    ("东方证券", ["东方证券", "orientsec.com.cn"]),
    ("长江证券", ["长江证券", "cjsc.com.cn"]),
    ("天风证券", ["天风证券", "tfzq.com"]),
    ("兴业证券", ["兴业证券", "xyzq.com.cn"]),
    ("安信证券", ["安信证券", "essence.com.cn"]),
    ("东亚前海证券", ["东亚前海证券", "easec.com.cn"]),
    ("西部证券", ["西部证券", "westsecu.com"]),
    ("华西证券", ["华西证券", "hx168.com.cn"]),
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download_pdf(url: str, destination: Path) -> str:
    errors: list[str] = []
    for attempt in range(1, 7):
        temp = destination.with_suffix(destination.suffix + ".part")
        temp.unlink(missing_ok=True)
        try:
            response = SESSION.get(
                url,
                headers=HEADERS,
                timeout=(20, 360),
                stream=True,
                allow_redirects=True,
            )
            print(
                "GET", url, "attempt", attempt, "status", response.status_code,
                "type", response.headers.get("content-type"),
                "length", response.headers.get("content-length"),
                "final", response.url,
                flush=True,
            )
            response.raise_for_status()
            try:
                with temp.open("wb") as fh:
                    for chunk in response.iter_content(1024 * 1024):
                        if chunk:
                            fh.write(chunk)
                final_url = str(response.url)
            finally:
                response.close()

            size = temp.stat().st_size
            head = temp.read_bytes()[:8]
            if size < 200_000 or not head.startswith(b"%PDF-"):
                raise RuntimeError(f"invalid PDF bytes={size}, head={head!r}")
            temp.replace(destination)
            return final_url
        except Exception as exc:  # noqa: BLE001
            temp.unlink(missing_ok=True)
            errors.append(f"attempt {attempt}: {exc!r}")
            time.sleep(min(2 * attempt, 10))
    raise RuntimeError(f"download failed for {url}: {errors}")


def render_page(path: Path, page_number: int, label: str) -> None:
    prefix = RENDER_DIR / f"{path.stem}_{label}"
    process = subprocess.run(
        [
            "pdftoppm", "-f", str(page_number), "-l", str(page_number),
            "-r", "100", "-png", "-singlefile", str(path), str(prefix),
        ],
        capture_output=True,
        text=True,
        timeout=240,
    )
    png = Path(str(prefix) + ".png")
    if (
        process.returncode != 0
        or not png.exists()
        or png.stat().st_size < 1000
        or png.read_bytes()[:8] != b"\x89PNG\r\n\x1a\n"
    ):
        raise RuntimeError(
            f"render failed for {path.name}, page {page_number}: {process.stderr[-1200:]}"
        )
    png.unlink()


def identify_broker(text: str) -> str:
    compact = re.sub(r"\s+", "", text).lower()
    for broker, patterns in BROKER_PATTERNS:
        if any(pattern.lower().replace(" ", "") in compact for pattern in patterns):
            return broker
    return "未从可提取文本中可靠识别"


def validate_pdf(target: dict[str, Any]) -> dict[str, Any]:
    path: Path = target["destination"]
    qpdf = subprocess.run(
        ["qpdf", "--check", str(path)],
        capture_output=True,
        text=True,
        timeout=240,
    )
    if qpdf.returncode not in (0, 3):
        raise RuntimeError(f"qpdf failed for {path.name}: {qpdf.stderr[-2000:]}")

    reader = PdfReader(str(path), strict=False)
    page_count = len(reader.pages)
    if page_count < int(target["min_pages"]):
        raise RuntimeError(
            f"report too short for a deep report: {path.name}, pages={page_count}"
        )

    render_page(path, 1, "first")
    render_page(path, page_count, "last")

    sample_indices = list(range(min(6, page_count)))
    sample_text = "\n".join((reader.pages[index].extract_text() or "") for index in sample_indices)
    compact = re.sub(r"\s+", "", sample_text)
    missing = [term for term in target["expected_terms"] if re.sub(r"\s+", "", term) not in compact]
    if sample_text.strip() and missing:
        raise RuntimeError(f"identity/title terms missing from {path.name}: {missing}")

    broker = identify_broker(sample_text)
    print("FIRST_PAGES_TEXT_BEGIN", path.name, flush=True)
    print(sample_text[:5000], flush=True)
    print("FIRST_PAGES_TEXT_END", path.name, flush=True)

    return {
        "pages": page_count,
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
        "broker": broker,
        "qpdf_return_code": qpdf.returncode,
        "first_and_last_page_rendered": True,
        "sample_text_extractable": bool(sample_text.strip()),
    }


records: list[dict[str, Any]] = []
seen_hashes: set[str] = set()
for target in TARGETS:
    final_url = download_pdf(target["url"], target["destination"])
    metadata = validate_pdf(target)
    if metadata["sha256"] in seen_hashes:
        raise RuntimeError(f"duplicate report: {target['destination'].name}")
    seen_hashes.add(metadata["sha256"])
    record = {
        "report_date": target["date"],
        "title": target["title"],
        "relative_path": str(target["destination"].relative_to(ROOT)),
        "source": "东方财富公开研报PDF镜像",
        "source_url": final_url,
        **metadata,
    }
    records.append(record)
    print("VALIDATED", json.dumps(record, ensure_ascii=False), flush=True)

manifest = {
    "package_name": PACKAGE,
    "company": "华域汽车系统股份有限公司",
    "stock_code": "600741.SH",
    "checked_as_of": "2026-09-27",
    "selection_rule": "选取可公开直接下载、篇幅达到公司深度/首次覆盖标准的完整券商PDF；排除短篇业绩点评和网页摘要。",
    "report_count": len(records),
    "records": records,
}
(ROOT / "manifest.json").write_text(
    json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
)

with (VERIFY_DIR / "文件清单.csv").open("w", newline="", encoding="utf-8-sig") as fh:
    writer = csv.writer(fh)
    writer.writerow(["文件", "日期", "券商", "标题", "页数", "文件大小", "SHA-256", "来源网址"])
    for record in records:
        writer.writerow([
            record["relative_path"], record["report_date"], record["broker"],
            record["title"], record["pages"], record["bytes"],
            record["sha256"], record["source_url"],
        ])

with (VERIFY_DIR / "SHA256SUMS.txt").open("w", encoding="utf-8") as fh:
    for record in records:
        fh.write(f"{record['sha256']}  {record['relative_path']}\n")

readme_lines = [
    "华域汽车（600741.SH）券商深度报告文件包",
    "",
    "核对日期：2026年9月27日",
    "",
    "收录标准：",
    "- 公开可直接下载的完整PDF；",
    "- 公司深度研究或首次覆盖报告；",
    "- 排除短篇年报/季报点评和网页摘要。",
    "",
    "收录报告：",
]
for index, record in enumerate(records, start=1):
    readme_lines.extend([
        f"{index}. {record['report_date']} | {record['broker']}",
        f"   标题：{record['title']}",
        f"   页数：{record['pages']}页",
        f"   文件：{record['relative_path']}",
    ])
readme_lines.extend([
    "",
    "校验说明：",
    "- 每份PDF均检查文件头和最低文件大小；",
    "- 使用qpdf执行结构检查；",
    "- 使用PDF解析器核验公司名称、标题关键词和页数；",
    "- 每份PDF的第一页和最后一页均实际渲染为PNG验证可读性；",
    "- 使用SHA-256校验并执行文件去重；",
    "- 详细来源和哈希值见《文件清单.csv》、SHA256SUMS.txt及manifest.json。",
])
(VERIFY_DIR / "README.txt").write_text("\n".join(readme_lines) + "\n", encoding="utf-8")

zip_path = Path(PACKAGE + ".zip")
zip_path.unlink(missing_ok=True)
with zipfile.ZipFile(
    zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True
) as archive:
    for path in sorted(ROOT.rglob("*")):
        if path.is_file():
            archive.write(path, path.as_posix())

with zipfile.ZipFile(zip_path, "r") as archive:
    bad_member = archive.testzip()
    if bad_member:
        raise RuntimeError(f"ZIP integrity test failed at {bad_member}")
    pdf_count = sum(name.lower().endswith(".pdf") for name in archive.namelist())
    if pdf_count != len(records):
        raise RuntimeError(f"ZIP PDF count mismatch: {pdf_count} != {len(records)}")

print(
    "FINAL_ZIP", zip_path, "bytes", zip_path.stat().st_size,
    "sha256", sha256(zip_path), flush=True,
)

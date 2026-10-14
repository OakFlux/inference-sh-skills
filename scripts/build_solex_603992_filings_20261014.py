from __future__ import annotations

import csv
import hashlib
import json
import shutil
import subprocess
import time
import zipfile
from pathlib import Path
from typing import Any

import requests
from pypdf import PdfReader

CHECKED_AS_OF = "2026-10-14"
COMPANY = "厦门松霖科技股份有限公司"
SHORT = "松霖科技"
CODE = "603992"
PACKAGE = "松霖科技_603992_2020-2025年报_2026最新季报及半年报"
ROOT = Path(PACKAGE)
ANNUAL = ROOT / "01_年度报告"
QUARTER = ROOT / "02_最新季度报告"
HALF = ROOT / "03_补充半年度报告"
VERIFY = ROOT / "04_说明与校验"
RENDER = Path("_solex_renders")
for d in (ANNUAL, QUARTER, HALF, VERIFY, RENDER):
    d.mkdir(parents=True, exist_ok=True)

REPORTS: list[dict[str, Any]] = [
    {"name":"松霖科技_603992_2020年年度报告.pdf","dir":ANNUAL,"kind":"年度报告","year":2020,"date":"2021-04-13","urls":[
        "https://file.finance.sina.com.cn/211.154.219.97%3A9494/MRGG/CNSESH_STOCK/2021/2021-4/2021-04-13/7034159.PDF",
        "http://211.154.219.97:9494/MRGG/CNSESH_STOCK/2021/2021-4/2021-04-13/7034159.PDF"]},
    {"name":"松霖科技_603992_2021年年度报告.pdf","dir":ANNUAL,"kind":"年度报告","year":2021,"date":"2022-04-26","urls":[
        "https://file.finance.sina.com.cn/211.154.219.97%3A9494/MRGG/CNSESH_STOCK/2022/2022-4/2022-04-26/8077356.PDF",
        "http://211.154.219.97:9494/MRGG/CNSESH_STOCK/2022/2022-4/2022-04-26/8077356.PDF"]},
    {"name":"松霖科技_603992_2022年年度报告.pdf","dir":ANNUAL,"kind":"年度报告","year":2022,"date":"2023-04-25","urls":[
        "https://file.finance.sina.com.cn/211.154.219.97%3A9494/MRGG/CNSESH_STOCK/2023/2023-4/2023-04-25/9061421.PDF",
        "http://211.154.219.97:9494/MRGG/CNSESH_STOCK/2023/2023-4/2023-04-25/9061421.PDF"]},
    {"name":"松霖科技_603992_2023年年度报告.pdf","dir":ANNUAL,"kind":"年度报告","year":2023,"date":"2024-04-30","urls":[
        "https://file.finance.sina.com.cn/211.154.219.97%3A9494/MRGG/CNSESH_STOCK/2024/2024-4/2024-04-30/10153803.PDF",
        "http://211.154.219.97:9494/MRGG/CNSESH_STOCK/2024/2024-4/2024-04-30/10153803.PDF"]},
    {"name":"松霖科技_603992_2024年年度报告.pdf","dir":ANNUAL,"kind":"年度报告","year":2024,"date":"2025-03-31","urls":[
        "https://static.cninfo.com.cn/finalpage/2025-03-31/1222962236.PDF",
        "http://static.cninfo.com.cn/finalpage/2025-03-31/1222962236.PDF"]},
    {"name":"松霖科技_603992_2025年年度报告.pdf","dir":ANNUAL,"kind":"年度报告","year":2025,"date":"2026-03-31","urls":[
        "https://static.cninfo.com.cn/finalpage/2026-03-31/1225064312.PDF",
        "http://static.cninfo.com.cn/finalpage/2026-03-31/1225064312.PDF"]},
    {"name":"松霖科技_603992_2026年第一季度报告.pdf","dir":QUARTER,"kind":"季度报告","year":2026,"quarter":1,"date":"2026-04-24","urls":[
        "https://static.cninfo.com.cn/finalpage/2026-04-24/1225171575.PDF",
        "http://static.cninfo.com.cn/finalpage/2026-04-24/1225171575.PDF"]},
    {"name":"松霖科技_603992_2026年半年度报告.pdf","dir":HALF,"kind":"半年度报告","year":2026,"date":"2026-08-27","urls":[
        "https://static.cninfo.com.cn/finalpage/2026-08-27/1225513902.PDF",
        "http://static.cninfo.com.cn/finalpage/2026-08-27/1225513902.PDF"]},
]

S = requests.Session()
S.trust_env = False
HEADERS = {
    "User-Agent":"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/152 Safari/537.36",
    "Accept":"application/pdf,application/octet-stream;q=0.9,*/*;q=0.5",
    "Referer":"https://www.sse.com.cn/",
}


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda: f.read(1024 * 1024), b""):
            h.update(b)
    return h.hexdigest()


def download(report: dict[str, Any], dest: Path) -> str:
    errors: list[str] = []
    for url in report["urls"]:
        for attempt in range(1, 5):
            tmp = dest.with_suffix(".pdf.part")
            tmp.unlink(missing_ok=True)
            try:
                with S.get(url, headers=HEADERS, stream=True, timeout=(25, 420), allow_redirects=True) as r:
                    print("GET", attempt, r.status_code, r.headers.get("content-type"), r.url, flush=True)
                    r.raise_for_status()
                    with tmp.open("wb") as f:
                        for chunk in r.iter_content(1024 * 1024):
                            if chunk:
                                f.write(chunk)
                    final_url = str(r.url)
                size = tmp.stat().st_size
                head = tmp.read_bytes()[:8]
                if size < 20_000 or not head.startswith(b"%PDF-"):
                    raise RuntimeError(f"invalid payload size={size} head={head!r}")
                tmp.replace(dest)
                return final_url
            except Exception as exc:  # noqa: BLE001
                tmp.unlink(missing_ok=True)
                errors.append(f"{url} attempt {attempt}: {exc!r}")
                time.sleep(min(2 * attempt, 8))
    raise RuntimeError("download failed: " + " | ".join(errors[-8:]))


def sample_text(reader: PdfReader) -> str:
    n = len(reader.pages)
    idx = sorted({0, min(1,n-1), min(2,n-1), n//2, n-1})
    parts: list[str] = []
    for i in idx:
        try:
            parts.append(reader.pages[i].extract_text() or "")
        except Exception as exc:  # noqa: BLE001
            print("TEXT_WARNING", i + 1, repr(exc), flush=True)
    return "".join(parts).replace(" ", "").replace("\n", "")


def render(path: Path, page: int) -> str:
    out = RENDER / f"{path.stem}_p{page}"
    p = subprocess.run(["pdftoppm","-f",str(page),"-l",str(page),"-r","105","-png","-singlefile",str(path),str(out)],capture_output=True,text=True,timeout=300)
    png = Path(str(out) + ".png")
    if p.returncode or not png.exists() or png.stat().st_size < 3000:
        raise RuntimeError(f"render failed {path.name} page {page}: {p.stderr[-1200:]}")
    return str(png)


def validate(report: dict[str, Any], path: Path) -> dict[str, Any]:
    q = subprocess.run(["qpdf","--check",str(path)],capture_output=True,text=True,timeout=300)
    if q.returncode not in (0,3):
        raise RuntimeError(f"qpdf failed {path.name}: {q.stderr[-1600:]}")
    reader = PdfReader(str(path), strict=False)
    pages = len(reader.pages)
    if pages < (8 if report["kind"] == "年度报告" else 5):
        raise RuntimeError(f"too few pages {path.name}: {pages}")
    text = sample_text(reader)
    if text and not (COMPANY in text or SHORT in text or CODE in text):
        raise RuntimeError(f"company check failed {path.name}")
    marker = f"{report['year']}年年度报告" if report["kind"] == "年度报告" else ("第一季度报告" if report["kind"] == "季度报告" else "半年度报告")
    if text and marker not in text:
        raise RuntimeError(f"period marker failed {path.name}: {marker}")
    rp = sorted({1, max(1,(pages+1)//2), pages})
    renders = [render(path, p) for p in rp]
    return {"pages":pages,"bytes":path.stat().st_size,"sha256":digest(path),"qpdf_return_code":q.returncode,"rendered_pages":rp,"render_files":renders}


def main() -> None:
    records: list[dict[str, Any]] = []
    for report in REPORTS:
        dest = report["dir"] / report["name"]
        resolved = download(report, dest)
        check = validate(report, dest)
        records.append({
            "file":str(dest),"kind":report["kind"],"year":report["year"],"quarter":report.get("quarter"),
            "disclosure_date":report["date"],"source_candidates":report["urls"],"resolved_url":resolved,**check,
        })
    if sorted(r["year"] for r in records if r["kind"] == "年度报告") != list(range(2020,2026)):
        raise RuntimeError("annual coverage mismatch")
    if len({r["sha256"] for r in records}) != len(records):
        raise RuntimeError("duplicate PDF content detected")

    manifest = {"company":COMPANY,"stock_code":CODE,"checked_as_of":CHECKED_AS_OF,"reports":records}
    (VERIFY/"manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding="utf-8")
    with (VERIFY/"文件清单.csv").open("w",encoding="utf-8-sig",newline="") as f:
        fields=["file","kind","year","quarter","disclosure_date","pages","bytes","sha256","resolved_url"]
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader()
        for r in records: w.writerow({k:r.get(k) for k in fields})
    with (VERIFY/"SHA256SUMS.txt").open("w",encoding="utf-8") as f:
        for r in records:
            f.write(f"{r['sha256']}  {Path(r['file']).relative_to(ROOT).as_posix()}\n")
    (ROOT/"README_文件说明.txt").write_text(
        f"{COMPANY}（{CODE}）定期报告合集\n核对日期：{CHECKED_AS_OF}\n\n"
        "包含2020-2025年6份年度报告全文、2026年第一季度报告；另补充2026年半年度报告。\n"
        "半年度报告是更近的定期报告，但不标作季报。已排除年度报告摘要等非全文文件。\n"
        "每份PDF均检查文件结构、页数、公司及报告期标识，并渲染首页/中间页/末页。\n"
        "页数、字节数、来源及SHA-256见04_说明与校验目录。原报告内容未改写。\n",
        encoding="utf-8",
    )
    zpath=Path(PACKAGE+".zip"); zpath.unlink(missing_ok=True)
    with zipfile.ZipFile(zpath,"w",zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for p in sorted(ROOT.rglob("*")):
            if p.is_file(): z.write(p,p.as_posix())
    with zipfile.ZipFile(zpath) as z:
        bad=z.testzip(); names=z.namelist()
        if bad: raise RuntimeError(f"bad zip member {bad}")
    if len([n for n in names if n.lower().endswith(".pdf")]) != len(REPORTS):
        raise RuntimeError("ZIP PDF count mismatch")
    print("FINAL",zpath,zpath.stat().st_size,digest(zpath),flush=True)


if __name__ == "__main__":
    try:
        main()
    finally:
        shutil.rmtree(RENDER,ignore_errors=True)

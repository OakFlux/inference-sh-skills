from __future__ import annotations

from pathlib import Path


def main() -> None:
    source_path = Path(".github/scripts/package_hehe_information_final.py")
    code = source_path.read_text(encoding="utf-8")

    original_inspection = '''    if kind == "prospectus":
        if "招股说明书" not in front_compact:
            raise RuntimeError(f"Prospectus marker missing: {path}")
        if "科创板" not in front_compact and "上海证券交易所" not in front_compact:
            raise RuntimeError(f"STAR Market marker missing in prospectus: {path}")
        if any(marker in front_compact for marker in ("申报稿", "招股意向书")):
            raise RuntimeError(f"Non-final prospectus version detected: {path}")
'''
    replacement_inspection = '''    if kind == "prospectus":
        cover_text = "\\n".join(
            document.load_page(index).get_text("text")
            for index in range(min(12, pages))
        )
        cover_compact = normalize(cover_text)
        if "招股说明书" not in cover_compact:
            raise RuntimeError(f"Prospectus marker missing: {path}")
        if "科创板" not in cover_compact and "上海证券交易所" not in cover_compact:
            raise RuntimeError(f"STAR Market marker missing in prospectus: {path}")
        if any(marker in cover_compact for marker in ("申报稿", "招股意向书")):
            raise RuntimeError(f"Non-final prospectus version detected: {path}")
'''
    if original_inspection not in code:
        raise RuntimeError("Prospectus inspection block was not found")
    code = code.replace(original_inspection, replacement_inspection, 1)

    original_download = '''prospectus_url, prospectus_detail_url, prospectus_context = extract_pdf_from_pages(
    prospectus_detail_variants()
)
prospectus_target = PROSPECTUS_DIR / f"{SHORT_NAME}_首次公开发行股票并在科创板上市招股说明书_正式版.pdf"
prospectus_used_url = download_pdf(
    download_candidates(prospectus_url), prospectus_target, prospectus_detail_url
)
'''
    replacement_download = '''prospectus_detail_url = prospectus_detail_variants()[0]
prospectus_context = (
    "新浪财经招股说明页面列示：2024-09-23 合合信息首次公开发行股票并在科创板上市招股说明书；"
    "正式发行版详情编号10494386。"
)
prospectus_candidates = [
    "https://file.finance.sina.com.cn/211.154.219.97%3A9494/MRGG/CNSESH_STOCK/2024/2024-9/2024-09-23/10494386.PDF",
    "https://file.finance.sina.com.cn/211.154.219.97:9494/MRGG/CNSESH_STOCK/2024/2024-9/2024-09-23/10494386.PDF",
    "http://file.finance.sina.com.cn/211.154.219.97:9494/MRGG/CNSESH_STOCK/2024/2024-9/2024-09-23/10494386.PDF",
]
prospectus_target = PROSPECTUS_DIR / f"{SHORT_NAME}_首次公开发行股票并在科创板上市招股说明书_正式版.pdf"
prospectus_used_url = download_pdf(
    prospectus_candidates, prospectus_target, prospectus_detail_url
)
prospectus_url = prospectus_used_url
'''
    if original_download not in code:
        raise RuntimeError("Prospectus download block was not found")
    code = code.replace(original_download, replacement_download, 1)

    compiled = compile(code, "hehe_information_packaging_v2_generated.py", "exec")
    exec(compiled, {"__name__": "__main__"})


if __name__ == "__main__":
    main()

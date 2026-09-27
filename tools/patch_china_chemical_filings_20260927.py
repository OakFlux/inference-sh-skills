from pathlib import Path

path = Path("tools/package_china_chemical_filings_20260927.py")
text = path.read_text(encoding="utf-8")

replacements = {
    "https://static.sse.com.cn/disclosure/listedinfo/announcement/c/new/2021-04-29/601117_20210429_11.pdf": "https://file.finance.sina.com.cn/211.154.219.97%3A9494/MRGG/CNSESH_STOCK/2021/2021-4/2021-04-29/7179635.PDF",
    "https://static.sse.com.cn/disclosure/listedinfo/announcement/c/new/2022-04-28/601117_20220428_2_ay38JzKR.pdf": "https://file.finance.sina.com.cn/211.154.219.97%3A9494/MRGG/CNSESH_STOCK/2022/2022-4/2022-04-28/8117633.PDF",
    "https://static.sse.com.cn/disclosure/listedinfo/announcement/c/new/2023-03-28/601117_20230328_HU01.pdf": "https://file.finance.sina.com.cn/211.154.219.97%3A9494/MRGG/CNSESH_STOCK/2023/2023-3/2023-03-28/8914979.PDF",
    "https://static.sse.com.cn/disclosure/listedinfo/announcement/c/new/2024-04-29/601117_20240429_DE4Z.pdf": "https://file.finance.sina.com.cn/211.154.219.97%3A9494/MRGG/CNSESH_STOCK/2024/2024-4/2024-04-29/10136607.PDF",
    "https://static.sse.com.cn/disclosure/listedinfo/announcement/c/new/2025-04-30/601117_20250430_PYFX.pdf": "https://file.finance.sina.com.cn/211.154.219.97%3A9494/MRGG/CNSESH_STOCK/2025/2025-4/2025-04-30/11075395.PDF",
    "https://static.sse.com.cn/disclosure/listedinfo/announcement/c/new/2026-03-25/601117_20260325_POJ5.pdf": "https://file.finance.sina.com.cn/211.154.219.97%3A9494/MRGG/CNSESH_STOCK/2026/2026-3/2026-03-25/12015316.PDF",
    "https://static.sse.com.cn/disclosure/listedinfo/announcement/c/new/2026-04-28/601117_20260428_Z4MB.pdf": "https://file.finance.sina.com.cn/211.154.219.97%3A9494/MRGG/CNSESH_STOCK/2026/2026-4/2026-04-28/12213805.PDF",
    "https://static.sse.com.cn/disclosure/listedinfo/announcement/c/new/2026-08-31/601117_20260831_CG6A.pdf": "https://file.finance.sina.com.cn/211.154.219.97%3A9494/MRGG/CNSESH_STOCK/2026/2026-8/2026-08-31/12574782.PDF",
    '"Referer": "https://www.sse.com.cn/",': '"Referer": "https://vip.stock.finance.sina.com.cn/",',
    '"source": "上海证券交易所公告PDF（static.sse.com.cn）",': '"source": "新浪财经公告PDF镜像（原始披露文件为上海证券交易所公告）",',
    '"来源：上海证券交易所公告PDF",': '"来源：新浪财经公告PDF镜像（原始披露文件为上海证券交易所公告）",',
}

for old, new in replacements.items():
    if old not in text:
        raise SystemExit(f"Patch anchor not found: {old}")
    text = text.replace(old, new, 1)

path.write_text(text, encoding="utf-8")
print("Patched", path)

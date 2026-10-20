from __future__ import annotations

import html
import json
import re
from pathlib import Path
from urllib.parse import urljoin

import requests

OUT = Path("source_probe")
OUT.mkdir(exist_ok=True)

URLS = {
    "sgpjbg_henghe_topic": "https://www.sgpjbg.com/zhuanti/henghejingmibaogao.html",
    "sgpjbg_structure_topic": "https://www.sgpjbg.com/zhuanti/xinnengyuanjiegoujianbaogao.html",
    "hibor_2025": "https://www.hibor.com.cn/repinfodetail_4445932.html",
    "nxny_2026": "https://www.nxny.com/report/view_6290105.html",
    "ninef_2023": "https://www.9fzt.com/detail/sz_300539_10_740567795901.html",
    "cfi_reports": "https://gg.cfi.cn/ybyl/20364/300539.html",
}

session = requests.Session()
session.headers.update(
    {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
)

summary = {}
for name, url in URLS.items():
    try:
        response = session.get(url, timeout=(20, 120), allow_redirects=True)
        text = response.text
        response.close()
        (OUT / f"{name}.html").write_text(text, encoding="utf-8", errors="replace")
        decoded = html.unescape(text)
        urls = []
        for raw in re.findall(r"(?i)(?:href|src|data-src|data-url|url)\s*=\s*['\"]([^'\"]+)['\"]", decoded):
            absolute = urljoin(response.url, raw)
            if absolute not in urls:
                urls.append(absolute)
        interesting = [
            item
            for item in urls
            if re.search(r"(?i)(pdf|download|down|report|baogao|preview|image|img|file|attachment|view|api)", item)
        ]
        context = []
        for pattern in (
            "横河精密",
            "优质精密制造",
            "25H1业绩显著增长",
            "全球无人机新秀崛起",
            "4445932",
            "6290105",
            "740567795901",
        ):
            for match in re.finditer(re.escape(pattern), decoded, flags=re.I):
                start = max(0, match.start() - 1000)
                end = min(len(decoded), match.end() + 1800)
                snippet = decoded[start:end]
                if snippet not in context:
                    context.append(snippet)
        (OUT / f"{name}_interesting_urls.txt").write_text("\n".join(interesting), encoding="utf-8")
        (OUT / f"{name}_context.txt").write_text("\n\n--- CONTEXT ---\n\n".join(context), encoding="utf-8")
        summary[name] = {
            "request_url": url,
            "final_url": response.url,
            "status": response.status_code,
            "content_type": response.headers.get("content-type"),
            "bytes": len(response.content),
            "title": (re.search(r"(?is)<title[^>]*>(.*?)</title>", decoded).group(1).strip() if re.search(r"(?is)<title[^>]*>(.*?)</title>", decoded) else ""),
            "url_count": len(urls),
            "interesting_urls": interesting[:300],
            "context_count": len(context),
        }
    except Exception as exc:  # noqa: BLE001
        summary[name] = {"request_url": url, "error": repr(exc)}

(OUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(summary, ensure_ascii=False, indent=2))

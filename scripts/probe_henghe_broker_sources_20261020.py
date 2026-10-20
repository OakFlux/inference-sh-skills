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
    "sgpjbg_henghe_topic_com": "https://www.sgpjbg.com/zhuanti/henghejingmibaogao.html",
    "sgpjbg_henghe_topic_cn": "https://www.sgpjbg.com.cn/zhuanti/henghejingmibaogao.html",
    "sgpjbg_structure_topic_cn": "https://www.sgpjbg.com.cn/zhuanti/xinnengyuanjiegoujianbaogao.html",
    "hibor_2025": "https://www.hibor.com.cn/repinfodetail_4445932.html",
    "hibor_fxgroup_2025": "https://fxgroup.hibor.com.cn/repinfodetail_4445932.html",
    "microbell_2025": "https://www.microbell.com/repinfodetail_4445932.html",
    "nxny_2026": "https://www.nxny.com/report/view_6290105.html",
    "ninef_2023": "https://www.9fzt.com/detail/sz_300539_10_740567795901.html",
    "ninef_article_2023": "https://www.9fzt.com/others/report.html?pushChannel=9fztgw&contentType=article&page=view_the_article&contentId=740567795901",
    "ninef_detail_js": "https://www.9fzt.com/js/detailArticle.js",
    "cfi_reports": "https://gg.cfi.cn/ybyl/20364/300539.html",
    "cfi_2026_text": "https://gg.cfi.cn/ybdata.aspx?id=20260511000239",
    "cfi_2026_image": "https://gg.cfi.cn/bigimage.aspx?stockid=20364&date=20260511",
}

session = requests.Session()
session.headers.update(
    {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
)

summary = {}
for name, url in URLS.items():
    try:
        response = session.get(url, timeout=(20, 120), allow_redirects=True)
        raw = response.content
        content_type = response.headers.get("content-type", "")
        encoding = response.encoding or response.apparent_encoding or "utf-8"
        try:
            text = raw.decode(encoding, errors="replace")
        except LookupError:
            text = raw.decode("utf-8", errors="replace")
        final_url = response.url
        status = response.status_code
        headers = dict(response.headers)
        response.close()
        suffix = ".js" if "javascript" in content_type or name.endswith("_js") else ".html"
        (OUT / f"{name}{suffix}").write_text(text, encoding="utf-8", errors="replace")
        decoded = html.unescape(text)
        urls = []
        for raw_url in re.findall(r"(?i)(?:href|src|data-src|data-url|url)\s*=\s*['\"]([^'\"]+)['\"]", decoded):
            absolute = urljoin(final_url, raw_url)
            if absolute not in urls:
                urls.append(absolute)
        for raw_url in re.findall(r"https?://[^\s'\"<>]+", decoded):
            absolute = raw_url.rstrip(")]}>,;\\")
            if absolute not in urls:
                urls.append(absolute)
        interesting = [
            item for item in urls
            if re.search(r"(?i)(pdf|download|down|report|baogao|preview|image|img|file|attachment|view|api|article|content)", item)
        ]
        context = []
        for pattern in (
            "横河精密", "优质精密制造", "25H1业绩显著增长", "全球无人机新秀崛起",
            "4445932", "6290105", "740567795901", "pdf", "download", "contentId", "fileUrl",
        ):
            for match in re.finditer(re.escape(pattern), decoded, flags=re.I):
                start = max(0, match.start() - 1200)
                end = min(len(decoded), match.end() + 2400)
                snippet = decoded[start:end]
                if snippet not in context:
                    context.append(snippet)
        (OUT / f"{name}_interesting_urls.txt").write_text("\n".join(interesting), encoding="utf-8")
        (OUT / f"{name}_context.txt").write_text("\n\n--- CONTEXT ---\n\n".join(context), encoding="utf-8")
        summary[name] = {
            "request_url": url,
            "final_url": final_url,
            "status": status,
            "content_type": content_type,
            "headers": headers,
            "bytes": len(raw),
            "encoding": encoding,
            "title": (re.search(r"(?is)<title[^>]*>(.*?)</title>", decoded).group(1).strip() if re.search(r"(?is)<title[^>]*>(.*?)</title>", decoded) else ""),
            "url_count": len(urls),
            "interesting_urls": interesting[:500],
            "context_count": len(context),
        }
    except Exception as exc:  # noqa: BLE001
        summary[name] = {"request_url": url, "error": repr(exc)}

(OUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(summary, ensure_ascii=False, indent=2))

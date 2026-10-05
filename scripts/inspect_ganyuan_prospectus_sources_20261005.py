from __future__ import annotations

import html
import json
import re
from urllib.parse import urljoin

import requests

SESSION = requests.Session()
SESSION.trust_env = False
HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/152 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

URLS = [
    "https://vip.stock.finance.sina.com.cn/corp/go.php/vISSUE_RaiseExplanation/stockid/002991.phtml",
    "https://money.finance.sina.com.cn/corp/go.php/vISSUE_RaiseExplanation/stockid/002991.phtml",
    "https://www.fxbaogao.com/detail/2098902",
    "https://ipo.qianzhan.com/zjh/Detail-f4462f0a3d0658b50cc6c7c5e14cc654.html",
]


def fetch(url: str) -> tuple[requests.Response, str]:
    r = SESSION.get(url, headers=HEADERS, timeout=60, allow_redirects=True)
    encoding = r.apparent_encoding or r.encoding or "utf-8"
    try:
        text = r.content.decode(encoding, errors="replace")
    except LookupError:
        text = r.content.decode("utf-8", errors="replace")
    return r, text


for url in URLS:
    print("\n===URL===", url, flush=True)
    try:
        r, text = fetch(url)
        print("STATUS", r.status_code, r.url, r.headers.get("content-type"), len(r.content), flush=True)
        m = re.search(r"<title[^>]*>(.*?)</title>", text, re.I | re.S)
        if m:
            print("TITLE", re.sub(r"<[^>]+>", "", m.group(1)).strip(), flush=True)
        links = []
        for match in re.finditer(r'''(?:href|src)\s*=\s*["']([^"']+)["']''', text, re.I):
            raw = html.unescape(match.group(1))
            full = urljoin(r.url, raw)
            low = full.lower()
            if any(key in low for key in ("pdf", "download", "issue", "raise", "attach", "file", "2098902", "002991")):
                links.append(full)
        unique = list(dict.fromkeys(links))
        print("LINKS", json.dumps(unique[:300], ensure_ascii=False, indent=2), flush=True)
        for pattern in (
            "首次公开发行股票招股说明书",
            "2020-07-21",
            "2020年07月21日",
            ".pdf",
            "download",
            "附件",
        ):
            positions = [m.start() for m in re.finditer(re.escape(pattern), text, re.I)]
            for pos in positions[:5]:
                snippet = re.sub(r"\s+", " ", text[max(0, pos - 800): pos + 2200])
                print("AROUND", pattern, snippet, flush=True)
        # Follow likely detail pages, but avoid broad nav links.
        follow = [
            link for link in unique
            if any(token in link for token in ("RaiseExplanationDetail", "vISSUE", "detail/2098902"))
        ][:20]
        for detail in follow:
            print("\n---FOLLOW---", detail, flush=True)
            try:
                rr, tt = fetch(detail)
                print("FOLLOW_STATUS", rr.status_code, rr.url, rr.headers.get("content-type"), len(rr.content), flush=True)
                found = []
                for mm in re.finditer(r'''(?:href|src)\s*=\s*["']([^"']+)["']''', tt, re.I):
                    raw = html.unescape(mm.group(1))
                    full = urljoin(rr.url, raw)
                    if any(k in full.lower() for k in ("pdf", "download", "attach", "file")):
                        found.append(full)
                print("FOLLOW_LINKS", json.dumps(list(dict.fromkeys(found))[:200], ensure_ascii=False, indent=2), flush=True)
                for pat in (".pdf", "招股说明书", "下载", "附件"):
                    pp = tt.lower().find(pat.lower())
                    if pp >= 0:
                        print("FOLLOW_AROUND", pat, re.sub(r"\s+", " ", tt[max(0, pp-800):pp+2200]), flush=True)
            except Exception as exc:
                print("FOLLOW_ERROR", repr(exc), flush=True)
    except Exception as exc:
        print("ERROR", repr(exc), flush=True)

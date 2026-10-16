from __future__ import annotations

import re
import requests

session = requests.Session()
session.trust_env = False
headers = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/152 Safari/537.36",
    "Accept": "*/*",
    "Referer": "https://stock.finance.sina.com.cn/",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

rptids = [
    ("银河2025首次覆盖", "search", "798029251905"),
    ("国泰君安2019首次覆盖", "search", "614136895381"),
    ("国泰君安2022更新", "search", "721664176494"),
    ("国泰君安2023更新", "search", "737374004477"),
    ("中金2026更新", "company", "830853874814"),
]

for label, kind, rptid in rptids:
    base = f"https://stock.finance.sina.com.cn/stock/go.php/vReport_Show/kind/{kind}/rptid/{rptid}"
    print("\n====", label, rptid, flush=True)
    for suffix in ["url", "index.phtml"]:
        url = f"{base}/{suffix}"
        try:
            r = session.get(url, headers=headers, timeout=90, allow_redirects=False)
            print("NOREDIR", suffix, r.status_code, r.headers.get("location"), r.headers.get("content-type"), len(r.content), flush=True)
            print("HEAD", r.content[:200], flush=True)
            if r.is_redirect or r.is_permanent_redirect:
                loc = r.headers.get("location")
                if loc:
                    rr = session.get(loc, headers=headers, timeout=90, allow_redirects=True)
                    print("REDIR_TARGET", rr.status_code, rr.url, rr.headers.get("content-type"), len(rr.content), rr.content[:20], flush=True)
            else:
                rr = session.get(url, headers=headers, timeout=90, allow_redirects=True)
                print("FINAL", rr.status_code, rr.url, rr.headers.get("content-type"), len(rr.content), rr.content[:20], flush=True)
        except Exception as exc:
            print("ERROR", suffix, repr(exc), flush=True)

    page = session.get(f"{base}/index.phtml", headers=headers, timeout=90)
    text = page.content.decode("gb18030", errors="replace")
    for m in re.finditer(r".{0,300}/url.{0,500}", text, re.I | re.S):
        print("URL_CONTEXT", re.sub(r"\s+", " ", m.group(0)), flush=True)

print("PROBE_COMPLETE", flush=True)

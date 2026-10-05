from __future__ import annotations

import html
import json
import re
from urllib.parse import urljoin

import requests

S = requests.Session()
S.trust_env = False
H = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/152 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Referer": "https://www.cninfo.com.cn/",
}


def print_json(label, value):
    print(label, json.dumps(value, ensure_ascii=False, indent=2), flush=True)


# 1) Eastmoney all-market announcement date window
print("=== EASTMONEY ALL MARKET ===", flush=True)
matches = []
for page in range(1, 31):
    params = {
        "sr": "-1",
        "page_size": "100",
        "page_index": str(page),
        "ann_type": "A",
        "client_source": "web",
        "f_node": "0",
        "s_node": "0",
        "begin_time": "2020-07-20",
        "end_time": "2020-07-22",
    }
    r = S.get("https://np-anotice-stock.eastmoney.com/api/security/ann", params=params, headers=H, timeout=60)
    print("EM_PAGE", page, r.status_code, len(r.content), r.url, flush=True)
    r.raise_for_status()
    data = (r.json().get("data") or {})
    rows = data.get("list") or []
    total = int(data.get("total_hits") or data.get("total") or 0)
    for row in rows:
        title = str(row.get("title") or row.get("notice_title") or "")
        codes = json.dumps(row.get("codes") or row.get("stock_list") or row.get("security_list") or [], ensure_ascii=False)
        hay = title + " " + codes + " " + json.dumps(row, ensure_ascii=False)
        if ("甘源食品" in hay or "002991" in hay) and "招股说明书" in hay:
            matches.append(row)
    if not rows or page * 100 >= total or len(rows) < 100:
        break
print_json("EM_MATCHES", matches)

# 2) CNINFO query variants
print("=== CNINFO ===", flush=True)
cninfo_url = "https://www.cninfo.com.cn/new/hisAnnouncement/query"
variants = [
    {
        "pageNum": "1", "pageSize": "30", "column": "szse", "tabName": "fulltext",
        "plate": "sz", "stock": "", "searchkey": "甘源食品 招股说明书",
        "secid": "", "category": "", "trade": "", "seDate": "2020-07-01~2020-08-01",
        "sortName": "", "sortType": "", "isHLtitle": "true",
    },
    {
        "pageNum": "1", "pageSize": "30", "column": "szse", "tabName": "fulltext",
        "plate": "sz", "stock": "002991", "searchkey": "招股说明书",
        "secid": "", "category": "", "trade": "", "seDate": "2020-07-01~2020-08-01",
        "sortName": "", "sortType": "", "isHLtitle": "true",
    },
    {
        "pageNum": "1", "pageSize": "30", "column": "szse", "tabName": "fulltext",
        "plate": "sz", "stock": "", "searchkey": "甘源食品",
        "secid": "", "category": "category_ndbg_szsh;category_bndbg_szsh;category_yjdbg_szsh;category_sjdbg_szsh",
        "trade": "", "seDate": "2020-07-20~2020-07-22",
        "sortName": "", "sortType": "", "isHLtitle": "true",
    },
]
for i, payload in enumerate(variants, 1):
    headers = dict(H)
    headers.update({"Content-Type": "application/x-www-form-urlencoded; charset=UTF-8", "X-Requested-With": "XMLHttpRequest"})
    try:
        r = S.post(cninfo_url, data=payload, headers=headers, timeout=60)
        print("CNINFO_VARIANT", i, r.status_code, r.headers.get("content-type"), len(r.content), flush=True)
        print("CNINFO_HEAD", r.text[:300].replace("\n", " "), flush=True)
        if r.headers.get("content-type", "").lower().startswith("application/json") or r.text.lstrip().startswith("{"):
            obj = r.json()
            anns = obj.get("announcements") or []
            filtered = []
            for ann in anns:
                hay = json.dumps(ann, ensure_ascii=False)
                if "甘源食品" in hay or "002991" in hay or "招股说明书" in hay:
                    filtered.append(ann)
            print_json(f"CNINFO_MATCHES_{i}", filtered)
        else:
            print("CNINFO_BODY", r.text[:2000], flush=True)
    except Exception as exc:
        print("CNINFO_ERROR", i, repr(exc), flush=True)

# 3) Lixinger page source
print("=== LIXINGER ===", flush=True)
url = "https://www.lixinger.com/equity/company/detail/sz/002991/2991/announcement?type=ipo"
try:
    r = S.get(url, headers=H, timeout=60, allow_redirects=True)
    print("LIX_STATUS", r.status_code, r.url, r.headers.get("content-type"), len(r.content), flush=True)
    text = r.text
    all_urls = []
    for m in re.finditer(r'''(?:href|src)\s*=\s*["']([^"']+)["']''', text, re.I):
        all_urls.append(urljoin(r.url, html.unescape(m.group(1))))
    strings = re.findall(r'''["']([^"']*(?:pdf|PDF|download|announcement|002991|6451512)[^"']*)["']''', text)
    print_json("LIX_LINKS", list(dict.fromkeys([u for u in all_urls if any(k in u.lower() for k in ("pdf", "download", "announcement", "002991"))]))[:300])
    print_json("LIX_STRINGS", list(dict.fromkeys(strings))[:500])
    next_data = re.search(r'<script[^>]+id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>', text, re.I | re.S)
    if next_data:
        print("LIX_NEXT_DATA", next_data.group(1)[:20000], flush=True)
    for pat in ("首次公开发行股票招股说明书", "10,615", "10615", "6451512", "2020-07-21"):
        pos = text.find(pat)
        if pos >= 0:
            print("LIX_AROUND", pat, re.sub(r"\s+", " ", text[max(0, pos-1000):pos+3000]), flush=True)
except Exception as exc:
    print("LIX_ERROR", repr(exc), flush=True)

# 4) FX report viewer source and predictable file probes
print("=== FXBAOGAO ===", flush=True)
view_url = "https://www.fxbaogao.com/view?id=2098902"
try:
    r = S.get(view_url, headers=H, timeout=60, allow_redirects=True)
    print("FX_VIEW", r.status_code, r.url, r.headers.get("content-type"), len(r.content), flush=True)
    text = r.text
    strings = re.findall(r'''["']([^"']*(?:pdf|PDF|report-image|2098902|download|fileUrl|oss)[^"']*)["']''', text)
    print_json("FX_STRINGS", list(dict.fromkeys(strings))[:1000])
    next_data = re.search(r'<script[^>]+id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>', text, re.I | re.S)
    if next_data:
        print("FX_NEXT_DATA", next_data.group(1)[:50000], flush=True)
except Exception as exc:
    print("FX_VIEW_ERROR", repr(exc), flush=True)

candidates = [
    "https://public.fxbaogao.com/report-pdf/2020/07/21/2098902.pdf",
    "https://public.fxbaogao.com/report/2020/07/21/2098902.pdf",
    "https://public.fxbaogao.com/report-file/2020/07/21/2098902.pdf",
    "https://public.fxbaogao.com/pdf/2020/07/21/2098902.pdf",
    "https://public.fxbaogao.com/report-pdf/2098902.pdf",
    "https://public.fxbaogao.com/report/2098902.pdf",
]
for u in candidates:
    try:
        rr = S.get(u, headers={**H, "Range": "bytes=0-63"}, timeout=40, allow_redirects=True)
        print("FX_PROBE", u, rr.status_code, rr.url, rr.headers.get("content-type"), rr.headers.get("content-length"), repr(rr.content[:16]), flush=True)
    except Exception as exc:
        print("FX_PROBE_ERROR", u, repr(exc), flush=True)

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


def dump(label, obj, limit=50000):
    text = json.dumps(obj, ensure_ascii=False, indent=2)
    print(label, text[:limit], flush=True)


print("=== CNINFO ===", flush=True)
url = "https://www.cninfo.com.cn/new/hisAnnouncement/query"
variants = [
    ("all-keyword", {
        "pageNum": "1", "pageSize": "50", "column": "szse", "tabName": "fulltext",
        "plate": "sz", "stock": "", "searchkey": "甘源食品 招股说明书", "secid": "",
        "category": "", "trade": "", "seDate": "2020-07-01~2020-08-01",
        "sortName": "", "sortType": "", "isHLtitle": "true",
    }),
    ("stock-keyword", {
        "pageNum": "1", "pageSize": "50", "column": "szse", "tabName": "fulltext",
        "plate": "sz", "stock": "002991", "searchkey": "招股说明书", "secid": "",
        "category": "", "trade": "", "seDate": "2020-07-01~2020-08-01",
        "sortName": "", "sortType": "", "isHLtitle": "true",
    }),
    ("keyword-only", {
        "pageNum": "1", "pageSize": "50", "column": "szse", "tabName": "fulltext",
        "plate": "sz", "stock": "", "searchkey": "甘源食品", "secid": "",
        "category": "", "trade": "", "seDate": "2020-07-20~2020-07-22",
        "sortName": "", "sortType": "", "isHLtitle": "true",
    }),
]
for name, payload in variants:
    headers = dict(H)
    headers.update({"Content-Type": "application/x-www-form-urlencoded; charset=UTF-8", "X-Requested-With": "XMLHttpRequest"})
    try:
        r = S.post(url, data=payload, headers=headers, timeout=90)
        print("CNINFO", name, r.status_code, r.headers.get("content-type"), len(r.content), r.url, flush=True)
        print("HEAD", r.text[:500].replace("\n", " "), flush=True)
        if r.status_code == 200 and r.text.lstrip().startswith("{"):
            obj = r.json()
            anns = obj.get("announcements") or []
            dump("ANNOUNCEMENTS_" + name, anns)
    except Exception as exc:
        print("CNINFO_ERROR", name, repr(exc), flush=True)

print("=== LIXINGER ===", flush=True)
lix = "https://www.lixinger.com/equity/company/detail/sz/002991/2991/announcement?type=ipo"
try:
    r = S.get(lix, headers=H, timeout=90, allow_redirects=True)
    print("LIX", r.status_code, r.url, r.headers.get("content-type"), len(r.content), flush=True)
    text = r.text
    links = []
    for m in re.finditer(r'''(?:href|src)\s*=\s*["']([^"']+)["']''', text, re.I):
        links.append(urljoin(r.url, html.unescape(m.group(1))))
    dump("LIX_LINKS", list(dict.fromkeys([x for x in links if any(k in x.lower() for k in ("pdf", "download", "announcement", "002991"))])))
    strings = re.findall(r'''["']([^"']*(?:pdf|PDF|download|announcement|002991|10615|6451512)[^"']*)["']''', text)
    dump("LIX_STRINGS", list(dict.fromkeys(strings)))
    for pat in ("首次公开发行股票招股说明书", "10,615", "10615", "2020-07-21"):
        for pos in [m.start() for m in re.finditer(re.escape(pat), text, re.I)][:5]:
            print("LIX_AROUND", pat, re.sub(r"\s+", " ", text[max(0, pos-1200):pos+3500]), flush=True)
except Exception as exc:
    print("LIX_ERROR", repr(exc), flush=True)

print("=== FXBAOGAO ===", flush=True)
for target in ("https://www.fxbaogao.com/detail/2098902", "https://www.fxbaogao.com/view?id=2098902"):
    try:
        r = S.get(target, headers=H, timeout=90, allow_redirects=True)
        print("FX", target, r.status_code, r.url, r.headers.get("content-type"), len(r.content), flush=True)
        text = r.text
        links = []
        for m in re.finditer(r'''(?:href|src)\s*=\s*["']([^"']+)["']''', text, re.I):
            links.append(urljoin(r.url, html.unescape(m.group(1))))
        dump("FX_LINKS", list(dict.fromkeys([x for x in links if any(k in x.lower() for k in ("pdf", "download", "report-image", "2098902"))])))
        strings = re.findall(r'''["']([^"']*(?:pdf|PDF|report-image|2098902|download|fileUrl|oss)[^"']*)["']''', text)
        dump("FX_STRINGS", list(dict.fromkeys(strings)))
        for pat in ("report-image", "2098902-1.png", "pageCount", "totalPage", ".pdf"):
            for pos in [m.start() for m in re.finditer(re.escape(pat), text, re.I)][:5]:
                print("FX_AROUND", pat, re.sub(r"\s+", " ", text[max(0, pos-1200):pos+3500]), flush=True)
    except Exception as exc:
        print("FX_ERROR", target, repr(exc), flush=True)

print("=== DIRECT PROBES ===", flush=True)
candidates = [
    "https://public.fxbaogao.com/report-pdf/2020/07/21/2098902.pdf",
    "https://public.fxbaogao.com/report/2020/07/21/2098902.pdf",
    "https://public.fxbaogao.com/report-file/2020/07/21/2098902.pdf",
    "https://public.fxbaogao.com/pdf/2020/07/21/2098902.pdf",
    "https://public.fxbaogao.com/report-pdf/2098902.pdf",
    "https://public.fxbaogao.com/report/2098902.pdf",
]
for target in candidates:
    try:
        r = S.get(target, headers={**H, "Range": "bytes=0-127"}, timeout=60, allow_redirects=True)
        print("PROBE", target, r.status_code, r.url, r.headers.get("content-type"), r.headers.get("content-length"), repr(r.content[:32]), flush=True)
    except Exception as exc:
        print("PROBE_ERROR", target, repr(exc), flush=True)

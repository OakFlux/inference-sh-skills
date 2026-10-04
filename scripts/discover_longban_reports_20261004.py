from __future__ import annotations

import html
import json
import re
import sys
from urllib.parse import quote_plus, urljoin
import xml.etree.ElementTree as ET

import requests

S = requests.Session()
S.trust_env = False
H = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/152 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


def call(method: str, url: str, **kwargs) -> requests.Response | None:
    headers = {**H, **kwargs.pop("headers", {})}
    try:
        r = S.request(method, url, headers=headers, timeout=(15, 60), allow_redirects=True, **kwargs)
        print(f"HTTP {method} {url} -> {r.status_code} {r.url} {r.headers.get('content-type')} {len(r.content)}", flush=True)
        return r
    except Exception as exc:
        print(f"ERROR {method} {url}: {exc!r}", flush=True)
        return None


def summarize_sdyanbao(keyword: str) -> list[dict]:
    r = call(
        "POST",
        "https://www.sdyanbao.com/api/file/search",
        json={
            "keyword": keyword,
            "page": 1,
            "pageSize": 100,
            "order": 0,
            "recommend": 0,
            "hideTrader": 0,
            "quanwen": True,
            "dateRange": 0,
            "startTime": "",
            "endTime": "",
            "typeIds": "",
            "industryIds": "",
        },
        headers={"Content-Type": "application/json", "Referer": "https://www.sdyanbao.com/report"},
    )
    if not r:
        return []
    try:
        payload = r.json()
    except Exception:
        print("SDYANBAO_NONJSON", r.text[:3000], flush=True)
        return []
    print("SDYANBAO_RAW", keyword, json.dumps(payload, ensure_ascii=False)[:20000], flush=True)
    data = payload.get("data", payload) if isinstance(payload, dict) else payload
    files = []
    if isinstance(data, dict):
        for key in ("files", "items", "list", "data"):
            if isinstance(data.get(key), list):
                files = data[key]
                break
    elif isinstance(data, list):
        files = data
    compact = []
    for f in files:
        if not isinstance(f, dict):
            continue
        compact.append({k: f.get(k) for k in (
            "id", "name", "time_text", "page_count", "file_size", "size", "original_id",
            "page_url", "online_url", "share_url", "data_source_uuid", "keyword"
        ) if f.get(k) is not None} | {
            "organization": (f.get("organization") or {}).get("name") if isinstance(f.get("organization"), dict) else f.get("organization"),
            "stock": f.get("stock"),
            "researcher": f.get("researcher"),
        })
    print("SDYANBAO_COMPACT", keyword, json.dumps(compact, ensure_ascii=False, indent=2), flush=True)
    return compact


def inspect_sdyanbao_detail(file_id: int) -> None:
    r = call("GET", f"https://www.sdyanbao.com/detail/{file_id}", headers={"Referer": "https://www.sdyanbao.com/report"})
    if not r:
        return
    t = r.text
    patterns = [
        r"page_url:\"([^\"]+)\"",
        r"share_url:\"([^\"]+)\"",
        r"original_id:(\d+)",
        r"page_count:(\d+)",
        r"online_url:([^,}]+)",
        r"data_source_uuid:\"([^\"]+)\"",
        r"organization:\{id:[^}]*name:\"([^\"]+)\"",
        r"researcher:\{id:[^}]*name:\"([^\"]+)\"",
    ]
    print("SDYANBAO_DETAIL_ID", file_id, flush=True)
    for p in patterns:
        vals = re.findall(p, t)
        if vals:
            print("PATTERN", p, vals[:20], flush=True)
    for token in ("龙版传媒", "深耕出版业务主业", "page_url", "original_id", "online_url", "share_url"):
        pos = t.find(token)
        if pos >= 0:
            print("CTX", token, t[max(0, pos-500):pos+1500].replace("\\u002F", "/"), flush=True)


def inspect_nxny_detail(report_id: int) -> None:
    r = call("GET", f"https://www.nxny.com/report/view_{report_id}.html")
    if not r:
        return
    t = r.text
    print("NXNY_TITLE", re.findall(r"<title>(.*?)</title>", t, flags=re.I|re.S)[:3], flush=True)
    for p in [
        r"downfile\((.*?)\)",
        r"DownLoad\.aspx\?rnd=([^\"'&]+)",
        r"rnd\s*=\s*['\"]([^'\"]+)",
        r"filename\s*=\s*['\"]([^'\"]+)",
        r"href=['\"]([^'\"]*(?:pdf|download|DownLoad)[^'\"]*)['\"]",
        r"<form[^>]*action=['\"]([^'\"]+)['\"]",
    ]:
        vals = re.findall(p, t, flags=re.I|re.S)
        if vals:
            print("NXNY_PATTERN", p, vals[:30], flush=True)
    for token in ("龙版传媒", "深耕出版业务主业", "download", "DownUrl", "downfile", "rnd"):
        for m in list(re.finditer(token, t, flags=re.I))[:5]:
            pos=m.start()
            print("NXNY_CTX", token, t[max(0,pos-600):pos+1800], flush=True)


def bing_rss(query: str) -> list[dict]:
    r = call("GET", "https://www.bing.com/search", params={"format":"rss", "q": query})
    if not r:
        return []
    print("BING_RSS_RAW", query, r.text[:12000], flush=True)
    items=[]
    try:
        root=ET.fromstring(r.content)
        for item in root.findall(".//item"):
            title=item.findtext("title") or ""
            link=item.findtext("link") or ""
            desc=item.findtext("description") or ""
            items.append({"title":html.unescape(title),"link":link,"description":html.unescape(desc)})
    except Exception as exc:
        print("BING_PARSE_ERROR", repr(exc), flush=True)
    print("BING_ITEMS", query, json.dumps(items, ensure_ascii=False, indent=2)[:20000], flush=True)
    return items


def main() -> None:
    found=[]
    for kw in [
        "龙版传媒",
        "605577",
        "深耕出版业务主业 业绩发展稳健",
        "东北证券 龙版传媒",
        "出版行业 年报 一季报 高股息",
        "出版行业 深度报告",
    ]:
        rows=summarize_sdyanbao(kw)
        for row in rows:
            name=str(row.get("name") or "")
            if "龙版传媒" in name or "出版" in name:
                found.append(row)
    ids=[]
    for row in found:
        try:
            ids.append(int(row["id"]))
        except Exception:
            pass
    for fid in sorted(set(ids))[:30]:
        inspect_sdyanbao_detail(fid)

    inspect_nxny_detail(5499041)

    for q in [
        '"龙版传媒" "深耕出版业务主业，业绩发展稳健"',
        '"龙版传媒" filetype:pdf 研报',
        '"龙版传媒" 券商 研究报告',
        '"出版行业" "龙版传媒" 券商 研报',
        '"出版行业2025年报及2026年一季报业绩综述"',
    ]:
        bing_rss(q)


if __name__ == "__main__":
    main()

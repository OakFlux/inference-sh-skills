from __future__ import annotations

import json
import re
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/152 Safari/537.36"
S = requests.Session()
S.trust_env = False
S.headers.update({"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"})


def dump(label, obj):
    print(f"\n===== {label} =====")
    print(json.dumps(obj, ensure_ascii=False, indent=2)[:100000])


def request(method, url, **kwargs):
    try:
        r = S.request(method, url, timeout=(20, 120), allow_redirects=True, **kwargs)
        print("HTTP", method, url, "=>", r.status_code, r.url, r.headers.get("content-type"), len(r.content))
        return r
    except Exception as e:
        print("ERR", method, url, repr(e))
        return None


def probe_sdyanbao():
    url = "https://www.sdyanbao.com/api/file/search"
    payloads = [
        {"keyword": "蓝丰生化", "page": 1, "pageSize": 100},
        {"keyword": "002513", "page": 1, "pageSize": 100},
        {"keyword": "蓝丰", "page": 1, "pageSize": 100},
        {"keyword": "蓝丰生化", "page": 1, "pageSize": 100, "quanwen": True},
        {"keyword": "002513", "page": 1, "pageSize": 100, "quanwen": True},
    ]
    for i, payload in enumerate(payloads, 1):
        for style in ("json", "data"):
            kw = {style: payload}
            r = request("POST", url, headers={"Referer": "https://www.sdyanbao.com/report"}, **kw)
            if not r:
                continue
            try:
                obj = r.json()
            except Exception:
                print(r.text[:5000])
                continue
            dump(f"SDY {i} {style}", obj)
            files = []
            if isinstance(obj, dict):
                data = obj.get("data")
                if isinstance(data, dict):
                    files = data.get("files") or data.get("items") or []
                elif isinstance(data, list):
                    files = data
            if files:
                compact = []
                for x in files:
                    compact.append({k: x.get(k) for k in ["id", "name", "time_text", "page_count", "size", "online_url", "page_url", "share_url", "data_source_uuid"]})
                    for k in ["type", "industry", "organization", "researcher", "stock"]:
                        if isinstance(x.get(k), dict):
                            compact[-1][k] = x[k]
                dump(f"SDY COMPACT {i} {style}", compact)


def parse_links(base, html, pattern="/report/view_"):
    soup = BeautifulSoup(html, "html.parser")
    out = []
    for a in soup.find_all("a", href=True):
        href = a.get("href")
        text = " ".join(a.get_text(" ", strip=True).split())
        title = a.get("title") or ""
        if pattern in href or "蓝丰生化" in text or "蓝丰生化" in title or "002513" in text or "002513" in title:
            out.append({"url": urljoin(base, href), "text": text, "title": title})
    seen = set()
    uniq = []
    for x in out:
        key = x["url"]
        if key not in seen:
            seen.add(key)
            uniq.append(x)
    return uniq


def probe_nxny():
    urls = [
        "https://www.nxny.com/Search.aspx?keyword=%E8%93%9D%E4%B8%B0%E7%94%9F%E5%8C%96",
        "https://www.nxny.com/Search.aspx?keyword=002513",
        "https://www.nxny.com/stock/stock_002513/",
        "https://www.nxny.com/stock/stock_002513.html",
    ]
    all_links = []
    for url in urls:
        r = request("GET", url)
        if not r:
            continue
        print(r.text[:3000])
        links = parse_links(r.url, r.text)
        dump("NXNY LINKS " + url, links)
        all_links.extend(links)
    uniq = {x["url"]: x for x in all_links}
    for url, meta in list(uniq.items())[:100]:
        r = request("GET", url)
        if not r:
            continue
        title = ""
        m = re.search(r"<title[^>]*>(.*?)</title>", r.text, flags=re.I|re.S)
        if m:
            title = re.sub(r"\s+", " ", BeautifulSoup(m.group(1), "html.parser").get_text(" ", strip=True))
        print("NXNY DETAIL", url, title)
        for line in r.text.splitlines():
            if any(t in line for t in ["上传日期", "格式", "来源", "评级", "作者", "共", "downfile", "rnd"]):
                print(line[:2000])


def probe_search_sites():
    urls = [
        "https://www.51yanbao.com/search?keyword=%E8%93%9D%E4%B8%B0%E7%94%9F%E5%8C%96",
        "https://www.microbell.com/stock/002513",
        "https://report.seedsufe.com/search?keyword=%E8%93%9D%E4%B8%B0%E7%94%9F%E5%8C%96",
        "https://stock.finance.sina.com.cn/stock/go.php/vReport_List/kind/search/index.phtml?symbol=002513&t1=all",
    ]
    for url in urls:
        r = request("GET", url)
        if not r:
            continue
        print("SITE", url, r.text[:5000])
        links = parse_links(r.url, r.text, pattern="report")
        dump("SITE LINKS " + url, links[:100])


if __name__ == "__main__":
    probe_sdyanbao()
    probe_nxny()
    probe_search_sites()

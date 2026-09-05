#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import re
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/151 Safari/537.36"
s = requests.Session()
s.headers.update({"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7"})

PAGES = {
    "yongxing": "https://stock.finance.sina.com.cn/stock/go.php/vReport_Show/kind/search/rptid/815391780519/index.phtml",
    "huafu": "https://stock.finance.sina.com.cn/stock/go.php/vReport_Show/kind/company/rptid/774398970577/index.phtml",
    "cicc2019": "https://www.sohu.com/a/344517878_734250",
}

out = Path("sina-guangshen-probe")
out.mkdir(exist_ok=True)
results = {}

for name, url in PAGES.items():
    try:
        r = s.get(url, timeout=(30, 180), allow_redirects=True)
        raw = r.content
        encodings = [r.encoding, r.apparent_encoding, "gb18030", "gbk", "utf-8"]
        text = None
        used = None
        for enc in encodings:
            if not enc:
                continue
            try:
                decoded = raw.decode(enc)
                if text is None or decoded.count("�") < text.count("�"):
                    text = decoded
                    used = enc
            except Exception:
                continue
        text = text or raw.decode("utf-8", errors="replace")
        (out / f"{name}.html").write_text(text, encoding="utf-8")
        soup = BeautifulSoup(text, "html.parser")
        links = []
        for tag in soup.find_all(True):
            for attr in ("href", "src", "data-src", "data-url", "content", "value", "action"):
                value = tag.get(attr)
                if isinstance(value, str) and value.strip():
                    absolute = urljoin(r.url, value.strip())
                    links.append({"tag": tag.name, "attr": attr, "raw": value.strip(), "url": absolute})
        url_regex = re.findall(r"(?:https?:)?//[^\s\"'<>\\]+|/[A-Za-z0-9_./?=&%+:-]+", text)
        for value in url_regex:
            links.append({"tag": "regex", "attr": "text", "raw": value, "url": urljoin(r.url, value)})
        dedup = []
        seen = set()
        for item in links:
            key = item["url"]
            if key not in seen:
                seen.add(key)
                dedup.append(item)
        interesting = [x for x in dedup if any(k in x["url"].lower() or k in x["raw"].lower() for k in ("pdf", "download", "report", "rpt", "file", "attach", "doc", "view", "api"))]
        scripts = []
        for m in re.finditer(r".{0,220}(?:pdf|download|report|rptid|file|attach|iframe|openapi|api).{0,500}", text, flags=re.I | re.S):
            snippet = re.sub(r"\s+", " ", m.group(0))
            scripts.append(snippet[:1000])
        result = {
            "name": name,
            "requested": url,
            "resolved": r.url,
            "status": r.status_code,
            "content_type": r.headers.get("content-type"),
            "bytes": len(raw),
            "response_encoding": r.encoding,
            "apparent_encoding": r.apparent_encoding,
            "used_encoding": used,
            "title": soup.title.string.strip() if soup.title and soup.title.string else "",
            "interesting_links": interesting,
            "snippets": scripts[:200],
        }
        results[name] = result
        print("PAGE", name, json.dumps({k: v for k, v in result.items() if k not in ("interesting_links", "snippets")}, ensure_ascii=False), flush=True)
        print("INTERESTING", name, len(interesting), flush=True)
        for item in interesting[:200]:
            print("LINK", name, json.dumps(item, ensure_ascii=False), flush=True)
        print("SNIPPETS", name, len(scripts), flush=True)
        for snippet in scripts[:60]:
            print("SNIP", name, snippet, flush=True)
    except Exception as exc:
        results[name] = {"error": repr(exc), "url": url}
        print("ERROR", name, repr(exc), flush=True)

Path("sina-guangshen-probe.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import re
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/151.0.0.0 Safari/537.36"
s = requests.Session()
s.headers.update({"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7"})

PAGES = {
    "book118_huafu": "https://max.book118.com/html/2024/0717/7031151105006134.shtm",
    "baogao_huafu": "https://www.baogao.com/jigou/1413517.html",
    "baogaobox_huafu": "https://www.baogaobox.com/reports/240715000023955.html",
    "sohu_cicc": "https://www.sohu.com/a/344517878_734250",
}
out = Path("guangshen-public-host-probe")
out.mkdir(exist_ok=True)
all_results = {}


def decode(r):
    candidates = []
    for enc in (r.encoding, r.apparent_encoding, "utf-8", "gb18030"):
        if not enc:
            continue
        try:
            text = r.content.decode(enc)
            candidates.append((text.count("�"), -len(text), enc, text))
        except Exception:
            pass
    candidates.sort()
    return candidates[0][2], candidates[0][3]


def probe(url, referer, label):
    try:
        r = s.get(url, headers={"User-Agent": UA, "Referer": referer, "Accept": "application/pdf,application/json,text/html,*/*", "Range": "bytes=0-1048575"}, timeout=(30, 120), allow_redirects=True)
        rec = {
            "label": label, "requested": url, "resolved": r.url, "status": r.status_code,
            "type": r.headers.get("content-type"), "length": r.headers.get("content-length"),
            "bytes": len(r.content), "head": r.content[:16].hex(),
            "history": [(x.status_code, x.url, x.headers.get("location")) for x in r.history],
        }
        print("PROBE", json.dumps(rec, ensure_ascii=False), flush=True)
        if r.content.startswith(b"%PDF-"):
            path = out / f"{label}.pdf"
            # Re-download whole file if server honored range.
            full = s.get(r.url, headers={"User-Agent": UA, "Referer": referer, "Accept": "application/pdf,*/*"}, timeout=(30, 600), allow_redirects=True)
            if full.status_code == 200 and full.content.startswith(b"%PDF-"):
                path.write_bytes(full.content)
                rec["pdf_path"] = str(path)
                rec["full_bytes"] = len(full.content)
                print("FOUND PDF", path, len(full.content), flush=True)
        return rec
    except Exception as exc:
        rec = {"label": label, "requested": url, "error": repr(exc)}
        print("ERROR", json.dumps(rec, ensure_ascii=False), flush=True)
        return rec


for name, page_url in PAGES.items():
    result = {"page": page_url, "links": [], "probes": []}
    try:
        r = s.get(page_url, timeout=(30, 180), allow_redirects=True)
        enc, text = decode(r)
        (out / f"{name}.html").write_text(text, encoding="utf-8")
        soup = BeautifulSoup(text, "html.parser")
        print("PAGE", name, r.status_code, r.url, r.headers.get("content-type"), len(r.content), enc, soup.title.get_text(" ", strip=True) if soup.title else "", flush=True)
        links = []
        for tag in soup.find_all(True):
            for attr in ("href", "src", "data-src", "data-url", "data-download", "data-file", "data-pdf", "content", "value", "action"):
                value = tag.get(attr)
                if isinstance(value, str) and value.strip():
                    links.append({"tag": tag.name, "attr": attr, "raw": value.strip(), "url": urljoin(r.url, value.strip())})
        patterns = [
            r"(?:https?:)?//[^\s\"'<>\\]+",
            r"/(?:download|downloads|file|files|pdf|preview|api|document|doc|attachment|source|view)[^\s\"'<>\\]*",
        ]
        for pattern in patterns:
            for value in re.findall(pattern, text, flags=re.I):
                links.append({"tag": "regex", "attr": "text", "raw": value, "url": urljoin(r.url, value)})
        dedup = []
        seen = set()
        for item in links:
            u = item["url"].rstrip("),]};'\"")
            if u in seen:
                continue
            seen.add(u)
            item["url"] = u
            hay = (u + " " + item["raw"]).lower()
            if any(k in hay for k in ("pdf", "download", "file", "doc", "preview", "attachment", "source", "api", "7031151105006134", "1413517", "240715000023955")):
                dedup.append(item)
        result["links"] = dedup
        print("LINKS", name, len(dedup), flush=True)
        for item in dedup[:300]:
            print("LINK", name, json.dumps(item, ensure_ascii=False), flush=True)

        snippets = []
        for m in re.finditer(r".{0,400}(?:pdf|download|fileUrl|file_url|docId|doc_id|preview|attachment|sourceUrl|source_url|oss|7031151105006134|1413517|240715000023955).{0,1000}", text, flags=re.I | re.S):
            snip = re.sub(r"\s+", " ", m.group(0))[:1800]
            if snip not in snippets:
                snippets.append(snip)
        print("SNIPPETS", name, len(snippets), flush=True)
        for snip in snippets[:120]:
            print("SNIP", name, snip, flush=True)

        for idx, item in enumerate(dedup[:220], 1):
            u = item["url"]
            if len(u) > 700 or u.startswith("javascript:") or any(x in u.lower() for x in (".css", ".js", "favicon", "logo", "icon")):
                continue
            rec = probe(u, r.url, f"{name}_{idx:03d}")
            result["probes"].append(rec)
    except Exception as exc:
        result["error"] = repr(exc)
        print("PAGE ERROR", name, repr(exc), flush=True)
    all_results[name] = result

Path("guangshen-public-host-results.json").write_text(json.dumps(all_results, ensure_ascii=False, indent=2), encoding="utf-8")

#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import re
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASE = "https://www.hangyan.co"
RID = "3193514544576070801"
PAGE = f"{BASE}/reports/{RID}"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/151.0.0.0 Safari/537.36"

s = requests.Session()
s.headers.update({
    "User-Agent": UA,
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
    "Accept": "text/html,application/xhtml+xml,application/json,application/pdf;q=0.9,*/*;q=0.8",
})
out = Path("hangyan-guangshen-probe")
out.mkdir(exist_ok=True)


def decode(response):
    encs = [response.encoding, response.apparent_encoding, "utf-8", "gb18030"]
    candidates = []
    for enc in encs:
        if not enc:
            continue
        try:
            text = response.content.decode(enc)
            candidates.append((text.count("�"), -len(text), enc, text))
        except Exception:
            pass
    if not candidates:
        return "utf-8-replace", response.content.decode("utf-8", errors="replace")
    candidates.sort()
    _, _, enc, text = candidates[0]
    return enc, text


def probe_url(label, url, referer=PAGE, method="GET", data=None):
    try:
        headers = {"User-Agent": UA, "Referer": referer, "Accept": "application/pdf,application/json,text/html,*/*"}
        r = s.request(method, url, data=data, headers=headers, timeout=(30, 180), allow_redirects=True)
        head = r.content[:16]
        rec = {
            "label": label, "requested": url, "resolved": r.url, "status": r.status_code,
            "content_type": r.headers.get("content-type"), "content_length": r.headers.get("content-length"),
            "bytes": len(r.content), "head_hex": head.hex(), "location": r.history[-1].headers.get("location") if r.history else None,
            "history": [(x.status_code, x.url, x.headers.get("location")) for x in r.history],
        }
        print("PROBE", json.dumps(rec, ensure_ascii=False), flush=True)
        if r.content.startswith(b"%PDF-"):
            path = out / f"{label}.pdf"
            path.write_bytes(r.content)
            rec["pdf_path"] = str(path)
            print("FOUND PDF", path, len(r.content), flush=True)
        else:
            enc, text = decode(r)
            rec["encoding"] = enc
            rec["text_head"] = re.sub(r"\s+", " ", text[:1200])
            (out / f"{label}.txt").write_text(text, encoding="utf-8")
        return rec, r
    except Exception as exc:
        rec = {"label": label, "requested": url, "error": repr(exc)}
        print("ERROR", json.dumps(rec, ensure_ascii=False), flush=True)
        return rec, None


results = []
page_rec, page_resp = probe_url("report_page", PAGE, referer=BASE + "/reports")
results.append(page_rec)

links = []
if page_resp is not None:
    enc, text = decode(page_resp)
    soup = BeautifulSoup(text, "html.parser")
    print("PAGE TITLE", soup.title.get_text(" ", strip=True) if soup.title else "", flush=True)
    for tag in soup.find_all(True):
        for attr in ("href", "src", "action", "data-url", "data-src", "data-download", "data-turbo-frame", "data-controller", "data-report-id", "value", "content"):
            value = tag.get(attr)
            if isinstance(value, str) and value.strip():
                links.append({"tag": tag.name, "attr": attr, "raw": value.strip(), "url": urljoin(page_resp.url, value.strip())})
    # Extract absolute/relative URLs and Rails ActiveStorage signed IDs.
    patterns = [
        r"(?:https?:)?//[^\s\"'<>\\]+",
        r"/(?:rails/active_storage|reports|downloads?|attachments?|files?|api|assets|blobs?)[^\s\"'<>\\]*",
        r"[A-Za-z0-9_-]{40,}",
    ]
    for pattern in patterns:
        for value in re.findall(pattern, text, flags=re.I):
            links.append({"tag": "regex", "attr": "text", "raw": value, "url": urljoin(page_resp.url, value)})
    # Print context around likely attachment/download hints.
    snippets = []
    for m in re.finditer(r".{0,350}(?:active_storage|blob|attachment|download|pdf|report_file|file_url|signed_id|turbo|3193514544576070801).{0,800}", text, flags=re.I | re.S):
        snippet = re.sub(r"\s+", " ", m.group(0))[:1600]
        if snippet not in snippets:
            snippets.append(snippet)
    print("SNIPPETS", len(snippets), flush=True)
    for snip in snippets[:100]:
        print("SNIP", snip, flush=True)

seen = set()
interesting = []
for item in links:
    url = item["url"].rstrip(")]},;\"")
    if url in seen:
        continue
    seen.add(url)
    hay = (url + " " + item["raw"]).lower()
    if any(k in hay for k in ("pdf", "download", "attachment", "active_storage", "blob", "file", "report", "api", RID)):
        item["url"] = url
        interesting.append(item)
print("INTERESTING LINKS", len(interesting), flush=True)
for item in interesting[:300]:
    print("LINK", json.dumps(item, ensure_ascii=False), flush=True)

# Probe any plausible URLs found directly in the page.
for i, item in enumerate(interesting[:180], 1):
    url = item["url"]
    if url.startswith("javascript:") or len(url) > 600 or any(x in url for x in ("fonts.googleapis", "favicon", ".css", ".js")):
        continue
    rec, _ = probe_url(f"found_{i:03d}", url)
    results.append(rec)

# Conventional route guesses for Rails-style apps.
guesses = [
    f"{BASE}/reports/{RID}.pdf",
    f"{BASE}/reports/{RID}?format=pdf",
    f"{BASE}/reports/{RID}/download",
    f"{BASE}/reports/{RID}/downloads",
    f"{BASE}/reports/{RID}/download.pdf",
    f"{BASE}/reports/{RID}/file",
    f"{BASE}/reports/{RID}/attachment",
    f"{BASE}/downloads/{RID}",
    f"{BASE}/download/{RID}",
    f"{BASE}/api/reports/{RID}",
    f"{BASE}/api/v1/reports/{RID}",
    f"{BASE}/reports/{RID}.json",
    f"{BASE}/reports/{RID}?format=json",
    f"{BASE}/reports/{RID}/charts",
]
for idx, url in enumerate(guesses, 1):
    rec, _ = probe_url(f"guess_{idx:02d}", url)
    results.append(rec)

Path("hangyan-guangshen-results.json").write_text(json.dumps({"page": PAGE, "links": interesting, "probes": results}, ensure_ascii=False, indent=2), encoding="utf-8")

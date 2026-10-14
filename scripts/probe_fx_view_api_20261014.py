from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urljoin

import requests

OUT = Path("fx_view_api_probe")
OUT.mkdir(exist_ok=True)

BASE = "https://www.fxbaogao.com/view?id=5201086"
ASSETS = [
    "https://static.fxbaogao.com/pub/js/config/production.js",
    "https://www.fxbaogao.com/_fxbg/2610131816/js/runtime.63c1261c72087296e4cb.js",
    "https://www.fxbaogao.com/_fxbg/2610131816/js/antd-table.efc2d913db806c205059.chunk.js",
    "https://www.fxbaogao.com/_fxbg/2610131816/js/vendors~app-pages-fxbg-main-js.153dbf505adafefa97e9.chunk.js",
    "https://www.fxbaogao.com/_fxbg/2610131816/js/app-pages-fxbg-main-js.7dcddcdd08ec3b0abd00.chunk.js",
]

session = requests.Session()
session.trust_env = False
headers = {"User-Agent": "Mozilla/5.0", "Referer": BASE}

records = []
queue = list(ASSETS)
seen = set()
while queue:
    url = queue.pop(0)
    if url in seen:
        continue
    seen.add(url)
    try:
        r = session.get(url, headers=headers, timeout=(20, 180), allow_redirects=True)
        print("FETCH", r.status_code, len(r.content), r.url, r.headers.get("content-type"), flush=True)
        name = re.sub(r"[^a-zA-Z0-9._-]+", "_", url)[-180:]
        path = OUT / name
        path.write_bytes(r.content)
        text = r.text
        urls = sorted(set(re.findall(r"https?://[^\"'`<>\\\s]+", text)))
        paths = sorted(set(re.findall(r"[\"'`](/{1,2}[^\"'`\s]{3,240})[\"'`]", text)))
        interesting_urls = [x for x in urls if any(k in x.lower() for k in ["fxbaogao", "hufangde", "mofoun", "pdf", "report", "view", "image"])]
        interesting_paths = [x for x in paths if any(k in x.lower() for k in ["mofoun", "pdf", "report", "view", "image", "document", "detail", "download"])]
        strings = sorted(set(re.findall(r"[\"'`]([^\"'`\n]{3,220})[\"'`]", text)))
        interesting_strings = [x for x in strings if any(k in x.lower() for k in ["mofoun", "pdf", "report", "view", "document", "download", "docid", "pagecount", "preview"])]
        rec = {"url": url, "status": r.status_code, "final_url": r.url, "bytes": len(r.content), "urls": interesting_urls, "paths": interesting_paths, "strings": interesting_strings[:5000]}
        records.append(rec)
        for value in interesting_urls:
            print("URL", value, flush=True)
        for value in interesting_paths:
            print("PATH", value, flush=True)
        for value in interesting_strings[:500]:
            print("STR", value[:500], flush=True)
        # Discover webpack chunks from runtime/main strings.
        for match in re.findall(r"(?:src=|u\()+[\"']?([^\"'\s]+\.js)", text):
            child = urljoin(r.url, match)
            if "fxbaogao.com" in child and child not in seen:
                queue.append(child)
    except Exception as exc:  # noqa: BLE001
        records.append({"url": url, "error": repr(exc)})
        print("ERROR", url, repr(exc), flush=True)

(OUT / "records.json").write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")

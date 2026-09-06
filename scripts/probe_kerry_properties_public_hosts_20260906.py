#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/151.0.0.0 Safari/537.36"
OUTDIR = Path("kerry-public-host-probe")
OUTDIR.mkdir(exist_ok=True)

PAGES = {
    "sgpjbg_label": "https://www.sgpjbg.com/labels/jialijianshenianbao.html",
    "fxbaogao_2025_deep": "https://www.fxbaogao.com/detail/4702606",
    "fxbaogao_2026_update": "https://www.fxbaogao.com/detail/5642153",
    "baogaobox_insight": "https://www.baogaobox.com/insights/250304000007937.html",
}

s = requests.Session()
s.headers.update({
    "User-Agent": UA,
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
    "Accept": "text/html,application/xhtml+xml,application/json,application/pdf;q=0.9,*/*;q=0.8",
})


def decode(r: requests.Response) -> tuple[str, str]:
    candidates = []
    for enc in (r.encoding, r.apparent_encoding, "utf-8", "gb18030"):
        if not enc:
            continue
        try:
            t = r.content.decode(enc)
            candidates.append((t.count("�"), -len(t), enc, t))
        except Exception:
            pass
    if not candidates:
        return "utf-8-replace", r.content.decode("utf-8", errors="replace")
    candidates.sort()
    return candidates[0][2], candidates[0][3]


def get(url: str, referer: str | None = None) -> requests.Response:
    headers = {
        "User-Agent": UA,
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
        "Accept": "application/pdf,application/json,text/html,*/*",
    }
    if referer:
        headers["Referer"] = referer
    return s.get(url, headers=headers, timeout=(30, 180), allow_redirects=True)


def probe_candidate(url: str, referer: str, label: str) -> dict:
    try:
        r = get(url, referer)
        rec = {
            "label": label,
            "requested": url,
            "resolved": r.url,
            "status": r.status_code,
            "content_type": r.headers.get("content-type"),
            "bytes": len(r.content),
            "head_hex": r.content[:16].hex(),
            "history": [(x.status_code, x.url, x.headers.get("location")) for x in r.history],
        }
        if r.status_code == 200 and r.content.startswith(b"%PDF-"):
            path = OUTDIR / f"{label}.pdf"
            path.write_bytes(r.content)
            rec["pdf_path"] = str(path)
            print("FOUND PDF", json.dumps(rec, ensure_ascii=False), flush=True)
        else:
            _, text = decode(r)
            rec["text_head"] = re.sub(r"\s+", " ", text[:800])
            print("PROBE", json.dumps(rec, ensure_ascii=False), flush=True)
        return rec
    except Exception as exc:
        rec = {"label": label, "requested": url, "error": repr(exc)}
        print("PROBE ERROR", json.dumps(rec, ensure_ascii=False), flush=True)
        return rec


def analyse_page(name: str, url: str) -> dict:
    result: dict = {"name": name, "url": url, "links": [], "snippets": [], "probes": []}
    try:
        r = get(url)
        enc, text = decode(r)
        result.update({
            "resolved": r.url,
            "status": r.status_code,
            "content_type": r.headers.get("content-type"),
            "bytes": len(r.content),
            "encoding": enc,
        })
        (OUTDIR / f"{name}.html").write_text(text, encoding="utf-8")
        soup = BeautifulSoup(text, "html.parser")
        result["title"] = soup.title.get_text(" ", strip=True) if soup.title else ""
        print("PAGE", json.dumps({k: result[k] for k in result if k not in ("links", "snippets", "probes")}, ensure_ascii=False), flush=True)

        links: list[dict] = []
        for tag in soup.find_all(True):
            for attr in (
                "href", "src", "action", "data-url", "data-src", "data-file", "data-pdf",
                "data-download", "data-href", "data-link", "content", "value",
            ):
                value = tag.get(attr)
                if isinstance(value, str) and value.strip():
                    links.append({"tag": tag.name, "attr": attr, "raw": value.strip(), "url": urljoin(r.url, value.strip())})

        patterns = [
            r"(?:https?:)?//[^\s\"'<>\\]+",
            r"/(?:download|downloads|file|files|pdf|preview|api|document|doc|attachment|source|view|baogao|report)[^\s\"'<>\\]*",
        ]
        for pattern in patterns:
            for value in re.findall(pattern, text, flags=re.I):
                links.append({"tag": "regex", "attr": "text", "raw": value, "url": urljoin(r.url, value)})

        interesting = []
        seen = set()
        keys = (
            "pdf", "download", "file", "doc", "preview", "attachment", "source", "api",
            "4702606", "5642153", "250218", "稳定分红", "嘉里建设", "kerry",
        )
        for item in links:
            u = item["url"].rstrip("),]};'\"")
            if u in seen or len(u) > 900:
                continue
            seen.add(u)
            item["url"] = u
            hay = (u + " " + item["raw"]).lower()
            if any(str(k).lower() in hay for k in keys):
                interesting.append(item)
        result["links"] = interesting
        print("LINK COUNT", name, len(interesting), flush=True)
        for item in interesting[:250]:
            print("LINK", name, json.dumps(item, ensure_ascii=False), flush=True)

        snippets = []
        for m in re.finditer(
            r".{0,450}(?:pdf|download|fileUrl|file_url|docId|doc_id|preview|attachment|sourceUrl|source_url|oss|4702606|5642153|250218|稳定分红|嘉里建设).{0,1100}",
            text,
            flags=re.I | re.S,
        ):
            snippet = re.sub(r"\s+", " ", m.group(0))[:2200]
            if snippet not in snippets:
                snippets.append(snippet)
        result["snippets"] = snippets[:150]
        print("SNIPPET COUNT", name, len(snippets), flush=True)
        for snippet in snippets[:80]:
            print("SNIP", name, snippet, flush=True)

        for idx, item in enumerate(interesting[:160], 1):
            u = item["url"]
            low = u.lower()
            if u.startswith("javascript:") or any(x in low for x in (".css", ".js", "favicon", "logo", "icon", "image", ".png", ".jpg", ".svg")):
                continue
            result["probes"].append(probe_candidate(u, r.url, f"{name}_{idx:03d}"))
    except Exception as exc:
        result["error"] = repr(exc)
        print("PAGE ERROR", name, repr(exc), flush=True)
    return result


def main() -> None:
    results = {name: analyse_page(name, url) for name, url in PAGES.items()}
    Path("kerry-public-host-results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()

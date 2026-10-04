from __future__ import annotations

import json
from pathlib import Path

import requests

OUT = Path("out/fxbaogao_lanfeng_api")
OUT.mkdir(parents=True, exist_ok=True)

base = "https://api.fxbaogao.com"
session = requests.Session()
session.trust_env = False
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/152 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Origin": "https://www.fxbaogao.com",
    "Referer": "https://www.fxbaogao.com/",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
})

report_ids = [966932, 967723]
records = []


def save_response(label: str, response: requests.Response):
    safe = label.replace("/", "_").replace("?", "_").replace("&", "_").replace("=", "_")
    suffix = ".json" if "json" in (response.headers.get("content-type") or "").lower() else ".txt"
    path = OUT / f"{safe}{suffix}"
    path.write_bytes(response.content)
    try:
        parsed = response.json()
    except Exception:
        parsed = None
    records.append({
        "label": label,
        "status": response.status_code,
        "url": response.url,
        "content_type": response.headers.get("content-type"),
        "bytes": len(response.content),
        "headers": dict(response.headers),
        "json": parsed,
        "text_head": response.text[:3000],
        "saved": str(path),
    })
    print(label, response.status_code, response.url, response.headers.get("content-type"), len(response.content), response.text[:1000])

for rid in report_ids:
    calls = [
        ("GET", f"/mofoun/report/report/getReportPreviewImages?reportId={rid}", None, None),
        ("GET", f"/mofoun/report/searchReport/detail/catalog?reportId={rid}", None, None),
        ("GET", f"/mofoun/report/report/report/isDownload?reportIds={rid}", None, None),
        ("GET", f"/mofoun/report/report/report/preDownV2?reportId={rid}", None, None),
        ("GET", f"/mofoun/report/report/file/downloadReport?reportId={rid}", None, None),
        ("GET", f"/mofoun/report/report/downloadReportByBean?reportId={rid}", None, None),
        ("POST_JSON", "/mofoun/report/searchReport/detail", {"reportId": rid}, None),
        ("POST_JSON", "/mofoun/report/searchReport/detail", {"id": rid}, None),
        ("POST_JSON", "/mofoun/report/searchReport/detail", {"reportId": str(rid)}, None),
        ("POST_FORM", "/mofoun/report/searchReport/detail", None, {"reportId": rid}),
        ("POST_FORM", "/mofoun/report/searchReport/detail", None, {"id": rid}),
    ]
    for idx, (method, path, json_body, form_body) in enumerate(calls, 1):
        url = base + path
        label = f"{rid}_{idx:02d}_{method}_{path.rsplit('/',1)[-1]}"
        try:
            if method == "GET":
                response = session.get(url, timeout=(20, 120), allow_redirects=True)
            elif method == "POST_JSON":
                response = session.post(url, json=json_body, timeout=(20, 120), allow_redirects=True)
            else:
                response = session.post(url, data=form_body, timeout=(20, 120), allow_redirects=True)
            save_response(label, response)
        except Exception as exc:
            records.append({"label": label, "error": repr(exc)})
            print(label, "ERROR", repr(exc))

(OUT / "summary.json").write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")

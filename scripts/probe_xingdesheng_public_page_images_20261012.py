from __future__ import annotations

import json

import requests

S = requests.Session()
S.trust_env = False
H = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/155 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

BASES = {
    "4653227": "https://public.fxbaogao.com/report-image/2024/12/27/4653227-{}.png",
    "4274904": "https://public.fxbaogao.com/report-image/2024/03/05/4274904-{}.png",
}
PROBES = {
    "4653227": [1, 2, 3, 36, 37, 38, 39],
    "4274904": [1, 2, 3, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50],
}

for doc_id, pages in PROBES.items():
    results = []
    for page in pages:
        url = BASES[doc_id].format(page)
        try:
            response = S.get(
                url,
                headers={**H, "Referer": f"https://www.fxbaogao.com/view?id={doc_id}"},
                timeout=90,
                allow_redirects=True,
            )
            results.append({
                "page": page,
                "status": response.status_code,
                "content_type": response.headers.get("content-type"),
                "bytes": len(response.content),
                "head": response.content[:12].hex(),
                "final_url": response.url,
            })
        except Exception as exc:
            results.append({"page": page, "error": repr(exc)})
    print("PROBE", doc_id, json.dumps(results, ensure_ascii=False), flush=True)

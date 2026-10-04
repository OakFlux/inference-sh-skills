import json
import requests

session = requests.Session()
session.trust_env = False
session.headers.update({
    "User-Agent": "Mozilla/5.0",
    "Referer": "https://www.fxbaogao.com/",
    "Origin": "https://www.fxbaogao.com",
    "Accept": "application/json, text/plain, */*",
})

base = "https://api.fxbaogao.com"

calls = [
    ("GET", base + "/mofoun/report/report/getReportPreviewImages?reportId=1408531", None),
    ("POST", base + "/mofoun/report/searchReport/detail", {"reportId": 1408531}),
    ("POST", base + "/mofoun/report/searchReport/search", {
        "keywords": "之江生物",
        "pageIndex": 1,
        "pageSize": 50,
        "orderBy": 2,
        "filterYears": [],
        "filterStocks": [],
        "filterIndustries": [],
        "filterDoctype": [],
        "filterDatatype": [],
        "filterDate": [0, 0],
        "onlyTitle": False,
        "noParticiple": False,
    }),
]

for method, url, payload in calls:
    print("\nCALL", method, url, json.dumps(payload, ensure_ascii=False), flush=True)
    try:
        if method == "GET":
            response = session.get(url, timeout=90)
        else:
            response = session.post(url, json=payload, timeout=90)
        print("STATUS", response.status_code, response.headers.get("content-type"), len(response.content), flush=True)
        print(response.text[:30000], flush=True)
    except Exception as exc:
        print("ERROR", repr(exc), flush=True)

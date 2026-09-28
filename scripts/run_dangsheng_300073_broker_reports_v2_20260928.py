from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

BASE_SCRIPT = Path(__file__).with_name("build_dangsheng_300073_broker_reports_20260928.py")
spec = importlib.util.spec_from_file_location("dangsheng_base", BASE_SCRIPT)
if spec is None or spec.loader is None:
    raise RuntimeError(f"Unable to load base script: {BASE_SCRIPT}")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def choose_reports_v2(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for row in rows:
        info_code = str(row.get("infoCode") or "").strip()
        pages = module.parse_int(row.get("attachPages"))
        if not info_code or pages < 18:
            continue
        item = dict(row)
        item["_score"] = module.depth_score(item)
        item["_pages"] = pages
        item["_date"] = module.parse_date(item.get("publishDate"))
        candidates.append(item)

    candidates.sort(
        key=lambda item: (item["_score"], item["_date"], item["_pages"]),
        reverse=True,
    )
    print(
        "V2_CANDIDATES",
        json.dumps(
            [
                {
                    "title": item.get("title"),
                    "org": item.get("orgSName") or item.get("orgName"),
                    "date": str(item.get("publishDate")),
                    "pages": item.get("_pages"),
                    "score": item.get("_score"),
                    "infoCode": item.get("infoCode"),
                }
                for item in candidates[:30]
            ],
            ensure_ascii=False,
            indent=2,
        ),
        flush=True,
    )

    selected: list[dict[str, Any]] = []
    used_orgs: set[str] = set()

    # 先收入最新一份长篇首次覆盖报告，保证对固态材料与全球化布局的时效性。
    first_coverages = [
        item
        for item in candidates
        if "首次覆盖" in str(item.get("title") or "")
        and not any(
            token in str(item.get("title") or "")
            for token in ("点评", "季报", "年报", "半年报", "快报")
        )
    ]
    if first_coverages:
        latest_first = max(first_coverages, key=lambda item: item["_date"])
        selected.append(latest_first)
        used_orgs.add(str(latest_first.get("orgSName") or latest_first.get("orgName") or ""))

    # 其余选择评分最高的真正深度报告，且保持券商机构不同。
    for item in candidates:
        if item in selected:
            continue
        title = str(item.get("title") or "")
        org = str(item.get("orgSName") or item.get("orgName") or "")
        if org in used_orgs:
            continue
        if any(token in title for token in ("点评", "季报", "年报", "半年报", "一季报", "三季报", "快报")):
            continue
        if "深度" not in title and "首次覆盖" not in title and item["_pages"] < 24:
            continue
        selected.append(item)
        used_orgs.add(org)
        if len(selected) == 3:
            break

    if len(selected) < 3:
        for item in candidates:
            if item in selected:
                continue
            org = str(item.get("orgSName") or item.get("orgName") or "")
            if org in used_orgs:
                continue
            selected.append(item)
            used_orgs.add(org)
            if len(selected) == 3:
                break

    if len(selected) < 2:
        raise RuntimeError(f"Only {len(selected)} suitable broker reports found")

    print(
        "V2_SELECTED",
        json.dumps(
            [
                {
                    "title": item.get("title"),
                    "org": item.get("orgSName") or item.get("orgName"),
                    "date": str(item.get("publishDate")),
                    "pages": item.get("_pages"),
                    "infoCode": item.get("infoCode"),
                }
                for item in selected[:3]
            ],
            ensure_ascii=False,
            indent=2,
        ),
        flush=True,
    )
    return selected[:3]


module.choose_reports = choose_reports_v2
module.main()

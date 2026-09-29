from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

SOURCE = Path('scripts/build_zhongxin_saike_broker_reports_20260929.py')
spec = importlib.util.spec_from_file_location('zhongxin_saike_broker_builder', SOURCE)
if spec is None or spec.loader is None:
    raise RuntimeError('Unable to load Zhongxin Saike report builder')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

original_select = module.select_reports


def select_reports_v2(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected = list(original_select(records))
    institutions = {
        str(item.get('orgSName') or item.get('orgName') or '未知机构')
        for item in selected
    }
    selected_codes = {str(item.get('infoCode') or '') for item in selected}

    # Fill the third slot with the longest remaining complete company report.
    # This captures long-form coverage whose title does not explicitly contain
    # the words 深度 or 首次覆盖, while still excluding short earnings notes.
    remaining = [
        dict(item)
        for item in records
        if item.get('infoCode')
        and str(item.get('infoCode')) not in selected_codes
        and int(item.get('attachPages') or 0) >= 15
        and str(item.get('orgSName') or item.get('orgName') or '未知机构') not in institutions
    ]
    remaining.sort(
        key=lambda item: (
            int(item.get('attachPages') or 0),
            str(item.get('publishDate') or ''),
        ),
        reverse=True,
    )
    if remaining and len(selected) < 3:
        selected.append(remaining[0])
        print('SELECTED_LONGFORM_FILL', remaining[0], flush=True)

    if len(selected) != 3:
        raise RuntimeError(f'Expected exactly 3 suitable reports, found {len(selected)}')
    return selected


module.select_reports = select_reports_v2
module.main()

from __future__ import annotations

import importlib.util
import json
import time
from pathlib import Path
from typing import Any

import requests
from PIL import Image

BASE = Path(__file__).with_name("build_longban_broker_archive_targeted_20261004.py")
spec = importlib.util.spec_from_file_location("longban_base", BASE)
if spec is None or spec.loader is None:
    raise RuntimeError("Could not load base builder")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def fast_request(method: str, url: str, *, timeout: tuple[int, int] = (10, 75), **kwargs: Any) -> requests.Response:
    errors: list[str] = []
    headers = {**mod.SESSION.headers, **kwargs.pop("headers", {})}
    for attempt in range(1, 3):
        try:
            response = mod.SESSION.request(
                method,
                url,
                headers=headers,
                timeout=timeout,
                allow_redirects=True,
                **kwargs,
            )
            print(
                "HTTP_FAST", method, url, "attempt", attempt, "status", response.status_code,
                "type", response.headers.get("content-type"), "length", response.headers.get("content-length"),
                "final", response.url,
                flush=True,
            )
            response.raise_for_status()
            return response
        except Exception as exc:  # noqa: BLE001
            errors.append(repr(exc))
            if attempt < 2:
                time.sleep(2)
    raise RuntimeError(f"fast request failed for {url}: {errors}")


mod.request = fast_request


def download_image_fast(url: str, target: Path) -> dict[str, Any] | None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_suffix(target.suffix + ".part")
    temp.unlink(missing_ok=True)
    try:
        response = mod.SESSION.get(
            url,
            headers={**mod.SESSION.headers, "Referer": "https://www.sdyanbao.com/"},
            timeout=(10, 75),
            allow_redirects=True,
            stream=True,
        )
        print("IMAGE_HTTP", url, response.status_code, response.headers.get("content-type"), response.headers.get("content-length"), flush=True)
        if response.status_code != 200:
            response.close()
            return None
        with temp.open("wb") as handle:
            for chunk in response.iter_content(512 * 1024):
                if chunk:
                    handle.write(chunk)
        response.close()
        if temp.stat().st_size < 3000:
            temp.unlink(missing_ok=True)
            return None
        with Image.open(temp) as image:
            image.verify()
        with Image.open(temp) as image:
            width, height = image.size
            image_format = image.format or ""
        if width < 500 or height < 700:
            temp.unlink(missing_ok=True)
            return None
        temp.replace(target)
        return {"url": url, "bytes": target.stat().st_size, "width": width, "height": height, "format": image_format}
    except Exception as exc:  # noqa: BLE001
        print("IMAGE_FAST_ERROR", url, repr(exc), flush=True)
        temp.unlink(missing_ok=True)
        return None


def build_sdyanbao_pdf_fast(report: dict[str, Any], output: Path) -> dict[str, Any]:
    metadata = mod.parse_sdyanbao(report)
    expected_pages = metadata.get("expected_pages")
    upper_bound = int(expected_pages) if expected_pages else 40
    page_dir = mod.WORK_DIR / f"detail_{report['detail_id']}_v2"
    page_dir.mkdir(parents=True, exist_ok=True)
    image_paths: list[Path] = []
    image_records: list[dict[str, Any]] = []
    for index in range(upper_bound):
        path = page_dir / f"{index:03d}.png"
        url = f"{metadata['page_url'].rstrip('/')}/{index}.png"
        record = download_image_fast(url, path)
        if record is None:
            # Public site normally exposes a contiguous prefix of pages.
            break
        image_paths.append(path)
        image_records.append({"page_index": index, **record})
    if not image_paths:
        raise RuntimeError(f"No public pages available for report {report['detail_id']}")
    mod.images_to_pdf(image_paths, output)
    full = bool(expected_pages and len(image_paths) == int(expected_pages))
    result = {
        **metadata,
        "delivery_type": "公开逐页图片存档PDF" if full else "公开预览页存档PDF",
        "source_pdf_url": "",
        "archived_page_urls": image_records,
        "public_pages_archived": len(image_paths),
        "is_complete_against_declared_page_count": full,
    }
    print("PUBLIC_PAGE_ARCHIVE", json.dumps(result, ensure_ascii=False, indent=2), flush=True)
    return result


mod.build_sdyanbao_pdf = build_sdyanbao_pdf_fast
mod.main()

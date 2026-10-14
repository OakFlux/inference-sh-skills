from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import Any

from playwright.async_api import async_playwright, Response

OUT = Path("fx_solex_network_capture")
OUT.mkdir(exist_ok=True)
REPORT_IDS = [5201086, 4902712, 5085249, 5077383]


def safe_name(text: str, limit: int = 180) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", text)[-limit:]


async def main() -> None:
    all_runs: list[dict[str, Any]] = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={"width": 1440, "height": 1200},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/155 Safari/537.36"
            ),
            locale="zh-CN",
        )
        for rid in REPORT_IDS:
            rdir = OUT / str(rid)
            rdir.mkdir(exist_ok=True)
            page = await context.new_page()
            records: list[dict[str, Any]] = []
            request_records: list[dict[str, Any]] = []

            async def on_request(request):
                url = request.url
                if any(k in url.lower() for k in ["api", "mofoun", "report", "pdf", "document", "view", "image", "download"]):
                    request_records.append({
                        "method": request.method,
                        "url": url,
                        "resource_type": request.resource_type,
                        "post_data": request.post_data,
                        "headers": await request.all_headers(),
                    })
                    print("REQUEST", rid, request.method, request.resource_type, url, request.post_data or "", flush=True)

            async def on_response(response: Response):
                url = response.url
                try:
                    headers = await response.all_headers()
                except Exception:
                    headers = {}
                content_type = headers.get("content-type", "")
                interesting = any(k in url.lower() for k in ["api", "mofoun", "report", "pdf", "document", "view", "image", "download"])
                if not interesting and not any(k in content_type.lower() for k in ["json", "pdf"]):
                    return
                rec: dict[str, Any] = {
                    "url": url,
                    "status": response.status,
                    "content_type": content_type,
                    "headers": headers,
                }
                print("RESPONSE", rid, response.status, content_type, url, flush=True)
                try:
                    body = await response.body()
                    rec["bytes"] = len(body)
                    if len(body) <= 8_000_000:
                        if "json" in content_type.lower() or url.lower().endswith(".json"):
                            filename = f"response_{len(records):04d}_{safe_name(url)}.json"
                            (rdir / filename).write_bytes(body)
                            rec["saved_as"] = filename
                            try:
                                rec["json"] = json.loads(body.decode("utf-8", errors="replace"))
                            except Exception:
                                pass
                        elif "pdf" in content_type.lower() or body.startswith(b"%PDF-"):
                            filename = f"response_{len(records):04d}_{safe_name(url)}.pdf"
                            (rdir / filename).write_bytes(body)
                            rec["saved_as"] = filename
                        elif any(k in content_type.lower() for k in ["text", "javascript", "html", "xml"]):
                            filename = f"response_{len(records):04d}_{safe_name(url)}.txt"
                            (rdir / filename).write_bytes(body)
                            rec["saved_as"] = filename
                except Exception as exc:  # noqa: BLE001
                    rec["body_error"] = repr(exc)
                records.append(rec)

            page.on("request", on_request)
            page.on("response", on_response)
            page.on("console", lambda msg: print("CONSOLE", rid, msg.type, msg.text, flush=True))
            page.on("pageerror", lambda exc: print("PAGEERROR", rid, repr(exc), flush=True))

            url = f"https://www.fxbaogao.com/view?id={rid}"
            nav_error = ""
            try:
                response = await page.goto(url, wait_until="domcontentloaded", timeout=120_000)
                print("GOTO", rid, response.status if response else None, page.url, flush=True)
                await page.wait_for_timeout(15_000)
                # Scroll repeatedly so lazy-loaded pages and metadata requests fire.
                for _ in range(12):
                    await page.mouse.wheel(0, 1500)
                    await page.wait_for_timeout(1000)
                await page.wait_for_timeout(5_000)
            except Exception as exc:  # noqa: BLE001
                nav_error = repr(exc)
                print("NAV_ERROR", rid, nav_error, flush=True)

            html = await page.content()
            (rdir / "page.html").write_text(html, encoding="utf-8")
            await page.screenshot(path=str(rdir / "page.png"), full_page=True)
            try:
                storage = await page.evaluate("""() => ({
                    localStorage: {...localStorage},
                    sessionStorage: {...sessionStorage},
                    location: location.href,
                    title: document.title,
                    text: document.body ? document.body.innerText.slice(0, 20000) : ''
                })""")
            except Exception as exc:  # noqa: BLE001
                storage = {"error": repr(exc)}
            cookies = await context.cookies()
            run = {
                "report_id": rid,
                "initial_url": url,
                "final_url": page.url,
                "navigation_error": nav_error,
                "storage": storage,
                "cookies": cookies,
                "requests": request_records,
                "responses": records,
            }
            (rdir / "network.json").write_text(json.dumps(run, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
            all_runs.append(run)
            await page.close()
        await browser.close()
    (OUT / "all_network.json").write_text(json.dumps(all_runs, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(main())

from __future__ import annotations

import asyncio
import json

from playwright.async_api import async_playwright

REPORT_IDS = [4788440, 4438234, 4069371]


async def main() -> None:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={"width": 1440, "height": 1200},
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151 Safari/537.36"
            ),
            locale="zh-CN",
        )
        for report_id in REPORT_IDS:
            page = await context.new_page()
            network_urls: list[str] = []

            def record_response(response) -> None:
                lower = response.url.lower()
                if any(k in lower for k in ("report-image", "pdf", "report", "page", "view")):
                    network_urls.append(response.url)

            page.on("response", record_response)
            url = f"https://www.fxbaogao.com/view?id={report_id}"
            print("\n=== REPORT", report_id, url, "===")
            try:
                response = await page.goto(url, wait_until="domcontentloaded", timeout=120000)
                print("NAV STATUS", response.status if response else None, "FINAL", page.url)
                await page.wait_for_timeout(6000)
                for _ in range(30):
                    await page.mouse.wheel(0, 5000)
                    await page.wait_for_timeout(400)
                await page.evaluate("window.scrollTo(0, 0)")
                await page.wait_for_timeout(1500)
                data = await page.evaluate(
                    """
                    () => ({
                      title: document.title,
                      bodyText: document.body.innerText.slice(0, 16000),
                      images: Array.from(document.images).map(img => ({
                        src: img.currentSrc || img.src,
                        alt: img.alt,
                        width: img.naturalWidth,
                        height: img.naturalHeight,
                        display: getComputedStyle(img).display,
                      })),
                      canvases: Array.from(document.querySelectorAll('canvas')).map(c => ({
                        width: c.width, height: c.height,
                        rect: {x:c.getBoundingClientRect().x,y:c.getBoundingClientRect().y,width:c.getBoundingClientRect().width,height:c.getBoundingClientRect().height},
                      })),
                      iframes: Array.from(document.querySelectorAll('iframe')).map(f => f.src),
                      links: Array.from(document.querySelectorAll('a')).map(a => ({href:a.href,text:a.innerText})).filter(x => /download|下载|pdf|报告/.test((x.href+' '+x.text).toLowerCase())),
                      htmlLength: document.documentElement.outerHTML.length,
                      scrollHeight: document.documentElement.scrollHeight,
                    })
                    """
                )
                print(json.dumps(data, ensure_ascii=False, indent=2)[:160000])
                print("NETWORK URLS")
                for item in dict.fromkeys(network_urls):
                    print(item)
                screenshot = f"report_{report_id}_full.png"
                await page.screenshot(path=screenshot, full_page=True)
                print("SCREENSHOT", screenshot)
            except Exception as exc:
                print("ERROR", report_id, repr(exc))
            finally:
                await page.close()
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())

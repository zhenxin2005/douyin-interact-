#!/usr/bin/env python3
"""打开浏览器 → 手动登录 → 自动保存 cookies"""

import asyncio
from playwright.async_api import async_playwright


async def main():
    p = await async_playwright().start()
    browser = await p.chromium.launch(
        headless=False,
        args=["--disable-blink-features=AutomationControlled"],
    )
    context = await browser.new_context(
        viewport={"width": 1280, "height": 720},
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/125.0.0.0 Safari/537.36"
        ),
    )
    page = await context.new_page()
    await page.goto("https://www.douyin.com/", wait_until="domcontentloaded")

    print("=" * 60)
    print("  浏览器已打开 → https://www.douyin.com/")
    print("  请手动扫码或账号密码登录")
    print("  登录成功后回到这个终端按 Enter 键...")
    print("=" * 60)

    input()

    cookies = await context.cookies()
    cookie_str = "; ".join(f'{c["name"]}={c["value"]}' for c in cookies)

    with open("cookies.txt", "w", encoding="utf-8") as f:
        f.write(cookie_str)

    print(f"✅ 已保存 {len(cookies)} 个 cookies 到 cookies.txt")

    await browser.close()
    await p.stop()


if __name__ == "__main__":
    asyncio.run(main())

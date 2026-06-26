#!/usr/bin/env python3
"""
抖音直播间弹幕发送模块 — 基于 Playwright 模拟浏览器操作

链路:
   启动 Chromium → 加载 cookies 登录 → 打开直播间 → 定位输入框 → 发送弹幕

用法:
   作为模块导入:
       from douyin_chat import DouyinChat
       chat = await DouyinChat().start()
       await chat.open_room("https://live.douyin.com/123456789")
       await chat.send_message("1")
       await chat.close()

   独立测试:
       python douyin_chat.py <直播间URL或房间号>
"""

import asyncio
import logging
import re
import sys
import time
from pathlib import Path

# Windows 控制台 UTF-8 兼容
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from playwright.async_api import async_playwright

logger = logging.getLogger("douyin_chat")

# 需要设为 httpOnly 的 cookie 名称（安全相关）
_SECURITY_COOKIES = {
    "sessionid", "sessionid_ss", "sid_tt", "sid_guard",
    "uid_tt", "uid_tt_ss",
    "sid_ucp_v1", "ssid_ucp_v1",
    "passport_csrf_token", "passport_csrf_token_default",
    "passport_auth_mix_state", "passport_mfa_token",
}

# ── Cookie 解析 ──────────────────────────────────


def parse_cookie_string(cookie_str: str) -> list[dict]:
    """解析 document.cookie 格式 (name=val; name=val; ...) → Playwright cookie 列表"""
    cookies = []
    for pair in cookie_str.split(";"):
        pair = pair.strip()
        if not pair or "=" not in pair:
            continue
        name, _, value = pair.partition("=")
        name = name.strip()
        value = value.strip()
        # 去掉包裹引号
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
            value = value[1:-1]

        is_secure = (
            name in _SECURITY_COOKIES
            or "session" in name.lower()
            or "token" in name.lower()
            or "ticket" in name.lower()
        )
        cookies.append({
            "name": name,
            "value": value,
            "domain": ".douyin.com",
            "path": "/",
            "secure": is_secure,
            "httpOnly": name in _SECURITY_COOKIES,
            "sameSite": "Lax",
        })
    return cookies


def _load_cookies_from_file(path: str) -> list[dict]:
    """从文件读取并解析 cookie"""
    p = Path(path)
    if not p.exists():
        logger.warning(f"cookies 文件不存在: {path}")
        return []
    content = p.read_text(encoding="utf-8").strip()
    if not content:
        return []
    return parse_cookie_string(content)


# ── 主类 ─────────────────────────────────────────


class DouyinChat:
    """抖音直播间弹幕发送器

    Args:
        cookies_path: cookies.txt 路径（默认同目录下 cookies.txt）
        headless: 是否无头模式（默认 False，可见浏览器窗口方便调试）
    """

    def __init__(self, headless: bool = False):
        self.user_data_dir = str(Path(__file__).parent / "browser_data")
        self.headless = headless
        self._playwright = None
        self._context = None
        self._page = None
        self._ready = False

    async def start(self):
        """启动浏览器（使用持久化用户目录，登录态自动保存）"""
        self._playwright = await async_playwright().start()

        self._context = await self._playwright.chromium.launch_persistent_context(
            user_data_dir=self.user_data_dir,
            headless=self.headless,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-gpu",
            ],
            viewport={"width": 1280, "height": 720},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
        )

        # persistent context 自带初始页面
        self._page = self._context.pages[0] if self._context.pages else await self._context.new_page()
        self._page.on("console", lambda msg: logger.debug(f"[浏览器] {msg.text}"))

        logger.info(f"✅ 浏览器已启动 (user_data: {self.user_data_dir})")
        return self

    async def ensure_login(self, force: bool = False):
        """确保已登录

        使用持久化浏览器用户目录（browser_data/），
        登录态自动保存，下次启动自动恢复。

        Args:
            force: 强制重新扫码登录
        """
        # ── 验证已有登录态是否有效 ──
        if not force:
            logger.info("🔍 验证登录态...")
            await self._page.goto("https://www.douyin.com/",
                                  wait_until="domcontentloaded")
            try:
                await self._page.wait_for_load_state("networkidle", timeout=15000)
            except Exception:
                pass
            await asyncio.sleep(2)

            for _ in range(3):
                try:
                    cookies = await self._context.cookies()
                    has_session = any(c["name"] == "sessionid" for c in cookies)
                    if has_session:
                        logger.info("✅ 登录态有效，直接使用")
                        return True
                    break
                except Exception:
                    await asyncio.sleep(2)
                    continue

            logger.warning("⚠️ 登录态已过期，需重新登录")

        # ── 让用户扫码登录 ──
        logger.info("🔑 打开抖音登录页，请用手机抖音扫一扫登录")
        await self._page.goto("https://www.douyin.com/",
                              wait_until="domcontentloaded")

        print("\n" + "=" * 60)
        print("  📱 请在浏览器窗口中扫码登录抖音")
        print("  👀 登录成功后能看到右上角有你的头像")
        print("  ⏳ 然后回到这里等待检测...")
        print("=" * 60 + "\n")

        for i in range(180):  # 最多等 3 分钟
            await asyncio.sleep(1)
            try:
                cookies = await self._context.cookies()
                if any(c["name"] == "sessionid" for c in cookies):
                    # 登录态由浏览器用户目录自动持久化，无需手动保存
                    logger.info("✅ 登录成功！持久化用户目录已保存登录态")
                    print("\n✅ 检测到登录态，继续运行...\n")
                    return True
            except Exception:
                continue
            if i % 15 == 0 and i > 0:
                print(f"  ⏳ 等待登录... {i//15*15}秒")

        logger.warning("⚠️ 登录超时，将以游客身份运行（弹幕可能受限）")
        return False

    async def _save_cookies(self, cookies: list[dict] | None = None):
        """保存当前浏览器 cookies 到文件"""
        if cookies is None:
            cookies = await self._context.cookies()
        cookie_str = "; ".join(f'{c["name"]}={c["value"]}' for c in cookies)
        with open(self.cookies_path, "w", encoding="utf-8") as f:
            f.write(cookie_str)
        logger.info(f"💾 已保存 {len(cookies)} 个 cookies 到 {self.cookies_path}")

    async def open_room(self, room_url: str, timeout: int = 30) -> bool:
        """打开直播间页面，等待输入框就绪

        Returns:
            True 表示找到输入框（可以发送消息），False 表示页面可能未完全加载
        """
        if not self._page:
            raise RuntimeError("请先调用 start()")

        logger.info(f"打开直播间: {room_url}")
        await self._page.goto(room_url, wait_until="domcontentloaded",
                               timeout=timeout * 1000)
        # 等待页面渲染（直播流、弹幕组件等）
        await asyncio.sleep(5)

        # 尝试多种选择器定位输入框
        for sel in _INPUT_SELECTORS:
            try:
                await self._page.wait_for_selector(sel, timeout=3000)
                logger.info(f"✅ 直播间已加载，输入框: {sel}")
                self._ready = True
                return True
            except Exception:
                continue

        # 截图留档（加超时，防页面未加载完卡死）
        try:
            await self._page.screenshot(path="debug_room_load.png", timeout=5000)
        except Exception:
            pass
        logger.warning("⚠️ 未找到输入框，后续发送会重试查找")
        self._ready = True  # 仍标记就绪，send_message 会再试
        return False

    async def send_message(self, text: str) -> bool:
        """发送弹幕消息

        自动重试查找输入框，支持 input/textarea 和 contenteditable div。
        """
        if not self._page:
            logger.error("❌ 浏览器未启动")
            return False

        # 查找输入框
        input_elem = None
        for sel in _INPUT_SELECTORS:
            try:
                elem = await self._page.wait_for_selector(sel, state="attached",
                                                           timeout=2000)
                if elem and await elem.is_visible():
                    input_elem = elem
                    logger.info(f"找到输入框: {sel}")
                    break
            except Exception:
                continue

        if not input_elem:
            await self._page.screenshot(path="debug_no_input.png")
            logger.error("❌ 找不到输入框，截图已保存: debug_no_input.png")
            return False

        try:
            # 聚焦并清空
            await input_elem.click()
            await asyncio.sleep(0.3)

            tag = await input_elem.evaluate("el => el.tagName.toLowerCase()")
            if tag in ("input", "textarea"):
                await input_elem.fill("")
                await asyncio.sleep(0.2)
                await input_elem.fill(text)
            else:
                # contenteditable div
                await input_elem.evaluate("el => el.textContent = ''")
                await asyncio.sleep(0.2)
                await input_elem.type(text, delay=30)

            await asyncio.sleep(0.5)

            # Enter 发送
            await self._page.keyboard.press("Enter")
            logger.info(f"✅ 已发送: {text}")
            await asyncio.sleep(0.5)

            # 发送成功后截图留证
            await self._save_screenshot(text)
            return True

        except Exception as e:
            logger.error(f"❌ 发送失败: {e}")
            return False

    async def _save_screenshot(self, text: str):
        """发送成功后截图，保存到 screenshots/ 目录"""
        try:
            shot_dir = Path(__file__).parent / "screenshots"
            shot_dir.mkdir(exist_ok=True)
            ts = time.strftime("%Y%m%d_%H%M%S")
            safe_text = text.replace(" ", "_")[:20]
            path = str(shot_dir / f"send_{ts}_{safe_text}.png")
            await self._page.screenshot(path=path)
            logger.info(f"📸 截图已保存: {path}")
        except Exception as e:
            logger.warning(f"截图失败: {e}")

    async def close(self):
        """关闭浏览器，释放资源"""
        for target in ("_page", "_context", "_playwright"):
            obj = getattr(self, target, None)
            if obj is None:
                continue
            try:
                if hasattr(obj, "close"):
                    await obj.close()
                elif hasattr(obj, "stop"):
                    await obj.stop()
            except Exception as e:
                logger.warning(f"关闭 {target} 时出错: {e}")
            setattr(self, target, None)
        self._ready = False
        logger.info("🛑 浏览器已关闭")

    @property
    def is_ready(self) -> bool:
        return self._ready

    @property
    def page(self):
        return self._page


# ── 输入框选择器列表（按优先级排序） ──────────────

_INPUT_SELECTORS = [
    "input[placeholder*='说点什么']",
    "textarea[placeholder*='说点什么']",
    "[placeholder*='说点什么']",
    "[class*='chat-input'] input",
    "[class*='chat-input'] [contenteditable='true']",
    "[class*='webcast-input'] input",
    "[class*='webcast-input'] [contenteditable='true']",
    "[class*='chat_input']",
    "[class*='ChatInput']",
    "[class*='input-area']",
    "div[contenteditable='true']",
]


# ── 独立测试入口 ──────────────────────────────────


async def _test_main(room_id_or_url: str):
    """独立测试：打开直播间并发送一条 "1" """
    url = room_id_or_url
    if not url.startswith("http"):
        url = f"https://live.douyin.com/{room_id_or_url}"

    chat = DouyinChat(headless=False)
    try:
        await chat.start()
        await chat.open_room(url)
        print("\n⏳ 等待 3 秒后发送测试消息...")
        await asyncio.sleep(3)
        await chat.send_message("1111111")
        print("📤 已发送 '1'，5 秒后自动关闭")
        await asyncio.sleep(5)
    finally:
        await chat.close()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(message)s",
    )
    if len(sys.argv) < 2:
        print("用法: python douyin_chat.py <抖音直播间URL或房间号>")
        print("示例:")
        print("  python douyin_chat.py https://live.douyin.com/123456789")
        print("  python douyin_chat.py 123456789")
        sys.exit(1)
    asyncio.run(_test_main(sys.argv[1]))

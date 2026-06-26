#!/usr/bin/env python3
"""
弹幕采集器 — 挂直播间学习真人弹幕互动

用法:
    python danmaku_collector.py <直播间链接>

链接格式:
    https://live.douyin.com/房间号
    https://www.douyin.com/follow/live/房间号?anchor_id=xxx

采集的数据保存到 danmaku_data/ 目录，后续用于构建知识库。

依赖:
    pip install playwright httpx websockets python-dotenv
    playwright install chromium
"""

import asyncio
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

# ── 复用项目模块 ──
sys.path.insert(0, str(Path(__file__).parent))
from douyin_chat import DouyinChat


# ── 弹幕选择器（按优先级排序，抖音改版时容易失效，可自行补充） ──
_DANMAKU_SELECTORS = [
    # 主流：webcast-chat 容器
    "div[class*='webcast-chat'] div[class*='message']",
    "div[class*='webcast-chat'] div[class*='item']",
    "div[class*='webcast-chat'] p",
    # 备选：chat 容器
    "div[class*='chat'] div[class*='message']",
    "div[class*='chat'] div[class*='item']",
    "div[class*='chat'] p",
    # 通用兜底
    "div[class*='ChatMessage']",
    "div[class*='chat-message']",
    "div[class*='danmaku']",
    "div[class*='Danmaku']",
]


def extract_room_id(s: str) -> str:
    """从链接中提取房间号"""
    for p in [r"live\.douyin\.com/(\d+)", r"/live/(\d+)"]:
        m = re.search(p, s)
        if m:
            return m.group(1)
    if s.strip().isdigit():
        return s.strip()
    return "unknown"


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ── 采集器 ──

class DanmakuCollector:
    """弹幕采集器

    打开指定直播间，定时轮询弹幕元素，去重保存。
    """

    def __init__(self, room_url: str):
        self.room_url = room_url
        self.room_id = extract_room_id(room_url)
        self.chat: DouyinChat | None = None
        self.collected: list[dict] = []
        self.seen_texts: set[str] = set()
        self._running = False

        # 输出目录
        self.output_dir = Path(__file__).parent / "danmaku_data"
        self.output_dir.mkdir(exist_ok=True)

        # 输出文件名
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.output_file = self.output_dir / f"danmaku_{self.room_id}_{ts}.json"

    # ── 主流程 ──

    async def run(self):
        """启动采集"""
        self._running = True

        self._print_banner()

        # 1. 启动浏览器
        print("  🚀 启动浏览器...")
        self.chat = DouyinChat(headless=False)
        await self.chat.start()

        # 2. 确保已登录
        print("  🔑 检查登录态...")
        await self.chat.ensure_login()

        # 3. 打开直播间
        print(f"  📺 打开直播间...")
        await self.chat.open_room(self.room_url)

        # 短暂等待页面弹幕组件加载
        print("  ⏳ 等待弹幕组件加载...")
        await asyncio.sleep(5)

        print(f"\n{'=' * 60}")
        print(f"  📝 开始采集弹幕 — 按 Ctrl+C 停止")
        print(f"  保存路径: {self.output_file}")
        print(f"{'=' * 60}\n")

        # 4. 轮询采集
        empty_rounds = 0
        last_save_count = 0
        try:
            while self._running:
                items = await self._fetch_danmaku()
                new_count = 0

                for item in items:
                    text = item["text"]
                    if text not in self.seen_texts:
                        self.seen_texts.add(text)
                        self.collected.append(item)
                        new_count += 1
                        print(f"  [{len(self.collected):>4}] 💬 {text}")

                if new_count == 0:
                    empty_rounds += 1
                else:
                    empty_rounds = 0

                # 每采集到 20 条新弹幕自动保存一次（防意外丢失）
                if len(self.collected) - last_save_count >= 20:
                    self._save()
                    last_save_count = len(self.collected)
                    print(f"  💾 已自动保存 ({len(self.collected)} 条)")

                # 长时间没采集到弹幕时提示
                if empty_rounds == 30:   # 约 1 分钟无弹幕
                    print("  ⚠️ 暂未采集到弹幕，直播间可能未开播或弹幕组件未加载")
                elif empty_rounds == 90:  # 约 3 分钟
                    print("  ⚠️ 已 3 分钟无弹幕，尝试切换选择器策略...")
                    print("     如果直播间已开播，可能需要调试选择器")

                await asyncio.sleep(2)

        except KeyboardInterrupt:
            print("\n\n  ⏹ 用户中断采集")
        except Exception as e:
            print(f"\n\n  ⛔ 采集异常: {e}")
            import traceback
            traceback.print_exc()
        finally:
            self._running = False
            self._save()
            # 关闭浏览器（_save 是同步方法，close 放 finally 里 await）
            if self.chat:
                try:
                    await self.chat.close()
                except Exception:
                    pass

    # ── 噪音过滤 ──

    _NOISE_KEYWORDS = [
        "来了", "欢迎", "抖音严禁", "违法违规", "低俗色情",
        "理性消费", "私下交易", "谨防", "诈骗",
        "隐私政策", "用户服务协议", "营业执照", "站点地图",
        "广告投放", "账号找回", "加入我们", "友情链接",
        "下载抖音", "抖音电商", "充钻石", "客户端",
        "进入全屏", "网页全屏", "屏幕旋转",
        "直播已结束", "猜你喜欢", "前往直播频道",
        "我的喜欢", "我的收藏", "观看历史", "稍后再看",
        "我的作品", "我的预约", "我的订单", "退出登录",
        "本场点赞", "京ICP备", "京公网安备",
        "广播电视节目", "增值电信业务", "网络文化经营",
        "互联网宗教信息服务", "药品医疗器械",
        "互联网新闻信息服务", "网络谣言曝光台",
        "网上有害信息举报", "© 抖音", "2026",
    ]

    @staticmethod
    def _is_noise(text: str) -> bool:
        """判断是否为噪音弹幕（进场通知、系统提示、页面UI文字等）"""
        t = text.strip()
        if not t or len(t) <= 2:
            return True
        for kw in DanmakuCollector._NOISE_KEYWORDS:
            if kw in t:
                return True
        return False

    # ── 采集核心：从页面提取弹幕 ──

    async def _fetch_danmaku(self) -> list[dict]:
        """从页面提取当前弹幕列表

        使用多种选择器策略 + 噪音过滤，只保留真人互动弹幕。
        """
        if not self.chat or not self.chat.page:
            return []

        now = time.strftime("%H:%M:%S")
        ts = time.time()

        try:
            texts = await self.chat.page.evaluate("""
                () => {
                    const result = [];
                    const selectors = [
                        // 新版抖音弹幕（优先匹配聊天消息区域）
                        '[class*="webcast-chat"] [class*="message"]',
                        '[class*="webcast-chat"] [class*="item"]',
                        // 旧版/备用
                        '[class*="chat"] [class*="message"]',
                        '[class*="chat"] [class*="item"]',
                        '[class*="ChatMessage"]',
                        '[class*="chat-message"]',
                        '[class*="danmaku"]',
                        '[class*="Danmaku"]',
                    ];

                    for (const sel of selectors) {
                        const els = document.querySelectorAll(sel);
                        if (els.length > 0) {
                            for (const el of els) {
                                const t = el.textContent.trim();
                                if (t && t.length > 1 && t.length < 200) {
                                    result.push(t);
                                }
                            }
                            if (result.length > 0) break;
                        }
                    }

                    // 如果选择器都没命中，尝试暴力搜可见文本
                    if (result.length === 0) {
                        const allDivs = document.querySelectorAll('div, p, span');
                        for (const el of allDivs) {
                            if (!el.offsetParent) continue;
                            const t = el.textContent.trim();
                            if (t && t.length > 2 && t.length < 100) {
                                if (!t.includes('http')) {
                                    result.push(t);
                                }
                            }
                        }
                    }

                    return [...new Set(result)];
                }
            """)

            return [
                {"text": t, "time": now, "timestamp": ts}
                for t in texts
                if t and not self._is_noise(t)
            ]

        except Exception as e:
            print(f"  ⚠️ 采集异常: {e}")
            return []

    # ── 保存 ──

    def _save(self):
        """保存采集结果到 JSON"""
        data = {
            "room_url": self.room_url,
            "room_id": self.room_id,
            "collect_time": now_str(),
            "duration_seconds": self._running_duration(),
            "total_raw": len(self.collected),
            "total_unique": len(self.seen_texts),
            "danmaku": self.collected,
        }

        self.output_file.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        print(f"\n{'=' * 60}")
        print(f"  💾 采集完成")
        print(f"  📁 文件: {self.output_file}")
        print(f"  📊 总计: {len(self.collected)} 条弹幕（{len(self.seen_texts)} 条去重）")
        print(f"{'=' * 60}")

        # 展示弹幕前 10 条
        if self.collected:
            print(f"\n  📋 弹幕预览（前 10 条）:")
            for i, d in enumerate(self.collected[:10], 1):
                print(f"    {i}. 💬 {d['text']}")

        # 浏览器关闭已移到 run() 的 finally 块中处理

    def _running_duration(self) -> int:
        """粗略估算运行时长"""
        try:
            if self.collected:
                first = self.collected[0]["timestamp"]
                last = self.collected[-1]["timestamp"]
                return int(last - first)
        except Exception:
            pass
        return 0

    def _print_banner(self):
        print()
        print("=" * 60)
        print("  弹幕采集器 v1 — 学习真人弹幕互动")
        print("=" * 60)
        print(f"\n  直播间: {self.room_url}")
        print(f"  房间号: {self.room_id}")
        print()


# ── 启动入口 ──

async def main():
    if len(sys.argv) < 2:
        print("用法: python danmaku_collector.py <抖音直播间链接>")
        print("示例:")
        print("  python danmaku_collector.py https://live.douyin.com/123456789")
        print('  python danmaku_collector.py "https://www.douyin.com/follow/live/...?anchor_id=..."')
        sys.exit(1)

    room_url = sys.argv[1]
    collector = DanmakuCollector(room_url)
    await collector.run()


if __name__ == "__main__":
    asyncio.run(main())

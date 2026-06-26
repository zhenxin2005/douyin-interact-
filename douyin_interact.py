#!/usr/bin/env python3
"""
抖音直播间实时互动系统 — 火山引擎 ASR + LLM 智能决策 + 自动弹幕

链路:
  抖音直播流 → ffmpeg PCM → 火山 BigModel ASR → LLM 决策引擎 → 拟人化弹幕发送
                                                ↘ 关键词匹配（兜底）

用法:
  python douyin_interact.py <直播间URL或房间ID>

环境变量 (.env):
  VOLC_APP_ID        - 火山语音应用 APP ID
  VOLC_ACCESS_TOKEN  - Access Token
  VOLC_SECRET_KEY    - Secret Key
  VOLC_RESOURCE_ID   - 资源 ID (默认: volc.seedasr.sauc.duration)
  KEYWORDS           - 互动关键词，逗号分隔
  LLM_PROVIDER       - LLM provider (openai / ollama，默认 ollama)
  LLM_MODEL          - 模型名 (默认 deepseek-r1:7b)
  LLM_API_KEY        - API 密钥（openai 模式需要）
  LLM_BASE_URL       - API 地址
  OLLAMA_URL         - Ollama 地址 (默认 http://localhost:11434)
"""

import asyncio
import json
import os
import re
import struct
import subprocess
import sys
import time
import uuid
from pathlib import Path

# Windows 控制台 UTF-8 兼容
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

try:
    import httpx
except ImportError:
    sys.exit("pip install httpx")

try:
    import websockets
except ImportError:
    sys.exit("pip install websockets")

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env")
except ImportError:
    pass

# 弹幕发送模块（可选）
try:
    from douyin_chat import DouyinChat
    CHAT_AVAILABLE = True
except ImportError:
    CHAT_AVAILABLE = False
    DouyinChat = None

# LLM 智能决策引擎（可选）
try:
    from llm_engine import create_engine_from_env, LLMReplyGenerator
    LLM_AVAILABLE = True
except ImportError:
    LLM_AVAILABLE = False

# ── 配置 ──────────────────────────────────────────────

VOLC_APP_ID = os.getenv("VOLC_APP_ID", "")
VOLC_ACCESS_TOKEN = os.getenv("VOLC_ACCESS_TOKEN", "")
VOLC_RESOURCE_ID = os.getenv("VOLC_RESOURCE_ID", "volc.seedasr.sauc.duration")

WS_URL = "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel_nostream"

CHUNK_MS = 200
CHUNK_SIZE = 16000 * 2 * CHUNK_MS // 1000   # 6400 bytes

# 火山引擎 auto-assigns sequence: FullClientRequest=1, first audio=2
AUDIO_START_SEQ = 2

# ── 互动规则 ──────────────────────────────────
# 每条规则: (主播话术关键词列表, 自动回复内容)
# 从上到下匹配 ASR 识别文本，命中第一条就发送对应回复
DEFAULT_REPLY_RULES = [
    # 1) 初轮摸底憋单 — 引导扣1统计人数
    (["扣1","扣个1","打1","统一扣","全屏扣","没扣1","扣一波","统计人数","人够了才开","人够了"], "1111111"),

    # 2) 报尺码互动（服饰/鞋品） — 问L码能穿到多大
    (["尺码","穿的尺码","报尺码","穿什么码","多大码","预留库存","按大家报的尺码","M码","L码","XL码","S码","把尺码"], "L码能穿到多大"),

    # 3) 选颜色互动（多色款） — 喜欢哪个颜色直接打出来
    (["什么颜色","想要什么颜色","要什么颜色","喜欢什么颜色","选颜色","拍颜色","扣黑","扣白","经典色","统计色系","统计完色系"], "要白色"),

    # 4) 精准锁客互动 — 确定要带一单的扣确定
    (["确定","带一单","扣确定","锁库存","优先安排发货","优先锁库存","带一单回家","确定的家人"], "确定"),

    # 5) 最终集结 + 倒计时互动 — 还没报的抓紧补
    (["最后30秒","最后三十秒","准备就绪","倒计时开","还没报尺码","还没选颜色","抓紧补","倒数直接开","我倒数"], "L码能穿到多大"),

    # 6) 补单回流互动 — 没抢到的扣补货
    (["补货","加库存","没抢到","没赶上","申请加库存","呼声高","追加库存","没抢到的家人","没赶上的家人"], "补货"),

    # 7) 加急互动 — 主播说加急安排
    (["加急","加急安排","加急发","加急单","加急处理"], "加急"),

    # 9) 尾单清场互动 — 最后库存，纠结尺码颜色的赶紧打出来
    (["最后库存","最后少量","清完这波","直接下架","不再补单","清仓","尾单","纠结尺码","纠结颜色"], "L码能穿到多大"),

    # 10) 身高体重（直播通用）
    (["身高","体重","多重","多高","身高体重","报身高","报体重","多少斤","多少公斤","多胖","多瘦","三围"], "160 110"),

]

# 兼容 .env 中 KEYWORDS 配置（追加为兜底规则）
_env_kw = [k.strip() for k in os.getenv("KEYWORDS", "").split(",") if k.strip()]
if _env_kw:
    DEFAULT_REPLY_RULES.append((_env_kw, os.getenv("REPLY_TEXT", "1111111")))
REPLY_RULES = DEFAULT_REPLY_RULES

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/125.0.0.0 Safari/537.36"


# ── 火山引擎二进制协议 ──────────────────────────────

def make_header(msg_type: int, flags: int = 0, serial: int = 1, comp: int = 0) -> bytes:
    """4字节: [proto=1|hdr_sz=1] [msg|flags] [serial|comp] [reserved]"""
    return struct.pack("BBBB",
        (1 << 4) | 1,          # byte 0
        (msg_type << 4) | flags,  # byte 1
        (serial << 4) | comp,     # byte 2
        0,                        # byte 3
    )


def pack(header: bytes, payload: bytes, seq: int | None = None) -> bytes:
    """Header + [Sequence 4B] + PayloadSize 4B + Payload"""
    buf = bytearray(header)
    if seq is not None:
        buf.extend(struct.pack(">i", seq))
    buf.extend(struct.pack(">I", len(payload)))
    buf.extend(payload)
    return bytes(buf)


def full_client_request() -> bytes:
    params = {
        "user": {"uid": "douyin_interact"},
        "audio": {"format": "pcm", "rate": 16000, "bits": 16, "channel": 1, "codec": "raw", "language": "zh-CN"},
        "request": {
            "model_name": "bigmodel",
            "enable_itn": True,
            "enable_punc": True,
            "result_type": "single",
        },
    }
    return pack(make_header(1, flags=0, serial=1), json.dumps(params).encode())


def audio_frame(audio: bytes, seq: int, last: bool = False) -> bytes:
    """Audio Only: msg_type=2, flags=1(positive seq), audio payload"""
    flags = 0x03 if last else 0x01  # 0x03 = negative seq (end)
    seq_val = -(seq) if last else seq
    return pack(make_header(2, flags, 0), audio, seq_val)


def parse_response(data: bytes):
    """解析服务器响应 — 跳过可能的前导非JSON字节"""
    if len(data) < 8:
        return None
    try:
        payload = data[8:]
        start = payload.find(b"{")
        if start < 0:
            return None
        obj = json.loads(payload[start:].decode())
        if "error" in obj:
            return obj
        return obj
    except Exception:
        return None


# ── 直播流 ────────────────────────────────────────

def extract_room_id(s: str) -> str:
    for p in [r"live\.douyin\.com/(\d+)", r"/live/(\d+)"]:
        m = re.search(p, s)
        if m:
            return m.group(1)
    if s.strip().isdigit():
        return s.strip()
    raise ValueError(f"无法解析: {s}")


def get_stream(room_id: str) -> dict:
    url = f"https://live.douyin.com/{room_id}"
    h = {"User-Agent": UA, "Referer": "https://live.douyin.com/"}
    with httpx.Client(headers=h, follow_redirects=True, timeout=30) as c:
        resp = c.get(url)
        resp.raise_for_status()
        html = resp.text.replace("\\u0026", "&")

    flv = re.findall(r'(https?://[^"\s<>]+\.douyincdn\.com[^"\s<>]*\.flv[^"\s<>]*)', html)
    anchor = re.search(r'"nickname"\s*:\s*"([^"]*)"', html)
    status = re.search(r'"status"\s*:\s*(\d+)', html)
    if status and int(status.group(1)) == 4:
        return {}
    if not flv:
        return {}

    def rank(u):
        if "_or4" in u: return 10
        if "_hd" in u: return 7
        return 1

    return {
        "url": max(flv, key=rank),
        "anchor": anchor.group(1) if anchor else "?",
        "live": True,
    }


def ffmpeg_audio(url: str) -> subprocess.Popen:
    return subprocess.Popen([
        "ffmpeg", "-hide_banner", "-loglevel", "error",
        "-user_agent", UA,
        "-headers", "Referer: https://live.douyin.com/\r\n",
        "-rw_timeout", "30000000", "-reconnect", "1", "-reconnect_streamed", "1",
        "-i", url, "-vn", "-ac", "1", "-ar", "16000", "-sample_fmt", "s16",
        "-f", "s16le", "-",
    ], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)


# ── 主逻辑 ────────────────────────────────────────

MAX_RETRIES = 11  # 首次尝试 + 最多 10 次重连后退出

async def run(room_id: str):
    print("=" * 50)
    print("  抖音互动 PoC — 火山(豆包) ASR  (自动重连版)")
    print("=" * 50)

    # 0. 初始化弹幕模块（只做一次，跨重连复用）
    chat = None
    if CHAT_AVAILABLE:
        try:
            chat = DouyinChat(headless=False)
            await chat.start()

            # 自动处理登录：先尝试已有 cookies，失效则打开页面让用户扫码
            await chat.ensure_login()

            room_url = f"https://live.douyin.com/{room_id}"
            await chat.open_room(room_url)
            if chat.is_ready:
                print("  ✅ 弹幕模块已就绪")
            else:
                print("  ⚠️ 弹幕模块已启动（输入框未确认，运行中会重试）")
        except Exception as e:
            print(f"  ⚠️ 弹幕模块初始化失败: {e}")
            print("     ASR 仍会运行，但不会自动发送弹幕")
            chat = None
    else:
        print("  ⚠️ 弹幕模块未安装 (需 pip install playwright)")

    # 0.5 初始化 LLM 决策引擎（只做一次，跨重连复用）
    llm_engine = None
    if LLM_AVAILABLE:
        try:
            llm_engine = create_engine_from_env()
            if llm_engine.is_available:
                print(f"  ✅ LLM 决策引擎已就绪: {llm_engine.provider_name}/{llm_engine.model}")
            else:
                print(f"  ⚠️ LLM 引擎未就绪（API 未配置），将使用关键词兜底")
        except Exception as e:
            print(f"  ⚠️ LLM 引擎初始化失败: {e}")
            print("     将使用传统关键词匹配")
            llm_engine = None
    else:
        print("  ⚠️ LLM 引擎模块未找到，使用传统关键词匹配")

    retry = 0
    while retry < MAX_RETRIES:
        retry += 1
        if retry > 1:
            print(f"\n🔁 第 {retry} 次重连 ({time.strftime('%H:%M:%S')})...")
            await asyncio.sleep(3)

        try:
            await _run_once(room_id, chat, llm_engine)
        except websockets.ConnectionClosed as e:
            print(f"\n  ⚠️ WebSocket 断开: {e}")
            print(f"  等待 5 秒后重连...")
            await asyncio.sleep(5)
            continue
        except (OSError, ConnectionError, asyncio.TimeoutError) as e:
            print(f"\n  ⚠️ 网络异常: {e}")
            print(f"  等待 8 秒后重连...")
            await asyncio.sleep(8)
            continue
        except Exception as e:
            # 非预期异常：打印堆栈然后重试
            import traceback
            traceback.print_exc()
            print(f"\n  ⚠️ 未知错误: {e}")
            print(f"  等待 10 秒后重连...")
            await asyncio.sleep(10)
            continue

    print(f"\n  ⛔ 已达最大重连次数 ({MAX_RETRIES - 1} 次)，程序退出")
    if chat:
        await chat.close()


async def _run_once(room_id: str, chat, llm_engine=None):
    """单次运行会话（含一次完整的 WebSocket 连接）"""
    # 1. 获取流
    info = get_stream(room_id)
    if not info or not info.get("live"):
        print("  ❌ 未开播，30 秒后重试...")
        await asyncio.sleep(30)
        raise ConnectionError("未开播")
    print(f"\n  主播: {info['anchor']}  |  流: {info['url'][:50]}...")

    # 2. 启动 ffmpeg
    ff = ffmpeg_audio(info["url"])
    await asyncio.sleep(1.5)
    if ff.poll() is not None:
        print("  ❌ ffmpeg 失败")
        ff.terminate()
        raise OSError("ffmpeg 启动失败")
    print("  ✅ 音频就绪")

    # 3. 连接火山引擎
    headers = {
        "X-Api-App-Key": VOLC_APP_ID,
        "X-Api-Access-Key": VOLC_ACCESS_TOKEN,
        "X-Api-Resource-Id": VOLC_RESOURCE_ID,
        "X-Api-Request-Id": str(uuid.uuid4()),
        "X-Api-Connect-Id": str(uuid.uuid4()),
    }
    ws = await asyncio.wait_for(
        websockets.connect(WS_URL, additional_headers=headers, max_size=2**24),
        timeout=15,
    )
    print("  ✅ 火山 ASR 已连接")

    # 4. 发送 Full Client Request
    await ws.send(full_client_request())

    # 5. 等待第一条结果
    print("  等待第一条响应...")
    first = await asyncio.wait_for(ws.recv(), timeout=10)
    r = parse_response(first)
    if r:
        lid = r.get("result", {}).get("additions", {}).get("log_id", "")
        msg = r.get("error", "")
        if msg:
            print(f"  ⚠️ 服务器错误: {msg[:200]}")
            ff.terminate()
            await ws.close()
            raise ConnectionError(f"ASR 服务器错误: {msg[:200]}")
        print(f"  ✅ 服务器就绪 (log_id={lid[:16]}...)")

    # 6. 后台读取器 + LLM 决策 + 弹幕发送
    last_text = ""
    last_send_time = 0.0
    SEND_COOLDOWN = 6.0

    async def reader():
        nonlocal last_text, last_send_time
        try:
            async for raw in ws:
                r = parse_response(raw)
                if not r:
                    continue
                if r.get("error"):
                    print(f"\n  ⚠️ {r['error'][:200]}")
                    continue
                txt = r.get("result", {}).get("text", "")
                if not txt:
                    utts = r.get("result", {}).get("utterances", [])
                    txt = utts[-1].get("text", "") if utts else ""
                if txt and txt != last_text:
                    last_text = txt
                    print(f"\r  🎤 {txt}", end="", flush=True)

                    # ── LLM 决策 / 关键词兜底 ──
                    reply = None
                    source = ""

                    # 优先 LLM 引擎
                    if llm_engine and llm_engine.is_available:
                        reply = await llm_engine.generate(txt)
                        if reply:
                            source = "LLM"
                            print(f"\n  🧠 [LLM] → {reply}")

                    # LLM 未生成 → 关键词兜底
                    if not reply:
                        matched_keywords = []
                        matched_reply = None
                        for keywords, rule_reply in REPLY_RULES:
                            found = [kw for kw in keywords if kw in txt]
                            if found:
                                matched_keywords = found
                                matched_reply = rule_reply
                                break
                        if matched_keywords:
                            reply = matched_reply
                            source = f"关键词: {', '.join(matched_keywords)}"

                    # ── 发送弹幕 ──
                    if reply:
                        now = time.time()
                        if chat and now - last_send_time >= SEND_COOLDOWN:
                            last_send_time = now
                            print(f"\n  🎯 [{source}] → {reply}")
                            try:
                                await chat.send_message(reply)
                            except Exception as e:
                                print(f"  ⚠️ 弹幕发送异常: {e}")
                        else:
                            print(f"\n  🎯 [{source}] → {reply} (冷却中)")
        except websockets.ConnectionClosed:
            pass

    rtask = asyncio.create_task(reader())

    # 7. 主循环：读取 ffmpeg stdout → 发送 WebSocket
    seq = AUDIO_START_SEQ - 1
    total = 0
    ts = time.time()
    print(f"\n🔊 开始 (Ctrl+C 停止)...\n")

    try:
        loop = asyncio.get_event_loop()
        while ff.poll() is None:
            chunk = await loop.run_in_executor(None, ff.stdout.read, CHUNK_SIZE)
            if not chunk:
                break
            seq += 1
            await ws.send(audio_frame(chunk, seq))
            total += len(chunk)
            await asyncio.sleep(CHUNK_MS / 1000.0)

        if ws.state == websockets.protocol.State.OPEN:
            await ws.send(audio_frame(b"", seq + 1, last=True))
    except websockets.ConnectionClosed:
        raise  # 让上层重连逻辑处理
    except KeyboardInterrupt:
        return
    finally:
        elapsed = time.time() - ts
        print(f"\n  时长: {elapsed:.0f}s  |  音频: {total/1024:.0f}KB  |  包: {seq}")
        rtask.cancel()
        try:
            await rtask
        except asyncio.CancelledError:
            pass
        await ws.close()
        ff.terminate()
        try:
            ff.wait(timeout=5)
        except subprocess.TimeoutExpired:
            ff.kill()
        print("  已停止\n")


def main():
    if not VOLC_APP_ID or not VOLC_ACCESS_TOKEN:
        print("❌ 请在 .env 中设置 VOLC_APP_ID 和 VOLC_ACCESS_TOKEN")
        sys.exit(1)

    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True, check=True)
    except Exception:
        print("❌ 未找到 ffmpeg")
        sys.exit(1)

    room = sys.argv[1] if len(sys.argv) > 1 else os.getenv("DOUYIN_ROOM_URL", "")
    if not room:
        print("用法: python douyin_interact.py <直播间URL>")
        sys.exit(1)

    asyncio.run(run(extract_room_id(room)))


if __name__ == "__main__":
    main()

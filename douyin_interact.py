#!/usr/bin/env python3
"""
抖音直播间实时互动 PoC — 火山引擎（豆包语音）大模型 ASR 版本

链路:
  抖音直播流 → ffmpeg 提取 PCM 音频 → 火山 BigModel ASR → 实时文本 → 关键词匹配

用法:
  python douyin_interact.py <直播间URL或房间ID>

环境变量 (.env):
  VOLC_APP_ID        - 火山语音应用 APP ID
  VOLC_ACCESS_TOKEN  - Access Token
  VOLC_SECRET_KEY    - Secret Key
  VOLC_RESOURCE_ID   - 资源 ID (默认: volc.seedasr.sauc.duration)
  KEYWORDS           - 互动关键词，逗号分隔
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

# ── 配置 ──────────────────────────────────────────────

VOLC_APP_ID = os.getenv("VOLC_APP_ID", "")
VOLC_ACCESS_TOKEN = os.getenv("VOLC_ACCESS_TOKEN", "")
VOLC_RESOURCE_ID = os.getenv("VOLC_RESOURCE_ID", "volc.seedasr.sauc.duration")

WS_URL = "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel_nostream"

CHUNK_MS = 200
CHUNK_SIZE = 16000 * 2 * CHUNK_MS // 1000   # 6400 bytes

# 火山引擎 auto-assigns sequence: FullClientRequest=1, first audio=2
AUDIO_START_SEQ = 2

DEFAULT_KW = ["扣1","扣个1","打1","打一波1","点点赞","点个赞","点赞","关注","点关注","点点关注","打想要","觉得好","觉得好的","评论区","公屏"]
_keywords_env = os.getenv("KEYWORDS", "")
KEYWORDS = [k.strip() for k in _keywords_env.split(",") if k.strip()] if _keywords_env else DEFAULT_KW

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

async def run(room_id: str):
    print("=" * 50)
    print("  抖音互动 PoC — 火山(豆包) ASR")
    print("=" * 50)

    # 1. 获取流
    info = get_stream(room_id)
    if not info or not info.get("live"):
        print("  ❌ 未开播")
        return
    print(f"\n  主播: {info['anchor']}  |  流: {info['url'][:50]}...")

    # 2. 启动 ffmpeg
    ff = ffmpeg_audio(info["url"])
    await asyncio.sleep(1.5)
    if ff.poll() is not None:
        print("  ❌ ffmpeg 失败")
        return
    print("  ✅ 音频就绪")

    # 3. 连接火山引擎
    headers = {
        "X-Api-App-Key": VOLC_APP_ID,
        "X-Api-Access-Key": VOLC_ACCESS_TOKEN,
        "X-Api-Resource-Id": VOLC_RESOURCE_ID,
        "X-Api-Request-Id": str(uuid.uuid4()),
        "X-Api-Connect-Id": str(uuid.uuid4()),
    }
    try:
        ws = await asyncio.wait_for(
            websockets.connect(WS_URL, additional_headers=headers, max_size=2**24),
            timeout=15,
        )
    except Exception as e:
        print(f"  ❌ 连接失败: {e}")
        ff.terminate()
        return
    print("  ✅ 火山 ASR 已连接")

    # 4. 发送 Full Client Request
    await ws.send(full_client_request())

    # 5. 等待第一条结果再开始发音频
    print("  等待第一条响应...")
    try:
        first = await asyncio.wait_for(ws.recv(), timeout=10)
        r = parse_response(first)
        if r:
            lid = r.get("result", {}).get("additions", {}).get("log_id", "")
            msg = r.get("error", "")
            if msg:
                print(f"  ⚠️ 服务器错误: {msg[:200]}")
                ff.terminate()
                await ws.close()
                return
            print(f"  ✅ 服务器就绪 (log_id={lid[:16]}...)")
    except asyncio.TimeoutError:
        print("  ⚠️ 服务器响应超时")
        ff.terminate()
        await ws.close()
        return

    # 6. 后台读后续结果
    last_text = ""
    async def reader():
        nonlocal last_text
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
                    hits = [kw for kw in KEYWORDS if kw in txt]
                    if hits:
                        print(f"\n  🎯 命中: {', '.join(hits)} → 触发互动(TODO)")
        except websockets.ConnectionClosed:
            pass

    rtask = asyncio.create_task(reader())

    # 6. 主循环
    seq = AUDIO_START_SEQ - 1  # Full Client Request = 1 (seq=-1即-1), audio 从 2 开始
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

        # 最后一包
        if ws.state == websockets.protocol.State.OPEN:
            await ws.send(audio_frame(b"", seq + 1, last=True))
    except KeyboardInterrupt:
        pass
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

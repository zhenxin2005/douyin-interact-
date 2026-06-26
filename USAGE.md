# 抖音直播互动系统 — 独立运行指南

## 概述

实时监听抖音直播间主播口播语音，转成文字，通过 **DeepSeek AI** 智能理解主播话术并自动发送弹幕互动。

```
主播说 → 火山 ASR → DeepSeek LLM → 6种角色轮换 → 自动弹幕
```

## 环境要求（已装好）

| 依赖 | 版本 |
|------|------|
| Python | 3.11+ ✅ |
| ffmpeg | 8.1+ ✅ |
| httpx | 0.28+ ✅ |
| websockets | 15+ ✅ |
| python-dotenv | 1.0+ ✅ |
| playwright | 1.60+ ✅ |

## 文件结构

```
C:\Users\zhenx\douyin-interact\
├── douyin_interact.py    ← 主程序（ASR + LLM 决策 + 弹幕发送）
├── douyin_chat.py        ← 弹幕发送模块
├── llm_engine.py         ← LLM 智能决策引擎（DeepSeek + 6角色轮换）
├── relogin.py            ← 扫码重新登录工具
├── .env                  ← 所有配置（火山 ASR + DeepSeek LLM + 角色配置）
├── cookies.txt           ← 抖音登录 cookies（可选）
├── requirements.txt      ← Python 依赖
├── README.md             ← 项目说明
├── USAGE.md              ← 本文件
└── screenshots/          ← 弹幕发送截图存档
```

## 快速启动

```powershell
cd C:\Users\zhenx\douyin-interact
python douyin_interact.py https://live.douyin.com/128070195914
```

把链接换成你要进的直播间就行。

## 配置说明

编辑 `.env` 文件，目前配置已就绪：

```ini
# ── 火山引擎 ASR（语音识别） ── 已配好，不用动
VOLC_APP_ID=9481950477
VOLC_ACCESS_TOKEN=xxx
VOLC_RESOURCE_ID=volc.seedasr.sauc.duration

# ── DeepSeek LLM（智能决策） ── 已配好，不用动
LLM_PROVIDER=openai
LLM_MODEL=deepseek-chat
LLM_API_KEY=sk-xxxxxxxx           # CodeWhale 的 Key
LLM_BASE_URL=https://api.deepseek.com

# ── 消费者角色轮换（可选调整） ──
PERSONA_ROTATE_INTERVAL=300       # 角色切换间隔（秒）
```

### 可调参数

```ini
# 想换模型 → 改 LLM_MODEL
LLM_MODEL=deepseek-chat            # DeepSeek V3
# LLM_MODEL=deepseek-reasoner      # DeepSeek R1（深度思考）

# 想改角色切换速度 → 改 PERSONA_ROTATE_INTERVAL
PERSONA_ROTATE_INTERVAL=300        # 5分钟
# PERSONA_ROTATE_INTERVAL=60      # 1分钟（测试用）
# PERSONA_ROTATE_INTERVAL=600     # 10分钟（更稳定）
```

## 运行效果

```
==================================================
  抖音互动 PoC — 火山(豆包) ASR
==================================================

  ✅ LLM 引擎已就绪: provider=openai, model=deepseek-chat
  🎭 初始角色: 精打细算姐
  ✅ 弹幕模块已就绪
  ✅ 音频就绪  |  ✅ 火山 ASR 已连接  |  ✅ 服务器就绪

🔊 开始 (Ctrl+C 停止)...

  🎤 扣1统计人数，我看有多少人
  🧠 [LLM] [精打细算姐] → 1111

  🎤 这件衣服有三个颜色，你们要什么颜色
  🧠 [LLM] [精打细算姐] → 白色好看吗 会不会不耐脏

  ... 5 分钟后自动切换角色 ...

  🔄 角色切换 → 捧场热心肠

  🎤 最后一波库存了，没抢到可惜
  🧠 [LLM] [捧场热心肠] → 等等我啊刚在看码数😭
```

## LLM 决策引擎说明

本系统使用 **DeepSeek API**（通过 CodeWhale 环境中的 API Key）来替代传统的关键词匹配。

### 6 种消费者角色（每 5 分钟轮换）

| 角色 | 说话风格 |
|------|---------|
| 🏃 **爽快下单姐** | 话少直接，看中就拍 |
| 💰 **精打细算姐** | 爱砍价，爱比价 |
| 🤔 **纠结犹豫妹** | 选择困难，反复问细节 |
| 🔍 **品质挑剔姐** | 注重质量，问题犀利 |
| 🎉 **捧场热心肠** | 开朗爱互动，活跃气氛 |
| 🐣 **新手小白** | 刚来直播间，需要指导 |

### 兜底机制

如果 DeepSeek API 不可用（网络问题或 Key 失效），会自动降级到内置的 9 条关键词匹配规则，系统不会中断。

## 停止运行

按 **`Ctrl + C`** 即可停止。程序会自动关闭浏览器和 ffmpeg。

## 断连自动重连

程序内置自动重连机制，不需要手动干预：

- WebSocket 断开 → 5 秒后自动重连
- 网络异常 → 8 秒后自动重连
- 直播间未开播 → 30 秒后自动重试
- 无限重试，直到你按 Ctrl+C

## 常见问题

### Q: 提示 "❌ 未开播"

直播间还没开播，程序会每隔 30 秒自动重试检测，开播后自动连上。

### Q: 弹幕发不出去

需要登录态。在 `cookies.txt` 里放抖音的 cookies。获取方式：
1. 浏览器打开抖音并登录
2. F12 → Console → 输入 `document.cookie`
3. 把输出的内容复制到 `cookies.txt`

### Q: 我想换直播间

直接 Ctrl+C 停掉，重新运行新的链接：

```powershell
python douyin_interact.py https://live.douyin.com/新房间号
```

### Q: LLM 回复太慢了

DeepSeek API 通常 1-2 秒内返回。如果感觉慢：
1. 检查网络连接
2. 可以在 `.env` 换用更快的模型（如 `deepseek-chat` 已是最快）
3. 仍然会通过关键词兜底正常运作

### Q: ffmpeg 报错

确保 ffmpeg 在 PATH 中：

```powershell
ffmpeg -version
```

如果找不到，重新安装 ffmpeg 或重启终端。

---

> 代码会自动重连，跑上就不用管了。想换直播间就 Ctrl+C 停掉重开。

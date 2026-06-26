# 抖音直播间实时互动系统

**火山 ASR（语音识别）+ DeepSeek LLM（智能决策）+ 6 种消费者角色轮换 + 自动弹幕**

```
主播说 → ffmpeg 音频采集 → 火山 ASR → DeepSeek LLM → 角色轮换 → Playwright 自动弹幕
```

---

## 快速启动

```powershell
cd C:\Users\zhenx\douyin-interact
pip install -r requirements.txt
python douyin_interact.py https://live.douyin.com/房间号
```

把链接换成你要进的直播间，按 **`Ctrl+C`** 停止。

---

## 核心能力

### 1️⃣ 实时语音识别
火山引擎 ASR（BigModel）通过 WebSocket 实时接收主播语音，转成文字。支持 `live.douyin.com` 和 `douyin.com` 两种链接格式。

### 2️⃣ AI 智能决策（DeepSeek LLM）
用 DeepSeek API 理解主播话术，自动生成贴合上下文的弹幕回复。内置上下文记忆（最近 3 轮主播话术），回复不重样。API 不可用时自动降级到关键词兜底。

### 3️⃣ 6 种消费者角色轮换
每 5 分钟自动切换一种消费者性格（可配置），话术风格丰富不重样：

| 角色 | 说话风格 | 示例回复 |
|------|---------|---------|
| 🏃 **爽快下单姐** | 话少直接，看中就拍 | "要一件" |
| 💰 **精打细算姐** | 爱砍价，爱比价 | "白色好看吗 会不会不耐脏" |
| 🤔 **纠结犹豫妹** | 选择困难，反复问细节 | "L 码能穿到多大" |
| 🔍 **品质挑剔姐** | 注重质量，问题犀利 | "面料起球吗" |
| 🎉 **捧场热心肠** | 开朗爱互动，活跃气氛 | "等等我啊刚在看码数😭" |
| 🐣 **新手小白** | 刚来直播间，需要指导 | "怎么买呀" |

### 4️⃣ 弹幕自动发送
Playwright Chromium 浏览器自动化，加载 cookies 登录态后自动在直播间输入框发送弹幕。发送成功自动截图留证（保存至 `screenshots/` 目录）。

### 5️⃣ 关键词兜底
LLM 不可用时（网络问题或 Key 失效），自动降级到内置关键词匹配规则（扣1、报尺码、选颜色等），系统不中断。

### 6️⃣ 自动重连 + 退出保护

| 故障场景 | 行为 |
|---------|------|
| WebSocket 断开 | 等待 5 秒后重连 |
| 网络异常 | 等待 8 秒后重连 |
| 未开播 / 下播 | 等待 30 秒后重试 |
| 未知错误 | 等待 10 秒后重连 |
| **重连超过 10 次仍失败** | **⛔ 程序自动退出** |

> 程序最多尝试 **首次连接 + 10 次重连**，全部失败后自动退出，不会无限重连。

---

## 文件结构

```
douyin-interact/
├── douyin_interact.py    ← 主程序（ASR + LLM + 弹幕）
├── douyin_chat.py        ← 弹幕发送模块（Playwright）
├── llm_engine.py         ← LLM 引擎（DeepSeek + 角色轮换）
├── relogin.py            ← 扫码重新登录工具
├── .env                  ← 配置（火山 ASR + DeepSeek Key + 角色参数）
├── .env.example          ← 配置模板
├── cookies.txt           ← 抖音登录 cookies（可选）
├── requirements.txt      ← Python 依赖
├── README.md             ← 本文件
├── USAGE.md              ← 详细使用指南
├── DEVELOPMENT.md        ← 开发进度
└── screenshots/          ← 弹幕发送截图存档
```

---

## 配置说明

编辑 `.env` 文件，火山 ASR 和 DeepSeek Key 已配好，通常不需要动：

```ini
# ── 火山引擎 ASR（已配好，不用动） ──
VOLC_APP_ID=9481950477
VOLC_ACCESS_TOKEN=xxx
VOLC_RESOURCE_ID=volc.seedasr.sauc.duration

# ── DeepSeek LLM（已配好，不用动） ──
LLM_PROVIDER=openai
LLM_MODEL=deepseek-chat
LLM_API_KEY=sk-xxxxxxxx
LLM_BASE_URL=https://api.deepseek.com

# ── 角色切换间隔 ──
PERSONA_ROTATE_INTERVAL=300    # 秒，默认 5 分钟
```

**可调参数：**

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `LLM_MODEL` | 模型选择 | `deepseek-chat`（V3，最快） |
| | 可选：`deepseek-reasoner` | R1 深度思考，慢一点 |
| `PERSONA_ROTATE_INTERVAL` | 角色切换间隔 | `300`（5 分钟） |
| | 测试用：`60`（1 分钟快切） | |

---

## 使用技巧

**首次运行：**
1. 确保 `ffmpeg` 在 PATH 中 —— `ffmpeg -version` 确认
2. 准备抖音登录态：浏览器登录抖音 → F12 → Console → 输入 `document.cookie` → 复制到 `cookies.txt`
3. 运行 `python douyin_interact.py https://live.douyin.com/房间号`

**换直播间：** Ctrl+C 停掉，重新运行新链接即可。

**重新登录：** 运行 `python relogin.py` 扫码获取新的 cookies。

---

## 常见问题

**Q: 提示 "❌ 未开播"**
直播间还没开播，程序会自动重试。重试 10 次仍不开播则自动退出。

**Q: 弹幕发不出去**
检查 `cookies.txt` 是否有有效登录态，或运行 `relogin.py` 重新扫码获取。

**Q: LLM 回复太慢**
通常 1-2 秒返回。如果慢检查网络，或保持 `deepseek-chat`（已是最快模型）。LLM 不可用时自动走关键词兜底。

**Q: ffmpeg 报错**
确保 ffmpeg 在 PATH 中，安装后重启终端。

**Q: 程序一直在重连怎么办**
如果直播间已下播或链接失效，程序会在 10 次重连后自动退出，不会无限跑下去。

---

## 架构

```
┌──────────────┐    ┌──────────────────┐    ┌────────────────┐
│  抖音直播间    │───▶│  火山 ASR        │───▶│  DeepSeek LLM │
│  FLV 直播流   │    │  BigModel 语音识别│    │  智能决策引擎  │
└──────────────┘    └──────────────────┘    └───────┬────────┘
                                                     │
                                                     ▼
                                           ┌──────────────────┐
                                           │  消费者角色轮换    │
                                           │  6种性格自动切换   │
                                           └───────┬──────────┘
                                                     │
                                                     ▼
                                           ┌──────────────────┐
                                           │  Playwright 弹幕  │
                                           │  浏览器自动化发送  │
                                           └──────────────────┘
```

## 许可证

仅供学习研究使用。

# 抖音直播间实时互动系统 — 开发进度

## 📋 项目概述

**火山引擎 ASR（语音识别）+ DeepSeek LLM（智能决策）+ 拟人化弹幕发送** 的抖音直播间自动互动系统。

```
主播说话
    │
    ▼
ffmpeg 音频采集 (PCM 16kHz 单声道)
    │
    ▼
火山引擎 BigModel ASR ← WebSocket 实时语音识别
    │
    ▼
┌─ LLM 智能决策引擎 ─────────────────────┐
│  DeepSeek API (openai 兼容协议)         │
│  6 种消费者角色 · 每 5 分钟自动轮换     │
│  关键词兜底 (9 条内置规则)              │
└─────────────────────────────────────────┘
    │
    ▼
Playwright 浏览器自动化 → 拟人化弹幕发送
```

---

## ✅ 已完成

### 第一阶段：基础架构（ASR 链路）

- [x] 直播流获取（支持 `live.douyin.com` 和 `www.douyin.com/follow/live/`）
- [x] ffmpeg 音频采集（PCM 16kHz 单声道，stdout pipe）
- [x] 火山引擎 BigModel ASR WebSocket 连接
- [x] ASR 实时语音转文字
- [x] 火山引擎二进制协议封装（header/pack/parse）
- [x] WebSocket 断线自动重连（5/8/10 秒阶梯重试，无限重试）
- [x] 直播间未开播自动检测（30 秒轮询）

### 第二阶段：关键词匹配

- [x] 实时文本关键词匹配引擎
- [x] 分层匹配规则（按优先级顺序匹配第一条）
- [x] 6 秒弹幕发送冷却机制
- [x] 发送重复文本去重（`last_text` 防重）

#### 内置兜底规则（9 条）

| # | 场景 | 触发关键词 | 自动回复 |
|---|------|-----------|---------|
| 1 | 扣1憋单 | 扣1, 统一扣, 全屏扣, 统计人数... | 1111111 |
| 2 | 报尺码 | 尺码, 多大码, 预留库存... | L 码能穿到多大 |
| 3 | 选颜色 | 什么颜色, 扣黑, 扣白, 经典色... | 要白色 |
| 4 | 锁客 | 确定, 带一单, 扣确定... | 确定 |
| 5 | 倒计时 | 最后30秒, 还没报抓紧补... | L 码能穿到多大 |
| 6 | 补货 | 补货, 没抢到, 加库存... | 补货 |
| 7 | 尾单 | 最后库存, 下架, 清仓... | L 码能穿到多大 |
| 8 | 身高体重 | 身高, 体重, 多少斤... | 160 110 |
| 9 | `.env` 自定义 | `KEYWORDS` 中定义 | `REPLY_TEXT` |

### 第三阶段：弹幕发送

- [x] Playwright Chromium 浏览器自动化
- [x] cookies.txt 登录态加载（支持 60+ cookie 字段）
- [x] 直播间页面打开与输入框自动定位（优先级排序 11 种选择器）
- [x] 弹幕文本输入与 Enter 发送（支持 `input` / `textarea` / `contenteditable div`）
- [x] 发送成功自动截图留证（保存至 `screenshots/` 目录）
- [x] 发送失败截图调试（`debug_no_input.png` / `debug_room_load.png`）
- [x] Windows 控制台 UTF-8 编码兼容

### 第四阶段：互动规则配置

- [x] 9 层关键词→回复映射规则（含 `.env` 自定义扩展）
- [x] 规则覆盖常见主播互动话术（扣1、尺码、颜色、锁客、补货、加急等）
- [x] `.env` 文件统一的配置管理

### 第五阶段：LLM 智能决策引擎

- [x] `LLMReplyGenerator` 类设计（多 provider 架构）
- [x] OpenAI 兼容 API 接入（DeepSeek / 豆包 / 百炼 / OpenAI）
- [x] Ollama 本地模型接入（DeepSeek、Qwen 等）
- [x] LLM 不可用时的关键词兜底机制
- [x] ASR 主程序中的 LLM 引擎集成（`douyin_interact.py`）
- [x] `.env` 配置（`LLM_PROVIDER` / `LLM_MODEL` / `LLM_API_KEY` 等）
- [x] 上下文记忆（最近 3 轮主播话术辅助决策）
- [x] 重复回复过滤（与最近一条不同才发送）
- [x] Provider 工厂模式设计（易于扩展新 provider）
- [x] 消费者角色库（6 种不同消费者性格）
- [x] 角色每 5 分钟自动轮换（`PERSONA_ROTATE_INTERVAL` 可配置）
- [x] 启动时随机选择初始角色

### 测试验证

- [x] Playwright 弹幕模块独立测试（`python douyin_chat.py <URL>`）
- [x] ASR + 弹幕全链路集成测试
- [x] 弹幕发送截图验证（命中→发送→截图一条龙）
- [x] LLM 引擎独立测试（`python llm_engine.py`）

### 第六阶段：LLM 优化（2026-06-17）

- [x] Temperature 0.9 → 0.6（降低回复随机性，避免过度发散）
- [x] "品质挑剔姐"人设重写（去掉面料成分/质检报告等专业话题）
- [x] BASE_SYSTEM_PROMPT 新增"禁止行为"规则
- [x] 新增 3 条常见场景示例（引导 LLM 往正确方向）

### 第七阶段：弹幕采集与知识库（2026-06-17）

- [x] `danmaku_collector.py` — 独立弹幕采集器
- [x] 基于 DouyinChat 打开直播间，轮询采集弹幕
- [x] 噪音过滤（"xxx 来了"进场通知、页面UI文字、系统提示）
- [x] 自动保存（每 20 条存一次，防意外丢失）
- [x] UTF-8 编码兼容（Windows GBK 问题修复）

### 第八阶段：登录态持久化改进（2026-06-17）

- [x] 从手动的 `cookies.txt` / `storage.json` 方案迁移到 `launch_persistent_context`
- [x] 使用浏览器用户目录 `browser_data/` 自动保存完整登录态
- [x] `ensure_login()` 简化：检测 `sessionid` cookie 即可，不依赖 DOM 检查
- [x] 移除 `storage.json` 手动保存/加载逻辑
- [x] 首次扫码后，后续启动不再需要登录

### 其他修复（2026-06-17）

- [x] `douyin_interact.py` — 重连次数上限 999 → 11，达到上限自动退出
- [x] `README.md` — 重写为完整使用说明文档

---

## 🔄 P0 — 高优先级（进行中）

### 1️⃣ 拟人化发送引擎

洛曦参考：模拟真人打字速度和行为，避免被平台识别为机器人。

| 维度 | 方案 | 改哪里 |
|------|------|--------|
| 逐字输入 | `page.keyboard.type(text, delay=random(30, 120))` 替代 `fill()` | `douyin_chat.py` → `send_message()` |
| 输入前停顿 | `sleep(random.uniform(0.5, 2.0))` 模拟看弹幕再反应 | 同上 |
| 发送间隔抖动 | 冷却时间 `6 + random.gauss(0, 1.5)` 秒 | `douyin_interact.py` → `SEND_COOLDOWN` |
| 偶尔"打错"重打 | 5% 概率先输入错误字符再删除重打 | `douyin_chat.py` |

- [ ] 拟人化逐字输入（替代 `fill` 方式）
- [ ] 发送前后随机停顿
- [ ] 偶尔"打错字"重打机制
- [ ] 冷却时间随机抖动

### 2️⃣ 熔断保护（动态频率控制）

洛曦参考：智能控制发送频率，防止触发平台限制。

| 场景 | 策略 |
|------|------|
| 弹幕稀疏（<5条/分） | 冷却缩短到 4-6s |
| 弹幕密集（>30条/分） | 冷却拉长到 15-30s |
| 刚发过相似内容 | 额外 +3s 冷却 |
| 检测到主播催互动 | 临时降低冷却到 3s |
| 连续发送超 N 条 | 强制暂停 30s |

- [ ] 自适应冷却计算函数
- [ ] 历史发送记录追踪
- [ ] 平台压力感知（根据直播间弹幕密度）
- [ ] 连续发送阈值与强制暂停

### 3️⃣ 回复内容轮换池

避免同一条规则永远回复一模一样的内容。

- [ ] 同一规则下多条回复随机轮换
- [ ] 尺码随机: L / M / XL
- [ ] 颜色随机: 要白色 / 要黑色 / 经典色
- [ ] 互动语随机池

---

## 🟡 P1 — 中优先级（待实现）

### 4️⃣ ~~LLM 智能回复引擎~~ ✅ 已完成

> 已实现为独立模块 `llm_engine.py`，详情见上方 **第五阶段**。

支持的模型：
- **云端**: DeepSeek API（当前使用）, 豆包, 百炼, OpenAI (openai provider)
- **本地**: DeepSeek (Ollama), Qwen (ollama provider)

### 5️⃣ 弹幕监听模块（可选开关）

不需要回复公屏弹幕，但保留代码通过配置开关选择性开启。

**配置开关**（`.env`）：
```ini
# 弹幕监听开关（默认关闭）
DANMAKU_LISTENER_ENABLED=false

# 仅开启时生效的规则
DANMAKU_KEYWORDS=多少钱,怎么买,有货吗
DANMAKU_REPLY=私信你了哦
```

**代码设计**：
- `DanmakuListener` 类放在 `douyin_chat.py`，默认不 import
- `douyin_interact.py` 中通过 `DANMAKU_ENABLED` 环境变量控制是否启动
- 关闭时零开销、零资源占用
- 开启时异步轮询弹幕元素，命中关键词后调用 `send_message()`

- [ ] `.env` 开关配置
- [ ] `DanmakuListener` 类实现
- [ ] 条件 import + 条件启动
- [ ] 关闭时完全零开销

### 6️⃣ 发送失败重试与账户健康监测

- [ ] 网络波动时自动重试发送
- [ ] 输入框选择器自动更新（抖音前端改版时 fallback）
- [ ] Cookie 有效性检测与失效告警
- [ ] 账号风控检测与自动暂停

---

## 🔵 P2 — 低优先级（远期规划）

### 7️⃣ 多平台支持

洛曦参考：支持 B站、抖音、快手、视频号，一套系统多平台运营。

```
PlatformAdapter (抽象接口)
├── DouyinAdapter    (已有)
├── BilibiliAdapter  (待实现)
├── KuaishouAdapter  (待实现)
└── WeChatAdapter    (待实现)
```

- [ ] `PlatformAdapter` 抽象基类
- [ ] 各平台输入框选择器配置
- [ ] 各平台弹幕发送协议适配
- [ ] 平台特定的反检测策略

### 8️⃣ 多开管理

洛曦参考：同时操作多个直播间，一台电脑多平台运行。

- [ ] 多账号配置管理（多个 cookies.txt）
- [ ] 账号池轮换机制
- [ ] 多直播间并发管理（asyncio.gather）
- [ ] IP 代理支持（不同账号不同出口 IP）

### 9️⃣ 监控与运维

- [ ] Web 管理面板（实时查看 ASR 内容 / 匹配日志 / 发送状态）
- [ ] 规则热加载（不重启更新关键词和回复）
- [ ] 数据统计（关键词命中率 / 弹幕发送量 / 在线时长）
- [ ] 持久化日志
- [ ] 异常告警（ASR 断开 / 浏览器崩溃 / 账号异常）

---

## 🗺️ 版本路线图

| 版本 | 目标 | 状态 |
|------|------|------|
| **v0.1** | 基础 ASR + 关键词匹配 + Playwright 发送 | ✅ 已完成 |
| **v0.2** | 拟人化发送 + 熔断保护 + 回复轮换 | 🔄 进行中 |
| **v0.3** | LLM 决策引擎 + 角色轮换 + 弹幕监听可选 | ✅ LLM+角色已完成 / 弹幕监听待实现 |
| **v0.31** | LLM 优化 + 弹幕采集器 + 登录态持久化 | ✅ 2026-06-17 |
| **v0.4** | 规则热加载 + 数据看板 + 多账号 | 📅 规划中 |
| **v1.0** | 多平台支持 + 多开管理 + Web 面板 | 📅 远期 |

---

## 📁 项目文件结构

```
douyin-interact/
│
├── douyin_interact.py    # 主程序：ASR + LLM 决策 + 弹幕发送
├── douyin_chat.py        # 弹幕发送模块：Playwright 浏览器自动化
├── llm_engine.py         # LLM 智能决策引擎（DeepSeek / 6 角色轮换）
├── danmaku_collector.py  # 弹幕采集器（真人弹幕学习）
├── relogin.py            # 扫码重新登录工具
│
├── .env                  # 环境配置（火山 ASR + DeepSeek LLM + 角色配置）
├── .env.example          # 配置模板（含所有可选项）
├── requirements.txt      # Python 依赖
├── README.md             # 使用说明
├── USAGE.md              # 独立运行指南
├── DEVELOPMENT.md        # 开发进度（本文档）
│
├── browser_data/         # 浏览器持久化用户目录（登录态自动保存）
├── danmaku_data/         # 弹幕采集数据存档
├── screenshots/          # 弹幕发送截图存档
├── debug_no_input.png    # 输入框未找到调试截图
└── debug_room_load.png   # 直播间加载异常调试截图
```

---

## 🏗️ 核心模块架构

### LLM 决策引擎（`llm_engine.py`）

```
LLMReplyGenerator
│
├── OpenAIProvider         # DeepSeek API (当前使用)
│   ├── deepseek-chat      #   走 https://api.deepseek.com
│   ├── 豆包 (volces.com)
│   ├── 百炼 (aliyun.com)
│   └── OpenAI (openai.com)
│
├── OllamaProvider         # 本地 Ollama 部署
│   ├── deepseek-r1:7b
│   └── qwen2.5:7b/3b
│
├── 消费者角色轮换系统      # 6 种性格，每 5 分钟切换
│   ├── 🏃 爽快下单姐
│   ├── 💰 精打细算姐
│   ├── 🤔 纠结犹豫妹
│   ├── 🔍 品质挑剔姐
│   ├── 🎉 捧场热心肠
│   └── 🐣 新手小白
│
└── FALLBACK_RULES         # 关键词兜底（9 条内置规则）
    ├── 扣1 → 1111111
    ├── 尺码 → L 码能穿到多大
    ├── 颜色 → 要白色
    └── ...
```

### 决策优先级

```
ASR 识别文本
    │
    ├── 1️⃣ LLM 引擎可用？
    │      ├── ✅  → DeepSeek 生成回复（带上当前角色）
    │      └── ❌  → 降级到关键词匹配
    │
    ├── 2️⃣ 关键词命中？
    │      ├── ✅  → 发送兜底回复
    │      └── ❌  → 本轮不回复
    │
    └── 3️⃣ 冷却检查
           ├── 冷却中 → 跳过
           └── 已冷却 → 发送弹幕
```

---

## 🔗 数据流

```
[抖音直播间]                    [本机]
                ┌─ ffmpeg ─→ PCM 音频 ─→ 火山 ASR ─→ 文本
  直播流 ───────┤                                        │
                └─ Playwright ─→ 浏览器页面 ←─── 弹幕发送 ─┤
                                                            │
                                              ┌─────────────┘
                                              ▼
                                     DeepSeek API (openai)
                                              │
                                         角色轮换系统
                                              │
                                         生成自然回复
```

---

> 最后更新：2026-06-17
> 当前阶段：**v0.31 已完成**（LLM 优化 / 弹幕采集器 / 登录态持久化）
> 下一阶段：**v0.2 P0** 拟人化发送 / 熔断保护 / 回复轮换

#!/usr/bin/env python3
"""
LLM 智能决策引擎 — 让 AI 自动理解主播话术并生成自然回复

洛曦参考：支持豆包/百炼/OpenAI 等多种 AI 模型，智能生成回复内容。

链路:
    ASR 识别文本 → LLM 判断场景 → 生成自然回复 → 发送弹幕

支持的 Provider:
    - openai:    OpenAI / 豆包 / 百炼 / DeepSeek 等兼容 API
    - ollama:    本地 Ollama 部署（DeepSeek、Qwen 等）

用法:
    from llm_engine import LLMReplyGenerator
    engine = LLMReplyGenerator(provider="ollama", model="deepseek-r1:7b")
    reply = await engine.generate("主播说：扣1统计人数")
"""

import asyncio
import json
import logging
import os
import sys
from pathlib import Path

# Windows 控制台 UTF-8 兼容
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env")
except ImportError:
    pass

logger = logging.getLogger("llm_engine")


# ── 内置回复规则（LLM 不可用时的兜底） ──────────────

FALLBACK_RULES = [
    (["扣1","扣个1","打1","统一扣","全屏扣","没扣1","扣一波","统计人数","人够了才开","人够了"], "1111111"),
    (["尺码","穿的尺码","报尺码","穿什么码","多大码","预留库存","按大家报的尺码","M码","L码","XL码","S码","把尺码"], "L码能穿到多大"),
    (["什么颜色","想要什么颜色","要什么颜色","喜欢什么颜色","选颜色","拍颜色","扣黑","扣白","经典色","统计色系","统计完色系"], "要白色"),
    (["确定","带一单","扣确定","锁库存","优先安排发货","优先锁库存","带一单回家","确定的家人"], "确定"),
    (["最后30秒","最后三十秒","准备就绪","倒计时开","还没报尺码","还没选颜色","抓紧补","倒数直接开","我倒数"], "L码能穿到多大"),
    (["补货","加库存","没抢到","没赶上","申请加库存","呼声高","追加库存","没抢到的家人","没赶上的家人"], "补货"),
    (["加急","加急安排","加急发","加急单","加急处理"], "加急"),
    (["最后库存","最后少量","清完这波","直接下架","不再补单","清仓","尾单","纠结尺码","纠结颜色"], "L码能穿到多大"),
    (["身高","体重","多重","多高","身高体重","报身高","报体重","多少斤","多少公斤","多胖","多瘦","三围"], "160 110"),
]


# ── 消费者角色库（每 5 分钟自动轮换） ──────────────

PERSONAS = [
    {
        "name": "爽快下单姐",
        "tone": "话少直接，看中就拍，不墨迹",
        "trait": "对价格不太敏感，看重眼缘",
        "style": "回复简短，一般不超过10个字，很少提问",
    },
    {
        "name": "精打细算姐",
        "tone": "注重性价比，爱砍价，爱比价",
        "trait": "对价格、优惠券、包邮门槛特别敏感",
        "style": "喜欢问价格、要优惠、凑满减",
    },
    {
        "name": "纠结犹豫妹",
        "tone": "想买但又顾虑多，反复问细节",
        "trait": "尺码颜色选择困难，担心买错",
        "style": "喜欢报身高体重问尺码、问材质、问退换货",
    },
    {
        "name": "品质挑剔姐",
        "tone": "注重款式和上身效果，眼光挑剔",
        "trait": "关注颜色好不好看、显不显瘦、好不好搭配",
        "style": "会问显胖吗、容不容易皱、透不透、好不好搭配",
    },
    {
        "name": "捧场热心肠",
        "tone": "性格开朗，爱互动，爱夸主播",
        "trait": "活跃气氛，带动节奏",
        "style": "积极扣屏、夸主播、说好看、帮主播喊价",
    },
    {
        "name": "新手小白",
        "tone": "刚来直播间，啥都不懂，问题比较多",
        "trait": "第一次买这类商品，需要详细指导",
        "style": "问得很基础：怎么买、多大码、什么时候发货",
    },
]

# 角色轮换间隔（秒）
PERSONA_ROTATE_INTERVAL = 300  # 5 分钟


# ── Provider 基类 ──────────────────────────────────

# ── 基础 Prompt 模板（所有角色共用） ──────────────

BASE_SYSTEM_PROMPT = """你是一个正在逛直播间的消费者。根据主播说的话，像真人在弹幕里互动。

## 通用规则
1. 回复要**简短自然**（5-25个字），口语化
2. 只输出弹幕内容本身，不要解释，不要加引号
3. 遇到主播引导互动时积极响应
4. 已经问过的问题不要再重复问
5. 多互动捧场，少问深究性技术问题

## 禁止行为（必须遵守）
- ❌ 不要问产品质量、面料成分、材料密度、质检报告等专业/技术问题
- ❌ 不要发表过于尖锐或质疑主播的言论
- ❌ 不要问"面料成分""材质""密度""缩水率"等类似问题
- ✅ 可以问「显胖吗」「好搭配吗」「容不容易皱」「透不透」「什么颜色好看」

## 当前你的角色
{persona_description}

## 常见场景参考
主播说"扣1统计人数"       → 1111
主播说"尺码怎么选"        → 主播我160 110斤穿什么码
主播说"想要什么颜色"      → 白色好看吗 会不会不耐脏
主播说"确定带一单的扣确定"  → 确定
主播说"没抢到的扣补货"    → 补货补货 没抢到啊
主播说"点点赞"            → 1111 赞了
主播说"这个价格划算吧"    → 还能再便宜点吗 包邮不
主播说"质量放心"          → 有没有买过的姐妹说说 好搭配吗
主播说"最后10单"          → 等等我 还在犹豫码数
主播说"这件好看吗"        → 好看 白色显白吗
主播说"显瘦"              → 会显胖吗 我肚子大能穿吗"""


# ── Provider 基类 ──────────────────────────────────

class BaseProvider:
    """LLM Provider 抽象基类"""
    
    async def generate(self, prompt: str, system_prompt: str | None = None) -> str:
        raise NotImplementedError


class OpenAIProvider(BaseProvider):
    """OpenAI 兼容 API（适配 OpenAI / 豆包 / 百炼 / DeepSeek）"""
    
    def __init__(self, api_key: str, base_url: str, model: str):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
    
    async def generate(self, prompt: str, system_prompt: str | None = None) -> str:
        import httpx
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt or ""},
                {"role": "user", "content": f"主播说：{prompt}"},
            ],
            "temperature": 0.6,
            "max_tokens": 80,
        }
        
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers=headers,
                    json=payload,
                )
                resp.raise_for_status()
                data = resp.json()
                reply = data["choices"][0]["message"]["content"].strip()
                reply = reply.strip("\"'「」")
                return reply
        except Exception as e:
            logger.warning(f"OpenAI API 请求失败: {e}")
            return ""


class OllamaProvider(BaseProvider):
    """本地 Ollama 部署（DeepSeek、Qwen 等）"""
    
    def __init__(self, base_url: str, model: str):
        self.base_url = base_url.rstrip("/")
        self.model = model
    
    async def generate(self, prompt: str, system_prompt: str | None = None) -> str:
        import httpx
        
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt or ""},
                {"role": "user", "content": f"主播说：{prompt}"},
            ],
            "stream": False,
            "options": {"temperature": 0.6},
        }
        
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    f"{self.base_url}/api/chat",
                    json=payload,
                )
                resp.raise_for_status()
                data = resp.json()
                reply = data["message"]["content"].strip()
                reply = reply.strip("\"'「」")
                return reply
        except Exception as e:
            logger.warning(f"Ollama 请求失败: {e}")
            return ""


# ── Provider 工厂 ───────────────────────────────────

PROVIDER_REGISTRY = {
    "openai": OpenAIProvider,
    "ollama": OllamaProvider,
}


def create_provider(provider_name: str, **kwargs) -> BaseProvider:
    """创建 Provider 实例"""
    cls = PROVIDER_REGISTRY.get(provider_name)
    if not cls:
        raise ValueError(f"不支持的 provider: {provider_name}，可选: {list(PROVIDER_REGISTRY.keys())}")
    return cls(**kwargs)


# ── 主引擎类 ────────────────────────────────────────

class LLMReplyGenerator:
    """LLM 智能回复生成器
    
    支持多种后端模型，LLM 不可用时自动降级到关键词匹配。
    
    Args:
        provider: LLM provider 名称 ("openai" | "ollama")
        model: 模型名称
        api_key: API 密钥（openai 模式需要）
        base_url: API 地址
        fallback_rules: 降级用的关键词规则（默认内置规则）
        context_size: 上下文记忆轮数（默认 3）
    """
    
    def __init__(
        self,
        provider: str = "ollama",
        model: str = "deepseek-r1:7b",
        api_key: str = "",
        base_url: str = "",
        fallback_rules: list | None = None,
        context_size: int = 3,
        personas: list | None = None,
        rotate_interval: int = 300,
    ):
        self.provider_name = provider
        self.model = model
        self.context_size = context_size
        self._history: list[str] = []  # 最近 N 轮主播话术
        self._last_replies: list[str] = []  # 最近 N 轮回复
        self._provider: BaseProvider | None = None
        self._available = False
        
        # 兜底规则
        self._fallback_rules = fallback_rules or FALLBACK_RULES
        
        # ── 角色轮换系统 ──
        self._personas = personas or PERSONAS
        self._rotate_interval = int(os.getenv("PERSONA_ROTATE_INTERVAL", str(rotate_interval)))
        self._persona_idx = 0          # 当前角色索引
        self._persona_switched_at = 0.0  # 上次切换时间戳
        self._pick_initial_persona()   # 启动时随机选一个
        
        # 初始化 provider
        self._init_provider(api_key, base_url)
    
    def _build_persona_description(self, persona: dict) -> str:
        """将角色字典格式化为 LLM 可读的描述"""
        return (
            f"你现在的身份是：{persona['name']}\n"
            f"性格特点：{persona['tone']}\n"
            f"消费习惯：{persona['trait']}\n"
            f"说话风格：{persona['style']}"
        )
    
    def _pick_initial_persona(self):
        """启动时随机选一个角色"""
        import random
        self._persona_idx = random.randint(0, len(self._personas) - 1)
        self._persona_switched_at = __import__("time").time()
        p = self._personas[self._persona_idx]
        logger.info(f"🎭 初始角色: {p['name']}")
    
    def _rotate_persona(self):
        """检查是否需要切换角色（每 5 分钟轮换）"""
        import random
        import time
        now = time.time()
        elapsed = now - self._persona_switched_at
        
        if elapsed < self._rotate_interval:
            return  # 还没到切换时间
        
        # 随机选一个和当前不同角色
        candidates = [i for i in range(len(self._personas)) if i != self._persona_idx]
        self._persona_idx = random.choice(candidates)
        self._persona_switched_at = now
        p = self._personas[self._persona_idx]
        logger.info(f"🔄 角色切换 [{self._rotate_interval//60}分钟到] → {p['name']}")
    
    def _get_current_persona_prompt(self) -> str:
        """构建当前角色对应的完整 system prompt"""
        self._rotate_persona()
        persona = self._personas[self._persona_idx]
        desc = self._build_persona_description(persona)
        return BASE_SYSTEM_PROMPT.format(persona_description=desc)
    
    def _init_provider(self, api_key: str, base_url: str):
        """初始化 LLM provider"""
        try:
            kwargs = {"model": self.model}
            
            if self.provider_name == "openai":
                kwargs["api_key"] = api_key or os.getenv("LLM_API_KEY", "")
                kwargs["base_url"] = base_url or os.getenv("LLM_BASE_URL", "https://api.openai.com/v1")
                if not kwargs["api_key"]:
                    logger.warning("⚠️ LLM_API_KEY 未配置，LLM 引擎将使用关键词兜底")
                    self._available = False
                    return
            
            elif self.provider_name == "ollama":
                kwargs["base_url"] = base_url or os.getenv("OLLAMA_URL", "http://localhost:11434")
            
            self._provider = create_provider(self.provider_name, **kwargs)
            self._available = True
            logger.info(f"✅ LLM 引擎已就绪: provider={self.provider_name}, model={self.model}")
            
        except Exception as e:
            logger.warning(f"⚠️ LLM 引擎初始化失败: {e}，将使用关键词兜底")
            self._available = False
    
    async def generate(self, asr_text: str) -> str:
        """根据 ASR 识别文本生成回复
        
        优先使用 LLM，不可用时降级到关键词匹配。
        """
        if not asr_text or not asr_text.strip():
            return ""
        
        text = asr_text.strip()
        
        # 1. 尝试 LLM 生成
        if self._available and self._provider:
            reply = await self._llm_generate(text)
            if reply:
                self._history.append(text)
                self._last_replies.append(reply)
                # 裁剪历史
                if len(self._history) > self.context_size:
                    self._history.pop(0)
                if len(self._last_replies) > self.context_size:
                    self._last_replies.pop(0)
                return reply
        
        # 2. LLM 不可用 → 关键词兜底
        return self._fallback_match(text)
    
    async def _llm_generate(self, text: str) -> str:
        """使用 LLM 生成回复"""
        # 构建带上下文的 prompt
        context_prompt = text
        if self._history:
            context = " | ".join(self._history[-2:])
            context_prompt = f"{context} | 现在主播说：{text}"
        
        # 获取当前角色 system prompt（含自动轮换检测）
        persona_prompt = self._get_current_persona_prompt()
        
        reply = await self._provider.generate(context_prompt, system_prompt=persona_prompt)
        
        # 验证回复是否合理（太长的可能是模型在解释，丢弃）
        if len(reply) > 50:
            return ""
        
        # 避免重复回复（和最近一条一样就丢弃）
        if reply and self._last_replies and reply == self._last_replies[-1]:
            logger.debug(f"LLM 生成重复回复: {reply}，跳过")
            return ""
        
        return reply
    
    def _fallback_match(self, text: str) -> str:
        """关键词兜底匹配"""
        for keywords, reply in self._fallback_rules:
            if any(kw in text for kw in keywords):
                logger.info(f"🔑 兜底命中: {reply}")
                return reply
        return ""
    
    @property
    def is_available(self) -> bool:
        return self._available
    
    @property
    def current_persona(self) -> dict:
        """获取当前角色信息"""
        return self._personas[self._persona_idx]
    
    @property
    def persona_name(self) -> str:
        """获取当前角色名称"""
        return self._personas[self._persona_idx]["name"]


# ── 便捷工厂函数 ────────────────────────────────────

def create_engine_from_env() -> LLMReplyGenerator:
    """从环境变量创建 LLM 引擎
    
    环境变量:
        LLM_PROVIDER    - provider 类型 (openai / ollama，默认 ollama)
        LLM_MODEL       - 模型名 (默认 deepseek-r1:7b)
        LLM_API_KEY     - API 密钥 (openai 模式需要)
        LLM_BASE_URL    - API 地址
        OLLAMA_URL      - Ollama 地址 (默认 http://localhost:11434)
    """
    provider = os.getenv("LLM_PROVIDER", "ollama").lower()
    model = os.getenv("LLM_MODEL", "deepseek-r1:7b")
    api_key = os.getenv("LLM_API_KEY", "")
    base_url = os.getenv("LLM_BASE_URL", "")
    
    return LLMReplyGenerator(
        provider=provider,
        model=model,
        api_key=api_key,
        base_url=base_url,
    )


# ── 独立测试 ──────────────────────────────────────

async def _test_main():
    """测试 LLM 决策引擎"""
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    
    engine = create_engine_from_env()
    
    test_cases = [
        "扣1统计人数，我看有多少人",
        "穿什么码，L码能穿到多少斤",
        "要什么颜色，黑色还是白色",
        "确定带一单的扣确定",
        "最后一波库存了，没抢到可惜",
        "点点赞，赞点到一万就开",
    ]
    
    print("\n🧪 LLM 决策引擎测试（角色每 5 分钟自动轮换）\n")
    for case in test_cases:
        reply = await engine.generate(case)
        source = "LLM" if engine.is_available else "兜底"
        persona = engine.persona_name if engine.is_available else ""
        print(f"  主播: {case}")
        print(f"  [{source}] [{persona}] 回复: {reply or '(空)'}\n")


if __name__ == "__main__":
    asyncio.run(_test_main())

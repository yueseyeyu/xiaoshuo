# -*- coding: utf-8 -*-
"""
llm_client.py — 统一 LLM 调用客户端
====================================
消除 pipeline 中 4+ 模块各自实现的 _llm_call / _llm_port / _get_llama_base 重复代码。

设计原则:
  - 单一入口: 所有 LLM 调用通过 llm_chat() 或 llm_chat_json()
  - 配置驱动: 端口/超时/重试从 config.yaml 读取 (SSOT)
  - 健壮性: 内置重试、超时、thinking-tag 清理
  - 零新依赖: 仅用 stdlib (urllib + json)

用法:
  from xiaoshuo.infra.llm_client import llm_chat, llm_chat_json, get_llm_base_url, check_llm_health

  # 简单调用
  reply = llm_chat("你好", system="你是助手", max_tokens=200)

  # JSON 输出
  data = llm_chat_json("分析这段文本", system="输出纯JSON")

  # 健康检查
  if check_llm_health():
      ...
"""

from __future__ import annotations

import json
import re
import urllib.request
import urllib.error
from typing import Optional

from xiaoshuo.infra.config_manager import get_config
from xiaoshuo.infra.logging_config import get_logger

logger = get_logger("llm_client")

# ── Thinking tag stripper (DeepSeek-R1 兼容) ──
_THINK_PATTERN = re.compile(r"<think>[\s\S]*?</think>\s*", re.DOTALL)


def _strip_thinking(text: str) -> str:
    """Remove <think>...</think> tags from DeepSeek-R1 output."""
    return _THINK_PATTERN.sub("", text).strip()


def get_llm_port() -> int:
    """获取 LLM 端口 (从 config.yaml analysis.llm_port, 默认 8000)。"""
    try:
        cfg = get_config()
        return int(cfg.get("analysis", {}).get("llm_port", 8000))
    except Exception:
        return 8000


def get_llm_base_url() -> str:
    """获取 LLM 基础 URL (如 http://127.0.0.1:8000)。"""
    return f"http://127.0.0.1:{get_llm_port()}"


def get_main_model_port() -> int:
    """获取主模型端口 (从 model_orchestration.models.main_model.port)。"""
    try:
        cfg = get_config()
        return int(
            cfg.get("model_orchestration", {})
            .get("models", {})
            .get("main_model", {})
            .get("port", 8000)
        )
    except Exception:
        return 8000


def get_main_model_base_url() -> str:
    """获取主模型基础 URL。"""
    return f"http://127.0.0.1:{get_main_model_port()}"


def check_llm_health(base_url: Optional[str] = None, timeout: int = 3) -> bool:
    """检查 LLM 服务是否可用。

    Args:
        base_url: 自定义基础 URL, 默认使用 get_llm_base_url()
        timeout: 超时秒数
    Returns:
        True 如果服务可用
    """
    url = base_url or get_llm_base_url()
    try:
        urllib.request.urlopen(f"{url}/health", timeout=timeout)
        return True
    except Exception:
        return False


def llm_chat(
    prompt: str,
    system: str = "",
    max_tokens: int = 600,
    temperature: float = 0.0,
    timeout: int = 90,
    max_retries: int = 3,
    base_url: Optional[str] = None,
    strip_thinking: bool = True,
    stop: Optional[list[str]] = None,
) -> str:
    """统一 LLM 对话调用。

    Args:
        prompt: 用户消息
        system: 系统消息 (可选)
        max_tokens: 最大生成 token 数
        temperature: 采样温度
        timeout: 单次请求超时秒数
        max_retries: 最大重试次数 (指数退避)
        base_url: 自定义基础 URL, 默认从 config 读取
        strip_thinking: 是否清理 <think> 标签
        stop: 停止词列表 (如 ["\n\n"])

    Returns:
        LLM 回复文本, 失败返回空字符串
    """
    url = base_url or get_llm_base_url()
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    payload = {
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    if stop:
        payload["stop"] = stop
    data = json.dumps(payload).encode("utf-8")

    last_error = None
    for attempt in range(max_retries):
        try:
            req = urllib.request.Request(
                f"{url}/v1/chat/completions",
                data,
                {"Content-Type": "application/json"},
            )
            resp = urllib.request.urlopen(req, timeout=timeout)
            result = json.loads(resp.read())
            content = result.get("choices", [{}])[0].get("message", {}).get("content", "")
            if strip_thinking:
                content = _strip_thinking(content)
            return content
        except (urllib.error.URLError, urllib.error.HTTPError, OSError, json.JSONDecodeError) as e:
            last_error = e
            if attempt < max_retries - 1:
                import time
                wait = 2 ** attempt  # 1s, 2s, 4s
                logger.warning("LLM 调用失败 (attempt %d/%d): %s, %ds 后重试",
                               attempt + 1, max_retries, e, wait)
                time.sleep(wait)
            else:
                logger.error("LLM 调用最终失败 (已重试 %d 次): %s", max_retries, e)

    return ""


def llm_chat_json(
    prompt: str,
    system: str = "输出纯JSON，不要额外说明。",
    max_tokens: int = 800,
    temperature: float = 0.0,
    timeout: int = 90,
    max_retries: int = 3,
    base_url: Optional[str] = None,
) -> dict | None:
    """调用 LLM 并解析 JSON 输出。

    自动提取 ```json ... ``` 代码块或裸 JSON。
    失败返回 None。
    """
    raw = llm_chat(
        prompt, system=system, max_tokens=max_tokens,
        temperature=temperature, timeout=timeout,
        max_retries=max_retries, base_url=base_url,
    )
    if not raw:
        return None

    # 尝试直接解析
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    # 尝试提取 ```json ... ``` 代码块
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw)
    if m:
        try:
            return json.loads(m.group(1).strip())
        except json.JSONDecodeError:
            pass

    # 尝试提取第一个 { ... } 块
    m = re.search(r"\{[\s\S]*\}", raw)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass

    logger.warning("LLM JSON 解析失败, 原始输出前200字: %s", raw[:200])
    return None

# 7. 接口与通信设计

> Extracted from DESIGN.md | [Back to index](../../DESIGN.md)

---

## 7. 接口与通信设计

### 7.1 AI_PROTOCOL.md 协议注入（v5.0：静态/动态分离 + Action Constraint）

```python
# .agents/skill_loader.py (v5.0 重构)
def inject_skill(task_type: str, chapter: int) -> dict:
    """分离静态前缀和动态内容，确保 Prefix Cache 命中"""
    static = build_static_skill_prefix()   # AI_PROTOCOL.md + config.yaml → Prefix Cached
    dynamic = build_chapter_context(chapter)  # 章节号、Intent → 每次动态拼接
    
    return {"system": static, "user": dynamic}
```

### 7.2 Prefix Caching + Context Shifting 组合方案

```
┌──────────────────────────────────────────────────────────────┐
│                  v5.0 推理加速双重机制                         │
│                                                              │
│  Prefix Caching (跨 Session):                                │
│    AI_PROTOCOL.md + config.yaml KV → 磁盘 (system_prompt_cache.bin) │
│    首次推理: 编码 System Prompt → 写磁盘                       │
│    后续推理: 读磁盘 → 直接复用 KV → 首 Token 延迟 -40%         │
│                                                              │
│  Context Shifting (同 Session 跨阶段):                        │
│    S1 → S3 → S4+++ 之间复用 KV Cache (--cache-reuse 256)     │
│    → 第 2/3 次推理速度 +30-40%                                │
│                                                              │
│  关键约束: System Prompt 禁止动态变量 → Prefix Cache 100% 命中  │
└──────────────────────────────────────────────────────────────┘
```

### 7.3 LLM 通信协议

```
POST http://localhost:8000/v1/chat/completions
{
  "model": "qwen3.5-9b",
  "messages": [
    {"role": "system", "content": "[AI_PROTOCOL.md + 结构化约束] (🆕 静态, Prefix Cached)"},
    {"role": "user", "content": "[章节内容 + canon数据 + NG上下文 + Intent] (动态)"}
  ],
  "temperature": 0.3,
  "max_tokens": 1000
}
```

温度策略同 v4.1。MCP/FastAPI 接口同 v4.1。

---



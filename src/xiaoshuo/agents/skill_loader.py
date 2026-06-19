"""
skill_loader.py — System Prompt 构建器（静态前缀 + 动态拼接）
============================================================
─ 文件定位 ─
.agents/核心模块之一。读取 AI_PROTOCOL.md 作为静态 System Prompt 前缀，
按 task_type 拼接动态上下文（章节/角色/Intent/节拍），
确保 Prefix Caching 命中率 100%。

─ 架构设计 ─
AI_PROTOCOL.md (静态, 不变)           ← llama.cpp Prefix Cache 缓存
  +
Dynamic Context (动态, 每次变)   ← 拼接在缓存边界之后

llama.cpp 的 KV Cache 机制：首次编码 AI_PROTOCOL.md → 写入磁盘缓存；
后续推理直接读缓存，仅需编码动态部分。静态部分不能含任何变量。

─ 对外接口 ─
from skill_loader import SkillLoader
loader = SkillLoader()
prompt = loader.build("S3_logic_cop", context={
    "chapter_num": 5,
    "characters": "...",
    "chapter_text": "..."
})
# prompt → 直接注入 messages[0] = {"role": "system", "content": prompt}

─ 开发者指引 ─
· 新增 task_type: 在 TASK_TEMPLATES 中添加模板
· 修改 AI_PROTOCOL.md: 编辑根目录 AI_PROTOCOL.md 文件，下次调用自动生效
· 动态内容来源: canon/*.md + state.json + NovelGraph（P1后）
· 静态部分切分: 只加载 AI_PROTOCOL.md 中 <!-- → --> 之后的内容（开发者注释已被过滤）
"""

from pathlib import Path
from xiaoshuo import PROJECT_ROOT
from typing import Optional
import re

# ============================================================
# 常量
# ============================================================
PROJECT_ROOT = PROJECT_ROOT
AI_PROTOCOL_PATH = PROJECT_ROOT / "AI_PROTOCOL.md"


# ============================================================
# 不同 task_type 的动态模板
# ============================================================
# 每个模板是一个 f-string，变量从 context dict 中取值。
# 模板设计原则：只追问、不代写；只抽象方向、不给具体文字。
# 新增 task_type 时在此处添加新条目。

TASK_TEMPLATES: dict[str, str] = {
    # ── S1 创意引导 ──
    "S1_creative": """
## 当前创作上下文
- 下一章: 第 {chapter_num} 章
{outline_section}
{characters_section}
{previous_svos_section}

## 你的任务
生成 3 个互不相同的剧情发展方向（温度参数由系统控制）。
每个方向只描述叙事功能和逻辑动机，不提供任何具体文字。
标注每个方向的认知距离（近/中/远），鼓励作者选择最远的。
""",

    # ── S2b 参考版生成 ──
    "S2b_reference": """
## 当前创作上下文
- 第 {chapter_num} 章（作者已手写 {handwritten_words} 字，可提供模糊方向）
{characters_section}
{outline_section}

## 你的任务
作者卡文，需要方向性启发。给出 3 个模糊的叙事方向（不是完整段落），
每个方向标注叙事功能。不提供任何可直接复制粘贴的文字。
认知距离偏向: 推荐最远的方向（概率 {cognitive_distance_bias:.0%}）。
""",

    # ── S3 逻辑警察 ──
    "S3_logic_cop": """
## 审查对象
第 {chapter_num} 章全文（{chapter_word_count} 字）。

## 角色设定参考
{characters_section}

## 你的角色
你是一个冷血的逻辑审查官。你的唯一任务是：
1. 找出本章中与前文矛盾的地方（时间线/角色能力/物品归属/因果关系）
2. 找出角色行为与其已建立性格的偏离
3. 指出任何"为了方便而牺牲逻辑"的叙事捷径

不要表扬任何写得好的地方。只找问题。
输出格式严格遵循 AI_PROTOCOL.md §4.2 的 JSON schema。
""",

    # ── S3 网文编辑 ──
    "S3_editor": """
## 审查对象
第 {chapter_num} 章全文（{chapter_word_count} 字）。

## 你的角色
你是一个专业的网文编辑。关注：
1. 节奏感 — 信息揭示速度、张弛平衡
2. 爽点密度 — 每 3000 字内的情绪峰值数量
3. 钩子效果 — 章末是否有足够悬念
4. 代入感 — 读者是否能理解/共情当前视角角色

每项 1-10 分，给出具体修改方向（不提供具体文字）。
""",

    # ── S3 语言质检 ──
    "S3_qc": """
## 审查对象
第 {chapter_num} 章全文（{chapter_word_count} 字）。

## 你的角色
你是语言质量检测器。纯数据驱动，客观输出：
1. AI 指纹词密度 — 高频词共现模式检测
2. 句法模式重复率 — 主语结构/句式重复频率
3. 风格漂移幅度 — 与作者前 5 章基线的偏离

阈值参考: config.yaml → detection.layers。
""",

    # ── S4 风格检测 ──
    "S4_detection": """
## 检测对象
第 {chapter_num} 章全文（{chapter_word_count} 字）。

## 你的任务
对本章做七层 AI 风格检测，输出格式严格遵循 AI_PROTOCOL.md §4.3。
阈值参考: config.yaml → detection.layers。
""",

    # ── M5a 节拍分析 ──
    "M5a_beat": """
## 分析对象
第 {chapter_num} 章（{chapter_word_count} 字）。

## 你的任务
用当前活跃的叙事理论框架分析本章的节拍位置。
当前框架: {active_framework}。
输出: 节拍标签、节拍区间、与理论模型的偏差说明。
""",
}


# ============================================================
# SkillLoader: System Prompt 构建器
# ============================================================
class SkillLoader:
    """读取 AI_PROTOCOL.md 静态前缀 + 按任务拼接动态上下文。

    用法:
        loader = SkillLoader()
        prompt = loader.build("S3_logic_cop", context={...})
        # prompt 可直接作为 messages[0]["content"]

    设计:
    - 单例: 每次调用重新读取 AI_PROTOCOL.md（文件可能被作者修改）
    - 静态前缀: AI_PROTOCOL.md 中 <!-- ... --> 之后的所有内容
    - 动态后缀: TASK_TEMPLATES[task_type] 用 context 变量填充
    - 缓存友好: 每次返回的静态部分完全相同 → Prefix Cache 100% 命中
    """

    def __init__(self):
        self._skill_md: Optional[str] = None
        self._skill_mtime: float = 0.0  # 文件修改时间，用于检测变更

    # ── 静态前缀加载 ──

    def _load_static_prefix(self) -> str:
        """加载 AI_PROTOCOL.md 的静态内容（去除 HTML 开发者注释）。

        开发者注释（<!-- ... --> 之间的内容）不被注入 System Prompt，
        只注入 LLM 真正需要看到的行为协议部分。

        缓存策略: 检查文件 mtime，仅在文件修改后重新读取。
        返回: AI_PROTOCOL.md 中第一个 HTML 注释闭合后的全部内容。
        """
        mtime = AI_PROTOCOL_PATH.stat().st_mtime if AI_PROTOCOL_PATH.exists() else 0.0
        if self._skill_md is not None and mtime == self._skill_mtime:
            return self._skill_md

        raw = AI_PROTOCOL_PATH.read_text(encoding="utf-8")
        cleaned = re.sub(r"<!--.*?-->\s*", "", raw, flags=re.DOTALL)

        self._skill_md = cleaned.strip()
        self._skill_mtime = mtime
        return self._skill_md

    # ── 系统提示构建 ──

    def build(self, task_type: str, context: Optional[dict] = None) -> str:
        """构建完整的 System Prompt。

        Args:
            task_type: 任务类型（必须匹配 TASK_TEMPLATES 中的 key）
            context: 动态变量字典。常用 key:
                chapter_num: int | str  — 章节号
                chapter_word_count: int  — 章节字数
                handwritten_words: int   — 已手写字数（S2b用）
                outline_section: str     — 大纲摘要（可选）
                characters_section: str  — 角色列表（可选）
                previous_svos_section: str — SVO摘要（可选）
                active_framework: str    — 活跃叙事框架（M5a用）
                cognitive_distance_bias: float — 认知距离偏向（S2b用）

        Returns:
            完整的 System Prompt 字符串。
            如果 task_type 未知，返回仅含静态前缀的 prompt。
        """
        static = self._load_static_prefix()

        # 未知 task_type → 仅返回静态前缀
        template = TASK_TEMPLATES.get(task_type)
        if template is None or context is None:
            return static

        # 填充模板变量
        ctx = self._default_context(context)
        try:
            dynamic = template.format(**ctx)
        except KeyError as e:
            # 缺失变量 → 用空白填充，不中断流程
            missing = str(e).strip("'")
            ctx[missing] = f"[{missing} 未提供]"
            dynamic = template.format(**ctx)

        # 拼接: 静态前缀 + 两个换行分隔 + 动态后缀
        return f"{static}\n\n{dynamic}"

    # ── 辅助: 填充默认值 ──

    @staticmethod
    def _default_context(context: dict) -> dict:
        """为缺失的 context key 填充安全默认值。

        不修改原始 context dict，返回浅拷贝后的填充版本。
        """
        result = dict(context)  # 浅拷贝，保护入参
        defaults = {
            "chapter_num": "?",
            "chapter_word_count": "?",
            "handwritten_words": 0,
            "outline_section": "",
            "characters_section": "",
            "previous_svos_section": "",
            "active_framework": "save_the_cat",
            "cognitive_distance_bias": 0.7,
        }
        for key, default in defaults.items():
            if key not in result:
                result[key] = default

        # 格式化章节辅助信息
        if result["outline_section"]:
            result["outline_section"] = f"- 粗纲参考:\n{result['outline_section']}"
        if result["characters_section"]:
            result["characters_section"] = f"- 出场角色:\n{result['characters_section']}"
        if result["previous_svos_section"]:
            result["previous_svos_section"] = f"- 近期关键事件:\n{result['previous_svos_section']}"

        return result

    # ── 便捷方法 ──

    def get_static_prefix(self) -> str:
        """仅返回 AI_PROTOCOL.md 静态前缀（不含动态部分）。

        用途: 调试 or 查看 AI_PROTOCOL.md 当前内容。
        """
        return self._load_static_prefix()

    def get_supported_tasks(self) -> list[str]:
        """返回所有已注册的 task_type 列表。"""
        return list(TASK_TEMPLATES.keys())


# ============================================================
# 模块自检
# ============================================================
if __name__ == "__main__":
    print("=" * 60)
    print("  skill_loader.py — 自检")
    print("=" * 60)

    loader = SkillLoader()

    # 1. 检查 AI_PROTOCOL.md 是否存在
    print(f"\n[TEST] AI_PROTOCOL.md: {'[OK]' if AI_PROTOCOL_PATH.exists() else '[FAIL]'} {AI_PROTOCOL_PATH}")

    # 2. 加载静态前缀
    static = loader.get_static_prefix()
    print(f"[TEST] 静态前缀: {len(static)} 字符, {len(static.splitlines())} 行")
    print(f"       前 80 字符: {repr(static[:80])}")

    # 3. 检查支持的 task_type
    tasks = loader.get_supported_tasks()
    print(f"\n[TEST] 已注册 task_type: {len(tasks)} 个")
    for t in tasks:
        print(f"  - {t}")

    # 4. 测试构建 S3 prompt（无上下文）
    print(f"\n[TEST] build('S3_logic_cop', {{}})：")
    prompt = loader.build("S3_logic_cop", {"chapter_num": 1, "chapter_word_count": 3000})
    lines = prompt.splitlines()
    print(f"       总行数: {len(lines)}")
    print(f"       总字符: {len(prompt)}")
    # 验证: 静态前缀在开头
    assert prompt.startswith("---"), "[FAIL] prompt 不是以 AI_PROTOCOL.md 内容开头"
    print(f"       [OK] 静态前缀位于开头")

    # 5. 测试缓存: 两次加载应该相同
    prompt2 = loader.build("S3_logic_cop", {"chapter_num": 1, "chapter_word_count": 3000})
    assert prompt == prompt2, "[FAIL] 缓存失效：两次 build 返回不同内容"
    print(f"       [OK] 缓存命中: 两次 build 内容相同")

    # 6. 测试未知 task_type
    prompt_unknown = loader.build("unknown_task", {})
    assert prompt_unknown == static, "[FAIL] 未知 task 应返回纯静态前缀"
    print(f"       [OK] 未知 task_type → 返回纯静态前缀")

    print("\n[DONE] skill_loader.py 自检完成")

# -*- coding: utf-8 -*-
"""
routes_creative.py — 创作辅助 API 路由 (v8.4)
================================================
为前端提供以下新模块的 API 端点:
  1. 小说解构 (deconstruct_novel.py)
  2. 作者心智模型 + 决策直觉 (author_mind_model.py)
  3. 章节目标门控 (chapter_goal_gate.py)
  4. 提示词模板管理 (prompt_template.py)

所有路由挂载到 /api/creative/* 前缀下。
"""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

router = APIRouter(prefix="/api/creative", tags=["creative"])
logger = logging.getLogger("routes_creative")

PROJECT_ROOT = Path(__file__).resolve().parents[3]


# ============================================================
# 1. 小说解构
# ============================================================

class DeconstructRequest(BaseModel):
    text: str = ""
    max_chapters: int | None = None
    file_path: str = ""


@router.post("/deconstruct")
async def deconstruct_novel_api(req: DeconstructRequest):
    """对小说文本执行五段式结构化解构。

    输入小说文本 (或文件路径) → 输出:
      - genre_tags: 题材标签
      - structure: 结构拆解
      - characters: 人物拆解
      - borrowable: 可借鉴元素
      - warnings: 避雷清单
    """
    try:
        from xiaoshuo.tools.deconstruct_novel import deconstruct_novel

        text = req.text
        if not text and req.file_path:
            safe_path = Path(req.file_path)
            # 安全检查：只允许 data/raw 目录下的文件
            try:
                safe_path = safe_path.resolve()
                if not str(safe_path).startswith(str(PROJECT_ROOT)):
                    raise HTTPException(403, "文件路径越界")
            except Exception:
                raise HTTPException(403, "文件路径无效")
            if not safe_path.exists():
                raise HTTPException(404, f"文件不存在: {req.file_path}")
            text = safe_path.read_text(encoding="utf-8", errors="replace")

        if not text:
            raise HTTPException(400, "请提供小说文本或文件路径")

        result = deconstruct_novel(text, max_chapters=req.max_chapters)
        return result.to_dict()
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("deconstruct_novel_api failed")
        raise HTTPException(500, f"解构失败: {e}")


@router.get("/deconstruct/books")
async def list_deconstructable_books(genre: str = Query("末世")):
    """列出可解构的小说文件 (从 data/raw/novels 目录扫描)。"""
    novels_dir = PROJECT_ROOT / "data" / "raw" / "novels" / genre
    if not novels_dir.exists():
        return {"books": [], "genre": genre}
    books = []
    for txt_file in novels_dir.rglob("*.txt"):
        try:
            size_kb = txt_file.stat().st_size // 1024
            rel_path = str(txt_file.relative_to(PROJECT_ROOT))
            books.append({
                "title": txt_file.stem,
                "file_path": rel_path,
                "size_kb": size_kb,
                "genre": genre,
            })
        except Exception:
            continue
    books.sort(key=lambda b: b["title"])
    return {"books": books, "genre": genre, "count": len(books)}


# ============================================================
# 2. 作者心智模型 + 决策直觉引擎
# ============================================================

class DecisionRequest(BaseModel):
    scenario: str
    authors: list[str] | None = None
    context: dict | None = None


class RecordChoiceRequest(BaseModel):
    scenario: str
    chosen_author: str
    context: dict | None = None
    all_options: list[dict] | None = None


@router.get("/authors/presets")
async def list_preset_authors():
    """列出预设作者心智模型。"""
    try:
        from xiaoshuo.agents.author_mind_model import _PRESET_INTUITIONS

        authors = []
        for name, data in _PRESET_INTUITIONS.items():
            authors.append({
                "name": name,
                "style": data.get("style", ""),
                "representative_works": data.get("representative_works", []),
                "categories": list(data.get("choices", {}).keys()),
            })
        return {"authors": authors, "count": len(authors)}
    except Exception as e:
        logger.exception("list_preset_authors failed")
        return {"authors": [], "error": str(e)}


@router.get("/authors/{author_name}")
async def get_author_model(author_name: str):
    """获取指定作者的心智模型详情。"""
    try:
        from xiaoshuo.agents.author_mind_model import AuthorMindModel

        model = AuthorMindModel(author_name)
        model.load()
        fw = model.get_framework()
        return {
            "author_name": author_name,
            "framework": fw.to_dict(),
            "signature_techniques": model.signature_techniques,
            "craft_notes": model.craft_notes,
            "representative_works": model.representative_works,
            "summary": model.summarize(),
        }
    except Exception as e:
        logger.exception("get_author_model failed")
        raise HTTPException(500, f"加载作者模型失败: {e}")


@router.post("/decision/options")
async def generate_decision_options(req: DecisionRequest):
    """生成多作者决策选项。

    输入一个创作场景 → 返回多个作者视角的决策选项。
    """
    try:
        from xiaoshuo.agents.author_mind_model import DecisionIntuitionEngine

        engine = DecisionIntuitionEngine()
        options = engine.generate_decision_options(
            scenario=req.scenario,
            authors=req.authors,
            context=req.context,
        )
        return {
            "scenario": req.scenario,
            "options": [opt.to_dict() if hasattr(opt, "to_dict") else opt for opt in options],
            "count": len(options),
        }
    except Exception as e:
        logger.exception("generate_decision_options failed")
        raise HTTPException(500, f"生成决策选项失败: {e}")


@router.post("/decision/record")
async def record_decision_choice(req: RecordChoiceRequest):
    """记录用户的决策选择 (积累个人决策直觉库)。"""
    try:
        from xiaoshuo.agents.author_mind_model import DecisionIntuitionEngine

        engine = DecisionIntuitionEngine()
        engine.record_choice(
            scenario=req.scenario,
            chosen_author=req.chosen_author,
            context=req.context,
            all_options=req.all_options,
        )
        return {"ok": True, "message": "决策已记录"}
    except Exception as e:
        logger.exception("record_decision_choice failed")
        raise HTTPException(500, f"记录决策失败: {e}")


# ============================================================
# 3. 章节目标门控
# ============================================================

class GoalVerifyRequest(BaseModel):
    chapter_text: str
    chapter_num: int = 1
    target_chars: list[int] = [2000, 5000]
    min_pleasure_points: int = 1
    emotion_curve_template: str = "rising"
    require_canon_check: bool = True
    min_s3_score: float = 70.0
    context: dict | None = None


@router.post("/goal-gate/verify")
async def verify_chapter_goal(req: GoalVerifyRequest):
    """验证章节是否满足完成标准 (5条硬性条件)。"""
    try:
        from xiaoshuo.pipeline.chapter_goal_gate import ChapterGoalGate, GoalCondition

        goal = GoalCondition(
            chapter_num=req.chapter_num,
            target_chars=tuple(req.target_chars),
            min_pleasure_points=req.min_pleasure_points,
            emotion_curve_template=req.emotion_curve_template,
            require_canon_check=req.require_canon_check,
            min_s3_score=req.min_s3_score,
        )
        gate = ChapterGoalGate()
        result = gate.verify(
            chapter_text=req.chapter_text,
            goal=goal,
            context=req.context,
            iteration=0,
        )
        return result.to_dict()
    except Exception as e:
        logger.exception("verify_chapter_goal failed")
        raise HTTPException(500, f"目标验证失败: {e}")


@router.get("/goal-gate/history")
async def goal_gate_history(limit: int = Query(20, ge=1, le=100)):
    """获取章节目标验证历史。"""
    try:
        log_dir = PROJECT_ROOT / "data" / "checkpoints" / "goal_gate"
        if not log_dir.exists():
            return {"records": [], "count": 0}
        records = []
        for json_file in sorted(log_dir.glob("*.json"), reverse=True)[:limit]:
            try:
                import json
                data = json.loads(json_file.read_text(encoding="utf-8"))
                records.append(data)
            except Exception:
                continue
        return {"records": records, "count": len(records)}
    except Exception as e:
        logger.exception("goal_gate_history failed")
        return {"records": [], "error": str(e)}


# ============================================================
# 4. 提示词模板管理
# ============================================================

@router.get("/prompt-templates")
async def list_prompt_templates():
    """列出所有已注册的提示词模板。"""
    try:
        from xiaoshuo.pipeline.prompt_template import PromptTemplateRegistry

        registry = PromptTemplateRegistry()
        templates = []
        for task_type in registry.list_templates():
            tmpl = registry.get_template(task_type)
            if tmpl:
                templates.append({
                    "task_type": task_type,
                    "description": tmpl.description,
                    "system_prompt_preview": tmpl.system_prompt[:200] + ("..." if len(tmpl.system_prompt) > 200 else ""),
                    "user_template_preview": tmpl.user_template[:200] + ("..." if len(tmpl.user_template) > 200 else ""),
                    "system_prompt_hash": tmpl.system_prompt_hash,
                    "system_prompt_length": len(tmpl.system_prompt),
                })
        stats = registry.cache_stats()
        return {"templates": templates, "count": len(templates), "cache_stats": stats}
    except Exception as e:
        logger.exception("list_prompt_templates failed")
        return {"templates": [], "error": str(e)}


@router.get("/prompt-templates/cost-savings")
async def prompt_cost_savings():
    """估算缓存优化带来的成本节省。"""
    try:
        from xiaoshuo.pipeline.prompt_template import PromptTemplateRegistry

        registry = PromptTemplateRegistry()
        return registry.estimate_cost_savings()
    except Exception as e:
        logger.exception("prompt_cost_savings failed")
        return {"error": str(e)}


@router.get("/prompt-templates/{task_type}")
async def get_prompt_template(task_type: str):
    """获取指定模板的完整内容。"""
    try:
        from xiaoshuo.pipeline.prompt_template import PromptTemplateRegistry

        registry = PromptTemplateRegistry()
        tmpl = registry.get_template(task_type)
        if not tmpl:
            raise HTTPException(404, f"模板不存在: {task_type}")
        return {
            "task_type": task_type,
            "description": tmpl.description,
            "system_prompt": tmpl.system_prompt,
            "user_template": tmpl.user_template,
            "system_prompt_hash": tmpl.system_prompt_hash,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("get_prompt_template failed")
        raise HTTPException(500, f"获取模板失败: {e}")


class PromptRenderRequest(BaseModel):
    task_type: str
    variables: dict = {}


@router.post("/prompt-templates/render")
async def render_prompt_template(req: PromptRenderRequest):
    """渲染指定模板 (预览效果)。"""
    try:
        from xiaoshuo.pipeline.prompt_template import PromptTemplateRegistry

        registry = PromptTemplateRegistry()
        messages = registry.render(req.task_type, req.variables)
        return {"messages": messages, "task_type": req.task_type}
    except Exception as e:
        logger.exception("render_prompt_template failed")
        raise HTTPException(500, f"渲染模板失败: {e}")

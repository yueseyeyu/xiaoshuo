"""API 响应模型 — Pydantic Schema 定义"""

from __future__ import annotations
from typing import Optional
from pydantic import BaseModel


# ── 场景搜索 ──

class SceneResult(BaseModel):
    rank: int
    similarity: float
    book_name: str
    chapter: int
    scene_index: int
    char_count: int
    text_preview: str
    emotion: str
    pace: str
    conflict_level: str
    pleasure_type: str
    dominant_sub: str
    technique_summary: str


class SearchResponse(BaseModel):
    query: str
    genre: str
    total_scenes: int
    results: list[SceneResult]


class IndexStats(BaseModel):
    genre: str
    total_scenes: int
    total_books: int


# ── 风格校准 ──

class StyleRuleItem(BaseModel):
    dimension: str
    rule: str
    weight: float
    source: str
    evidence: str


class StyleCalibrateRequest(BaseModel):
    chapter_id: int = 0
    text: str
    version: str = ""


class StyleCalibrateResponse(BaseModel):
    ok: bool
    rule_count: int
    rules: list[StyleRuleItem]
    new_findings: int
    version: str = ""
    error: Optional[str] = None


class StyleRulesResponse(BaseModel):
    ok: bool
    rule_count: int
    rules: list[StyleRuleItem]
    version: str = ""
    error: Optional[str] = None


# ── v8.0: 平台合规预检 ──

class FingerprintHit(BaseModel):
    word: str
    count: int


class ComplianceScanResponse(BaseModel):
    ok: bool
    risk_level: str
    total_count: int
    high_risk_count: int
    by_category: dict[str, list[FingerprintHit]]
    high_risk_hits: list[FingerprintHit]
    error: Optional[str] = None
    # v8.1: AI 率预估 (对标番茄 30% 红线)
    ai_rate: float = 0.0
    ai_rate_level: str = ""
    ai_rate_passed: bool = True
    ai_rate_recommendation: str = ""


# ── 任务管理 (v8.4) ──

class TaskCreateRequest(BaseModel):
    name: str = "未命名任务"
    type: str = "disassembly"
    genre: str = "末世"
    books: list[str] = []


class TaskItem(BaseModel):
    id: str
    name: str
    type: str
    genre: str
    books: list[str]
    status: str
    progress: int
    created_at: str
    updated_at: str


class TasksResponse(BaseModel):
    tasks: list[TaskItem]
    genre: str
    count: int
#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
scene_search.py — 场景级写作参考检索引擎 v3 (混合检索: BM25 + BGE + RRF)
==========================================================================
为新人作者提供"怎么写这种场景"的语义搜索能力。
输入自然语言描述（如"拍卖场冲突"），从书库中检索最相似的场景，
并附上技法分析。

技术栈 (v3 混合检索, 工业标准方案):
  - 场景切分: 段落组(双换行) → 300-1500字场景单元
  - 中文分词: jieba (精确模式 + 自定义停用词) — 用于 BM25 通道
  - 关键词检索 (通道A): rank_bm25.BM25Okapi + jieba 分词
  - 语义检索 (通道B): sentence_transformers.SentenceTransformer (BAAI/bge-small-zh-v1.5, 512维)
  - 融合算法: Reciprocal Rank Fusion (RRF), k=60 (工业标准默认值)
  - 技法: 复用 rhythm CSV + technique_tagger

变更历史:
  v1 → v2: 改为纯 TF-IDF (基于错误的"硬约束"幻觉, 已废弃)
  v2 → v3: 混合检索 BM25 + BGE + RRF (工业标准, 召回率最优)
           - BM25 通道: 关键词精确匹配 + 词频饱和 + 长度归一化
           - BGE 通道:  语义相似度, 弥补同义词/抽象查询场景
           - RRF 融合:  倒数排名融合, 无需分数标定, 鲁棒性强

参考文献:
  - BM25: Robertson & Zaragoza (2009), "The Probabilistic Relevance Framework: BM25 and Beyond"
  - RRF:  Cormack et al. (2009), "Reciprocal Rank Fusion outperforms Condorcet and individual Rank Learning Methods"
  - 混合检索: BEIR/MTEB 基准显示 hybrid 比 BM25/BGE 单通道高 5-15% NDCG@10

用法:
  python -m xiaoshuo.pipeline.scene_search "拍卖场冲突" --genre 末世 --top 5
  python -m xiaoshuo.pipeline.scene_search --build  # 重建索引
"""

import csv
import hashlib
import json
import os
import pickle
import re
import shutil
import stat
import threading
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Optional, TYPE_CHECKING

import jieba
import numpy as np
from rank_bm25 import BM25Okapi

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

from xiaoshuo import PROJECT_ROOT
from xiaoshuo.infra.config_manager import get_config
from xiaoshuo.pipeline.rhythm_analyzer import extract_chapters

# ── 常量 ──
_NOVELS_DIR = PROJECT_ROOT / "data" / "raw" / "novels"
_INDEX_PATH = PROJECT_ROOT / "data" / "raw" / "novel_index.json"

# 场景切分参数
_MIN_SCENE_CHARS = 200
_MAX_SCENE_CHARS = 1500
_MERGE_MIN_CHARS = 100  # 小于此值的段落合并到相邻场景

# RRF 融合参数 (Reciprocal Rank Fusion)
_RRF_K = 60  # 工业标准默认值 (Cormack et al. 2009)

# 默认 BGE 模型 (与 config.yaml 保持一致)
_DEFAULT_BGE_MODEL = "BAAI/bge-small-zh-v1.5"
_BGE_CACHE_DIR = PROJECT_ROOT / ".hf_cache"

BuildProgressCallback = Callable[[str, int, int], None]


class BuildProgressAbort(RuntimeError):
    """由受控 worker 请求停止构建，不把停止误报为普通回调错误。"""


class IndexStagingCleanupError(RuntimeError):
    """staging 无法清理，保留 run 供诊断并阻止成功回执。"""

    def __init__(self, message: str):
        super().__init__(message)
        self.cleanup_error = message


class IndexPublishRollbackError(RuntimeError):
    """正式索引发布或其回滚失败，禁止把状态报告为可用。"""

    def __init__(self, message: str):
        super().__init__(message)
        self.cleanup_error = message


_METADATA_STRING_FIELDS = (
    "book_name", "text_preview", "emotion", "pace", "conflict_level",
    "pleasure_type", "dominant_sub", "hook_type", "technique_summary",
    "split_reason",
)
_METADATA_INT_FIELDS = (
    "chapter", "scene_index", "char_count", "parent_scene_index",
    "sub_scene_index", "token_count",
)
_METADATA_FLOAT_FIELDS = ("dialogue_ratio",)


class IndexNotReadyError(RuntimeError):
    """索引不存在、损坏或与当前模型/语料合同不一致。"""


class EmbeddingModelError(IndexNotReadyError):
    """BGE 加载或编码失败，使用稳定的模型错误分类。"""


class CorpusContractError(IndexNotReadyError):
    """章节缺少索引所需的完整正文，禁止静默回退到截断字段。"""

    code = "CORPUS_CONTRACT_INVALID"

    def __init__(self, message: str):
        super().__init__(f"{self.code}: {message}")


class QueryTooLongError(IndexNotReadyError):
    """查询超过当前 BGE tokenizer 合同，禁止静默截断。"""

    code = "QUERY_TOO_LONG"

    def __init__(self, token_count: int, token_max: int):
        super().__init__(
            f"{self.code}: 查询包含 {token_count} 个 token，超过上限 {token_max}"
        )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _digest_entries(entries: list[tuple[str, str]]) -> str:
    payload = json.dumps(sorted(entries), ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _notify_progress(
    callback: Optional[BuildProgressCallback],
    phase: str,
    n_done: int,
    n_total: int,
) -> None:
    """发送进度；普通回调错误不改变构建结果，受控停止例外继续传播。"""
    if callback is None:
        return
    try:
        callback(phase, n_done, n_total)
    except BuildProgressAbort:
        raise
    except Exception as exc:  # pragma: no cover - 保护业务构建不被观测器拖垮
        print(f"  [WARN] 构建进度回调失败：{exc}")


def _is_strict_int(value: Any) -> bool:
    """判断不把 bool 当作整数的严格整数类型。"""
    return isinstance(value, int) and not isinstance(value, bool)


def _valid_book_reports(value: Any) -> bool:
    """校验 manifest 中逐本构建报告的结构和计数类型。"""
    if not isinstance(value, list):
        return False
    count_fields = (
        "chapter_count", "max_chapter_chars", "total_chapter_chars",
        "abnormal_chapter_count",
    )
    for report in value:
        if not isinstance(report, dict):
            return False
        if not isinstance(report.get("book_name"), str):
            return False
        if not isinstance(report.get("indexed"), bool):
            return False
        if any(
            not _is_strict_int(report.get(field)) or report[field] < 0
            for field in count_fields
        ):
            return False
    return True


def _reported_corpus_chars(book_reports: list[dict[str, Any]]) -> int:
    """使用逐本 raw_body 报告计算语料字符总数，不使用切分后文本。"""
    return sum(report["total_chapter_chars"] for report in book_reports)


def _is_reparse_point(path: Path) -> bool:
    """识别 Windows reparse point、symlink 和其他链接目录。"""
    try:
        info = path.stat(follow_symlinks=False)
    except OSError:
        return False
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return path.is_symlink() or bool(getattr(info, "st_file_attributes", 0) & reparse_flag)


def _reject_reparse_ancestors(path: Path, label: str) -> None:
    """拒绝目标及其已有祖先中的链接/junction，避免路径语义漂移。"""
    current = path.absolute()
    while True:
        if _is_reparse_point(current):
            raise IndexNotReadyError(f"{label} 路径包含 reparse point：{current}")
        parent = current.parent
        if parent == current:
            return
        current = parent


def _reject_reparse_file(path: Path, root: Path, label: str) -> None:
    """拒绝链接文件，并确认解析后的文件仍在批准目录内。"""
    _reject_contained_path(path, root, label)
    if not path.is_file():
        raise IndexNotReadyError(f"{label} 文件无效：{path}")


def _validated_file_for_read(path: Path, root: Path, label: str) -> Path:
    """在一次具体读取或哈希前重新验证文件边界。"""
    _reject_reparse_file(path, root, label)
    return path


def _validated_path_before_probe(path: Path, root: Path, label: str) -> None:
    """在任何存在性探测前验证原始路径和解析后路径的 containment。"""
    _reject_reparse_ancestors(path, label)
    try:
        path.resolve(strict=False).relative_to(root.resolve(strict=True))
    except (OSError, ValueError) as exc:
        raise IndexNotReadyError(f"{label} 文件越出批准目录：{path}") from exc


def _validated_optional_file(path: Path, root: Path, label: str) -> Optional[Path]:
    """安全探测可选文件；缺失返回 None，越界或链接直接失败。"""
    _validated_path_before_probe(path, root, label)
    if not path.exists():
        return None
    return _validated_file_for_read(path, root, label)


def _validated_sha256_file(path: Path, root: Path, label: str) -> str:
    """在哈希前重新完成文件路径门禁。"""
    return _sha256_file(_validated_file_for_read(path, root, label))


def _validated_file_size(path: Path, root: Path, label: str) -> int:
    """在读取文件大小前重新验证文件边界。"""
    return _validated_file_for_read(path, root, label).stat().st_size


def _configure_jieba_cache(cache_dir: Path) -> None:
    """将 jieba 运行缓存固定到 D 盘，避免写入系统临时目录。"""
    if not cache_dir.is_absolute() or cache_dir.drive.upper() != "D:":
        raise IndexNotReadyError("jieba 缓存目录必须位于 D 盘")
    _reject_reparse_ancestors(cache_dir, "jieba 缓存")
    cache_dir.mkdir(parents=True, exist_ok=True)
    _reject_reparse_ancestors(cache_dir, "jieba 缓存")
    jieba.dt.tmp_dir = str(cache_dir)
    jieba.dt.cache_file = str(cache_dir / "jieba.cache")


def _reject_contained_path(path: Path, root: Path, label: str) -> None:
    """拒绝 reparse 路径，并确认解析后的目标仍在批准目录内。"""
    _reject_reparse_ancestors(path, label)
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(root.resolve(strict=True))
    except (OSError, ValueError) as exc:
        raise IndexNotReadyError(f"{label} 文件越出批准目录：{path}") from exc


def _resolve_cache_path(path: Path, root: Path, label: str) -> Path:
    """解析缓存目标，并将其限制在调用者声明的边界内。"""
    if ".." in path.parts:
        raise IndexNotReadyError(f"{label} 不得包含 ..")
    _reject_reparse_ancestors(path, label)
    _reject_reparse_ancestors(root, label)
    resolved = path.resolve(strict=False)
    boundary = root.resolve(strict=True)
    try:
        resolved.relative_to(boundary)
    except ValueError as exc:
        raise IndexNotReadyError(f"{label} 越出批准目录：{path}") from exc
    _reject_reparse_ancestors(resolved, label)
    return resolved


def _resolve_project_cache_path(path: Path) -> Path:
    """将默认缓存路径固定在项目根内，并拒绝越界和 reparse。"""
    return _resolve_cache_path(path, PROJECT_ROOT, "索引缓存")

# 中文停用词 (场景检索场景下的常见无信息量词)
_STOP_WORDS = frozenset([
    "的", "了", "和", "是", "在", "我", "有", "他", "这", "那", "个",
    "们", "中", "来", "上", "下", "不", "也", "都", "而", "及", "与",
    "着", "或", "一个", "没有", "我们", "你们", "他们", "自己", "这个",
    "那个", "这样", "那样", "什么", "怎么", "为什么", "如何", "可以",
    "就是", "还是", "但是", "不过", "然后", "所以", "因为", "如果",
    "虽然", "尽管", "可是", "而是", "不是", "已经", "正在", "将要",
    "说道", "说道：", "道：", "：", "？", "！", "。", "，", "、",
])

# 技法标签映射 (从 rhythm 字段 → 人类可读描述)
_TECHNIQUE_DESCRIPTIONS = {
    "打脸": "打脸爽点：角色被轻视后展示实力，打脸反派",
    "突破": "突破爽点：角色升级/突破瓶颈，获得新能力",
    "碾压": "碾压爽点：角色以绝对优势碾压对手",
    "绝地反击": "绝地反击：从绝境中翻盘，戏剧性反转",
    "羁绊": "羁绊爽点：角色间情感纽带，信任/牺牲/守护",
    "策略": "策略爽点：用智谋而非蛮力解决问题",
    "资源": "资源爽点：获得稀有物资/装备/领地",
    "反派反噬": "反派反噬：反派自作自受，被自己的计划反噬",
    "伏笔回收": "伏笔回收：前期伏笔在此处兑现",
    "身份反转": "身份反转：角色真实身份揭露",
}

_EMOTION_LABELS = {
    "爽快": "上扬情绪，读者获得满足感",
    "悲壮": "悲壮情绪，牺牲/代价带来沉重感",
    "悬疑": "悬疑情绪，信息差制造紧张感",
    "日常": "日常情绪，过渡/铺垫/角色互动",
    "紧张": "紧张情绪，高压/危险逼近",
}

_PACE_LABELS = {
    "fast": "快节奏，连续动作/对话推进",
    "medium": "中速节奏，描写与推进平衡",
    "slow": "慢节奏，重描写/内心独白",
}




def _validate_genre_component(genre: str) -> None:
    """题材只能是单个目录组件，禁止绝对路径和嵌套路径。"""
    genre_path = Path(genre)
    if (
        not genre
        or genre_path.is_absolute()
        or genre_path.name != genre
        or ".." in genre_path.parts
    ):
        raise IndexNotReadyError("题材路径无效")


def _cache_dir(genre):
    _validate_genre_component(genre)
    return _resolve_project_cache_path(
        PROJECT_ROOT / "data" / "processed" / genre / "scene_index"
    )


def _rhythm_source_dir(genre: str) -> Path:
    """返回项目内的节奏 CSV 目录，不依赖执行上下文。"""
    _validate_genre_component(genre)
    rhythm_root = PROJECT_ROOT / "data" / "processed" / genre / "rhythm"
    _reject_reparse_ancestors(rhythm_root, "节奏数据")
    resolved = rhythm_root.resolve(strict=False)
    try:
        resolved.relative_to(PROJECT_ROOT.resolve(strict=True))
    except (OSError, ValueError) as exc:
        raise IndexNotReadyError("节奏数据路径必须位于项目目录内") from exc
    return resolved


def _rhythm_csv_path(genre: str, book_name: str) -> Path:
    """解析单本书的节奏 CSV，并拒绝越界或链接文件。"""
    book_path = Path(book_name)
    if not book_name or book_path.name != book_name or ".." in book_path.parts:
        raise IndexNotReadyError("节奏 CSV 文件名无效")
    csv_path = _rhythm_source_dir(genre) / f"rhythm_{book_name}.csv"
    _reject_reparse_ancestors(csv_path, "节奏 CSV")
    _validated_optional_file(csv_path, PROJECT_ROOT, "节奏 CSV")
    return csv_path


def _novel_source_path(genre: str, file_name: str) -> Path:
    """解析小说源文件，并在读取前拒绝越界、链接和 reparse 路径。"""
    _validate_genre_component(genre)
    novel_path_value = Path(file_name)
    if (
        not file_name
        or novel_path_value.name != file_name
        or ".." in novel_path_value.parts
    ):
        raise IndexNotReadyError("小说源文件路径无效")
    novel_path = _NOVELS_DIR / genre / file_name
    _reject_reparse_ancestors(novel_path, "小说源文件")
    resolved = novel_path.resolve(strict=False)
    try:
        resolved.relative_to(PROJECT_ROOT.resolve(strict=True))
    except (OSError, ValueError) as exc:
        raise IndexNotReadyError("小说源文件路径必须位于项目目录内") from exc
    return novel_path


def _validated_novel_index_path() -> Optional[Path]:
    if _is_reparse_point(_INDEX_PATH):
        raise IndexNotReadyError(f"源 novel_index.json 是 reparse point：{_INDEX_PATH}")
    _reject_reparse_ancestors(_INDEX_PATH, "源 novel_index.json")
    return _validated_optional_file(
        _INDEX_PATH, PROJECT_ROOT, "源 novel_index.json"
    )


def _load_novel_index():
    index_path = _validated_novel_index_path()
    if index_path is not None:
        index_path = _validated_file_for_read(
            index_path, PROJECT_ROOT, "源 novel_index.json"
        )
        with index_path.open("r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def _load_rhythm_data(genre, book_name):
    """Load rhythm CSV for a book, return {ch_num: dict}."""
    csv_path = _rhythm_csv_path(genre, book_name)
    csv_path = _validated_optional_file(csv_path, PROJECT_ROOT, "节奏 CSV")
    if csv_path is None:
        return {}
    data = {}
    csv_path = _validated_file_for_read(csv_path, PROJECT_ROOT, "节奏 CSV")
    with csv_path.open("r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            ch = int(row.get("ch_num", 0))
            data[ch] = {
                "wc": int(row.get("wc", 0)),
                "emotion": row.get("emotion", ""),
                "pace": row.get("pace", ""),
                "conflict": row.get("conflict", ""),
                "conflict_level": row.get("conflict_level", ""),
                "pleasure_type": row.get("pleasure_type", ""),
                "dominant_sub": row.get("dominant_sub", ""),
                "hook_type": row.get("hook_type", ""),
                "dialogue_ratio": float(row.get("dialogue_ratio", 0)),
                "pos_density": float(row.get("pos_density", 0)),
                "conflict_density": float(row.get("conflict_density", 0)),
                "hook_density": float(row.get("hook_density", 0)),
                "readability": float(row.get("readability", 0)),
            }
    return data


def _jieba_tokenize(text):
    """jieba 精确模式分词 + 停用词过滤 + 长度过滤。

    用于 BM25 通道的文档/查询分词。
    """
    tokens = jieba.lcut(text, cut_all=False, HMM=True)
    return [t for t in tokens if t not in _STOP_WORDS and len(t.strip()) >= 2]


def _split_scenes(text, min_chars=_MIN_SCENE_CHARS, max_chars=_MAX_SCENE_CHARS):
    """Split text into scenes based on paragraph groups.

    Algorithm:
      1. Split on double newlines → paragraph groups
      2. Merge groups < min_chars with neighbors
      3. Split groups > max_chars on sentence boundaries
    """
    # Step 1: split on paragraph boundaries
    raw_groups = re.split(r"\n\s*\n", text.strip())

    # Step 2: merge small groups
    groups = []
    buf = ""
    for g in raw_groups:
        g = g.strip()
        if not g:
            continue
        if len(buf) + len(g) < _MERGE_MIN_CHARS or len(g) < _MERGE_MIN_CHARS:
            buf += "\n\n" + g if buf else g
        else:
            if buf:
                groups.append(buf.strip())
            buf = g
    if buf:
        groups.append(buf.strip())

    # Step 3: split large groups
    scenes = []
    for g in groups:
        if len(g) <= max_chars:
            if g:
                scenes.append(g)
        else:
            # Split on sentence boundaries
            sentences = re.split(r"(?<=[。！？!?])\s*", g)
            chunk = ""
            for s in sentences:
                if len(chunk) + len(s) > max_chars and len(chunk) >= min_chars:
                    scenes.append(chunk.strip())
                    chunk = s
                else:
                    chunk += s
            if chunk.strip():
                scenes.append(chunk.strip())

    return scenes


def _tokenizer_input_ids(tokenizer: Any, text: str) -> list:
    """以不截断方式读取 tokenizer 的 input_ids。"""
    encoded = tokenizer(
        text,
        add_special_tokens=True,
        truncation=False,
    )
    if not hasattr(encoded, "__contains__") or "input_ids" not in encoded:
        raise IndexNotReadyError("BGE tokenizer 未返回 input_ids")
    input_ids = encoded["input_ids"]
    if input_ids and isinstance(input_ids[0], (list, tuple)):
        input_ids = input_ids[0]
    if not isinstance(input_ids, (list, tuple)):
        raise IndexNotReadyError("BGE tokenizer 的 input_ids 格式无效")
    return list(input_ids)


def _token_count(tokenizer: Any, text: str) -> int:
    """计算包含特殊 token 的长度，明确禁止 tokenizer 截断。"""
    return len(_tokenizer_input_ids(tokenizer, text))


def _split_scene_by_tokens(
    scene_text: str,
    tokenizer: Any,
    token_max: int,
) -> list[tuple[str, int, str]]:
    """按 tokenizer 上限确定性拆分场景，保留全部原始字符。"""
    if token_max <= 0:
        raise IndexNotReadyError("scene_search.token_max 必须是正整数")
    full_count = _token_count(tokenizer, scene_text)
    if full_count <= token_max:
        return [(scene_text, full_count, "within_token_limit")]

    parts: list[tuple[str, int, str]] = []
    start = 0
    text_length = len(scene_text)
    while start < text_length:
        remaining = scene_text[start:]
        remaining_count = _token_count(tokenizer, remaining)
        if remaining_count <= token_max:
            parts.append((remaining, remaining_count, "token_aware_character"))
            break

        low, high = 1, len(remaining)
        best_end = 0
        best_count = 0
        while low <= high:
            middle = (low + high) // 2
            count = _token_count(tokenizer, remaining[:middle])
            if count <= token_max:
                best_end = middle
                best_count = count
                low = middle + 1
            else:
                high = middle - 1
        if best_end == 0:
            raise IndexNotReadyError(
                "BGE tokenizer 无法为场景找到不超过 token_max 的非空片段"
            )

        paragraph_end = 0
        for match in re.finditer(r"\n\s*\n", remaining[:best_end]):
            paragraph_end = match.end()
        if paragraph_end > 0:
            cut_end = paragraph_end
            cut_count = _token_count(tokenizer, remaining[:cut_end])
            reason = "token_aware_paragraph"
        else:
            cut_end = best_end
            cut_count = best_count
            reason = "token_aware_character"
        parts.append((remaining[:cut_end], cut_count, reason))
        start += cut_end

    if not parts or "".join(part[0] for part in parts) != scene_text:
        raise IndexNotReadyError("token-aware 场景拆分未保留完整正文")
    return parts


def _analyze_scene_technique(rhythm_data):
    """Generate human-readable technique analysis from rhythm stats."""
    parts = []

    # Emotion
    emotion = rhythm_data.get("emotion", "")
    if emotion in _EMOTION_LABELS:
        parts.append(_EMOTION_LABELS[emotion])

    # Pace
    pace = rhythm_data.get("pace", "")
    if pace in _PACE_LABELS:
        parts.append(_PACE_LABELS[pace])

    # Conflict
    conflict_level = rhythm_data.get("conflict_level", "")
    if conflict_level == "high":
        parts.append("高冲突场景，外部对抗激烈")
    elif conflict_level == "medium":
        parts.append("中等冲突，有对抗但非全章高潮")

    # Pleasure type
    pt = rhythm_data.get("pleasure_type", "")
    if pt == "climax":
        parts.append("高潮爽点，读者情绪峰值")
    elif pt == "major":
        parts.append("中爽点，重要情绪释放")

    # Dominant sub-type
    sub = rhythm_data.get("dominant_sub", "")
    if sub in _TECHNIQUE_DESCRIPTIONS:
        parts.append(_TECHNIQUE_DESCRIPTIONS[sub])

    # Dialogue
    dr = rhythm_data.get("dialogue_ratio", 0)
    if dr > 0.4:
        parts.append(f"对话密集型场景(对话占比{dr:.0%})")
    elif dr < 0.1:
        parts.append(f"叙述密集型场景(对话占比{dr:.0%})")

    # Hook
    hook = rhythm_data.get("hook_type", "")
    if hook and hook != "none":
        parts.append(f"章末钩子类型: {hook}")

    return "；".join(parts) if parts else "无明显技法特征"


def _build_scene_metadata(
    book_name,
    ch_num,
    scene_idx,
    scene_text,
    rhythm_data,
    *,
    parent_scene_index=None,
    sub_scene_index=0,
    token_count=0,
    split_reason="within_token_limit",
):
    """Build metadata dict for a single scene."""
    return {
        "book_name": book_name,
        "chapter": ch_num,
        "scene_index": scene_idx,
        "parent_scene_index": scene_idx if parent_scene_index is None else parent_scene_index,
        "sub_scene_index": sub_scene_index,
        "token_count": token_count,
        "split_reason": split_reason,
        "text_preview": scene_text[:200],
        "char_count": len(scene_text),
        "emotion": rhythm_data.get("emotion", ""),
        "pace": rhythm_data.get("pace", ""),
        "conflict_level": rhythm_data.get("conflict_level", ""),
        "pleasure_type": rhythm_data.get("pleasure_type", ""),
        "dominant_sub": rhythm_data.get("dominant_sub", ""),
        "hook_type": rhythm_data.get("hook_type", ""),
        "dialogue_ratio": rhythm_data.get("dialogue_ratio", 0),
        "technique_summary": _analyze_scene_technique(rhythm_data),
    }


def _rrf_fuse(bm25_rank_indices, bge_rank_indices, k=_RRF_K):
    """Reciprocal Rank Fusion (RRF) 融合两路检索排名。

    公式: score(d) = Σ_i 1/(k + rank_i(d))
    其中 rank_i(d) 是文档 d 在第 i 路检索中的排名 (1-based), k=60 (工业标准).

    Args:
        bm25_rank_indices: list[int] — BM25 通道的文档索引 (按相关性降序)
        bge_rank_indices:  list[int] — BGE 通道的文档索引 (按相关性降序)
        k: int — RRF 平滑参数, 默认 60

    Returns:
        list[int] — 融合后文档索引 (按融合分数降序)
    """
    scores = {}
    for rank, idx in enumerate(bm25_rank_indices, start=1):
        scores[idx] = scores.get(idx, 0.0) + 1.0 / (k + rank)
    for rank, idx in enumerate(bge_rank_indices, start=1):
        scores[idx] = scores.get(idx, 0.0) + 1.0 / (k + rank)
    # 按融合分数降序
    fused = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    return [idx for idx, _ in fused]


def _publish_staged_artifacts(
    staging: Path,
    cache: Path,
    cache_parent: Path,
    backup_dir: Optional[Path] = None,
) -> None:
    """在已持有跨进程锁时发布 staging，并在受控失败时恢复旧载荷。"""
    names = ("bm25_index.pkl", "bge_embeddings.npy", "metadata.json", "manifest.json")
    backup_root = backup_dir or (staging / ".publish-backup")
    _reject_reparse_ancestors(backup_root, "索引发布备份")
    backup_root.mkdir(parents=True, exist_ok=True)
    _reject_contained_path(backup_root, backup_root.parent, "索引发布备份")

    existed: dict[str, bool] = {}
    publish_error: BaseException | None = None
    rollback_failed = False
    try:
        for name in names:
            target = cache / name
            _reject_reparse_ancestors(target, "索引缓存")
            existed[name] = target.exists()
            if existed[name]:
                backup = backup_root / name
                shutil.copy2(target, backup)
                _reject_reparse_file(backup, backup_root, "索引发布备份")

        for name in names[:-1]:
            source = staging / name
            target = cache / name
            _reject_reparse_file(source, staging, "索引 staging")
            _reject_contained_path(cache, cache_parent, "索引缓存")
            os.replace(source, target)
        source = staging / names[-1]
        target = cache / names[-1]
        _reject_reparse_file(source, staging, "索引 staging")
        _reject_contained_path(cache, cache_parent, "索引缓存")
        os.replace(source, target)
    except Exception as exc:
        publish_error = exc
        rollback_errors: list[str] = []
        for name in reversed(names):
            target = cache / name
            backup = backup_root / name
            try:
                if existed.get(name, False) and backup.is_file():
                    os.replace(backup, target)
                elif not existed.get(name, False) and target.exists():
                    target.unlink()
            except OSError as rollback_exc:
                rollback_errors.append(f"{name}: {rollback_exc}")
        if rollback_errors:
            rollback_failed = True
            raise IndexPublishRollbackError(
                "索引发布失败且回滚失败："
                + "; ".join(rollback_errors)
                + f"；原始错误：{exc}；备份保留于：{backup_root}"
            ) from exc
        raise
    finally:
        if not rollback_failed:
            try:
                shutil.rmtree(backup_root)
            except OSError as cleanup_exc:
                if publish_error is None:
                    raise IndexStagingCleanupError(
                        f"索引发布备份清理失败：{backup_root}：{cleanup_exc}"
                    ) from cleanup_exc
                raise IndexPublishRollbackError(
                    f"索引发布失败且备份清理失败：{backup_root}：{cleanup_exc}；"
                    f"原始错误：{publish_error}"
                ) from publish_error


class SceneSearch:
    """场景级写作参考检索引擎 (v3 混合检索版本)。

    双通道并行检索 + RRF 融合:
      - 通道A (BM25): 关键词精确匹配, 词频饱和 + 长度归一化
      - 通道B (BGE):  语义相似度, 弥补同义词/抽象查询场景
      - 融合 (RRF):   倒数排名融合, k=60

    v2→v3 变更:
      - 修正 v2 时期基于错误"硬约束"幻觉移除 BGE 的决策
      - 引入 BM25 通道替代 TF-IDF (词频饱和 + 长度归一化)
      - 恢复 BGE 通道 (语义检索, 弥补同义词/抽象查询)
      - 新增 RRF 融合层 (工业标准, BEIR 基准 +5-15% NDCG@10)
      - 缓存格式: bm25_index.pkl + bge_embeddings.npy + metadata.json
      - 公共接口签名完全保留, 调用方无需改动

    Usage:
        ss = SceneSearch("末世")
        ss.build_index()           # 首次使用需构建索引
        results = ss.search("拍卖场冲突", top_k=5)
        for r in results:
            print(r["book_name"], r["technique_summary"])
    """

    def __init__(
        self,
        genre="末世",
        resource_guard: Optional[Callable[[], None]] = None,
        cache_dir: Optional[Path | str] = None,
        cache_root: Optional[Path | str] = None,
    ):
        _validate_genre_component(genre)
        self.genre = genre
        cfg = get_config()
        ss_cfg = cfg.get("scene_search", {})
        self.method = ss_cfg.get("method", "hybrid_bm25_bge")
        self.top_k = ss_cfg.get("top_k", 5)
        self.embedding_model_name = ss_cfg.get("embedding_model", _DEFAULT_BGE_MODEL)
        self.embedding_model_path = Path(str(ss_cfg.get("model_local_path", ""))).expanduser()
        self.offline = ss_cfg.get("offline", True)
        self.manifest_schema_version = int(ss_cfg.get("manifest_schema_version", 1))
        self.min_scene_chars = int(ss_cfg.get("min_scene_chars", _MIN_SCENE_CHARS))
        self.max_scene_chars = int(ss_cfg.get("max_scene_chars", _MAX_SCENE_CHARS))
        self.token_max = int(ss_cfg.get("token_max", 510))
        self.rrf_k = int(ss_cfg.get("rrf_k", _RRF_K))
        self.jieba_cache_dir = Path(str(ss_cfg.get(
            "jieba_cache_dir", "D:/tmp/yeyu-ai-a3/mpv-02b-runtime/jieba"
        ))).expanduser()
        _configure_jieba_cache(self.jieba_cache_dir)
        self._config_error: Optional[str] = None
        cache_template = ss_cfg.get("cache_dir")
        try:
            if cache_template:
                cache_path = Path(str(cache_template).format(genre=genre)).expanduser()
                cache_path = cache_path if cache_path.is_absolute() else PROJECT_ROOT / cache_path
            else:
                cache_path = _cache_dir(genre)
            self._cache = _resolve_project_cache_path(cache_path)
        except (IndexNotReadyError, KeyError, ValueError) as exc:
            self._config_error = str(exc)
            self._cache = _cache_dir(genre).resolve(strict=False)
        self._formal_cache = self._cache
        self._cache_boundary = PROJECT_ROOT.resolve(strict=True)
        self._explicit_cache_dir = cache_dir is not None
        if cache_dir is not None:
            if cache_root is None:
                raise IndexNotReadyError("显式索引缓存必须提供 cache_root")
            self._cache_boundary = Path(cache_root).absolute().resolve(strict=True)
            self._cache = _resolve_cache_path(
                Path(cache_dir).absolute(), self._cache_boundary, "实验索引缓存"
            )
        self._state_lock = threading.RLock()
        # BM25 状态
        self._bm25: Optional[BM25Okapi] = None
        self._tokenized_corpus: list = []
        # BGE 状态
        self._bge_model: Optional[Any] = None
        self._resource_guard = resource_guard
        self._bge_embeddings: Optional[np.ndarray] = None  # (N, 512)
        # 共享状态
        self._metadata: list = []
        self._loaded_build_limit: Optional[int] = None

    def _clear_loaded_state(self) -> None:
        """发布失败时清空旧内存索引，避免绕过磁盘合同继续服务。"""
        self._bm25 = None
        self._tokenized_corpus = []
        self._bge_embeddings = None
        self._metadata = []
        self._loaded_build_limit = None

    # ── BGE 模型懒加载 ──

    def _get_bge_model(self):
        """懒加载 D 盘本地 BGE 模型，禁止联网回退。"""
        with self._state_lock:
            if self._bge_model is None:
                if self._resource_guard is not None:
                    self._resource_guard()
                model_path = self._validated_model_path()
                try:
                    from sentence_transformers import SentenceTransformer

                    print(f"  [BGE] 加载本地模型 {model_path} ...")
                    self._bge_model = SentenceTransformer(
                        str(model_path),
                        cache_folder=str(_BGE_CACHE_DIR),
                        local_files_only=True,
                    )
                except IndexNotReadyError:
                    raise
                except Exception as exc:
                    raise EmbeddingModelError(f"BGE 模型加载失败：{exc}") from exc
                if self._resource_guard is not None:
                    self._resource_guard()
                try:
                    dimension = self._bge_model.get_sentence_embedding_dimension()
                    print(f"  [BGE] 模型就绪, dim={dimension}")
                except Exception as exc:
                    raise EmbeddingModelError(f"BGE 模型能力检查失败：{exc}") from exc
            return self._bge_model

    def _validated_model_path(self) -> Path:
        """校验模型目录在 D 盘且具备 SentenceTransformer 最小文件集。"""
        path = self.embedding_model_path
        required = ("config.json", "tokenizer_config.json")
        weights = (path / "model.safetensors", path / "pytorch_model.bin")
        if self._config_error:
            raise IndexNotReadyError(self._config_error)
        if self.offline is not True:
            raise IndexNotReadyError("scene_search.offline 必须严格为 true")
        if not path.is_absolute() or path.drive.upper() != "D:":
            raise IndexNotReadyError("BGE 模型必须位于 D 盘本地目录")
        _reject_reparse_ancestors(path, "BGE 模型")
        if not path.is_dir():
            raise IndexNotReadyError("D 盘 BGE 模型目录不完整")
        model_root = path.resolve(strict=True)
        for name in required:
            _validated_file_for_read(path / name, model_root, "BGE 模型")
        valid_weights = [
            weight for weight in weights
            if _validated_optional_file(weight, model_root, "BGE 模型") is not None
        ]
        if not valid_weights:
            raise IndexNotReadyError("D 盘 BGE 模型缺少权重文件")
        return path

    def _model_identity(self) -> dict[str, Any]:
        path = self._validated_model_path()
        config_path = path / "config.json"
        model_root = path.resolve(strict=True)
        config_path = _validated_file_for_read(config_path, model_root, "BGE 模型")
        tokenizer_config_path = _validated_file_for_read(
            path / "tokenizer_config.json", model_root, "BGE 模型"
        )
        weight = next(
            item for item in (path / "model.safetensors", path / "pytorch_model.bin")
            if _validated_optional_file(item, model_root, "BGE 模型") is not None
        )
        weight = _validated_file_for_read(weight, model_root, "BGE 模型")
        return {
            "model_id": self.embedding_model_name,
            "model_local_path": path.as_posix(),
            "model_config_sha256": _validated_sha256_file(config_path, model_root, "BGE 模型"),
            "model_tokenizer_config_sha256": _validated_sha256_file(
                tokenizer_config_path, model_root, "BGE 模型"
            ),
            "model_weight_file": weight.name,
            "model_weight_bytes": _validated_file_size(
                weight, model_root, "BGE 模型"
            ),
            "model_weight_sha256": _validated_sha256_file(weight, model_root, "BGE 模型"),
        }

    def _bge_encode(
        self,
        texts,
        batch_size=32,
        show_progress=False,
        on_progress: Optional[BuildProgressCallback] = None,
    ):
        """文本 → BGE 嵌入向量 (L2 归一化, 便于 cosine 相似度)."""
        model = self._get_bge_model()
        if on_progress is None:
            try:
                embeddings = model.encode(
                    texts,
                    batch_size=batch_size,
                    show_progress_bar=show_progress,
                    normalize_embeddings=True,  # L2 归一化, dot product = cosine
                    convert_to_numpy=True,
                )
            except Exception as exc:
                raise EmbeddingModelError(f"BGE 向量编码失败：{exc}") from exc
            return embeddings.astype(np.float32, copy=False)

        encoded_batches = []
        total = len(texts)
        for start in range(0, total, 100):
            batch = texts[start:start + 100]
            try:
                encoded_batches.append(model.encode(
                    batch,
                    batch_size=batch_size,
                    show_progress_bar=False,
                    normalize_embeddings=True,
                    convert_to_numpy=True,
                ))
            except Exception as exc:
                raise EmbeddingModelError(f"BGE 向量编码失败：{exc}") from exc
            _notify_progress(
                on_progress, "encode", min(start + len(batch), total), total
            )
        if not encoded_batches:
            return np.empty((0, 0), dtype=np.float32)
        return np.concatenate(encoded_batches, axis=0).astype(np.float32, copy=False)

    def _tokenizer_contract(self) -> tuple[Any, int]:
        """读取本地 BGE tokenizer 的真实窗口并校验配置上限。"""
        model = self._get_bge_model()
        tokenizer = getattr(model, "tokenizer", None)
        if tokenizer is None:
            raise IndexNotReadyError("BGE 模型未提供 tokenizer")
        limits = []
        for owner in (model, tokenizer):
            value = getattr(owner, "max_seq_length", None)
            if value is None:
                value = getattr(owner, "model_max_length", None)
            if isinstance(value, int) and not isinstance(value, bool) and 0 < value < 1_000_000:
                limits.append(value)
        if not limits:
            raise IndexNotReadyError("无法读取 BGE tokenizer 的最大序列长度")
        tokenizer_max_length = min(limits)
        if self.token_max <= 0:
            raise IndexNotReadyError("scene_search.token_max 必须是正整数")
        if self.token_max > tokenizer_max_length:
            raise IndexNotReadyError(
                "scene_search.token_max 不得超过 BGE tokenizer 最大序列长度"
            )
        return tokenizer, tokenizer_max_length

    # ── 索引构建 ──

    @contextmanager
    def _filesystem_lock(self):
        """跨进程锁住同一题材的索引发布，避免读到交叉写入状态。"""
        if self._config_error:
            raise IndexNotReadyError(self._config_error)
        if self.offline is not True:
            raise IndexNotReadyError("scene_search.offline 必须严格为 true")
        if self.method != "hybrid_bm25_bge":
            raise IndexNotReadyError(f"不支持的 scene_search.method：{self.method}")
        lock_path = self._cache.parent / f".{self._cache.name}.lock"
        _reject_contained_path(self._cache.parent, self._cache_boundary, "索引缓存")
        if not self._cache.parent.is_dir():
            raise IndexNotReadyError("索引目录尚未建立，请先执行索引构建")
        safe_lock_path = _validated_optional_file(
            lock_path, self._cache_boundary, "索引锁"
        ) or lock_path
        try:
            with safe_lock_path.open("a+b") as handle:
                handle.seek(0, os.SEEK_END)
                if handle.tell() == 0:
                    handle.write(b"0")
                    handle.flush()
                handle.seek(0)
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
                    try:
                        yield
                    finally:
                        handle.seek(0)
                        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                    try:
                        yield
                    finally:
                        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        except OSError as exc:
            raise IndexNotReadyError("索引文件锁不可用") from exc

    def _validate_method(self) -> None:
        if self._config_error:
            raise IndexNotReadyError(self._config_error)
        if self.offline is not True:
            raise IndexNotReadyError("scene_search.offline 必须严格为 true")
        if self.method != "hybrid_bm25_bge":
            raise IndexNotReadyError(f"不支持的 scene_search.method：{self.method}")

    def build_index(
        self,
        force=False,
        limit=0,
        on_progress: Optional[BuildProgressCallback] = None,
        publish_backup_dir: Optional[Path] = None,
        staging_dir: Optional[Path] = None,
    ):
        """在进程内和跨进程锁内构建或加载索引。"""
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 0:
            raise IndexNotReadyError("索引构建 limit 必须是非负整数")
        if on_progress is not None and not callable(on_progress):
            raise IndexNotReadyError("索引构建 on_progress 必须是可调用对象")
        self._validate_method()
        if self._explicit_cache_dir:
            self._cache = _resolve_cache_path(
                self._cache, self._cache_boundary, "实验索引缓存"
            )
        elif limit > 0:
            sample_cache = self._formal_cache.parent / f"{self._formal_cache.name}.sample"
            self._cache = _resolve_project_cache_path(sample_cache)
        else:
            self._cache = self._formal_cache
        self._cache.parent.mkdir(parents=True, exist_ok=True)
        _reject_reparse_ancestors(self._cache.parent, "索引缓存")
        with self._state_lock:
            with self._filesystem_lock():
                if on_progress is None and publish_backup_dir is None and staging_dir is None:
                    return self._build_index_unlocked(force=force, limit=limit)
                return self._build_index_unlocked(
                    force=force,
                    limit=limit,
                    on_progress=on_progress,
                    publish_backup_dir=publish_backup_dir,
                    staging_dir=staging_dir,
                )

    def _collect_corpus(
        self,
        limit=0,
        tokenizer=None,
        on_progress: Optional[BuildProgressCallback] = None,
    ):
        """读取当前语料并返回构建结果与可复算的源快照。"""
        index_path = _validated_novel_index_path()
        if index_path is None:
            raise IndexNotReadyError("源 novel_index.json 不存在")
        novel_index = _load_novel_index()
        genre_novels = novel_index.get("genres", {}).get(self.genre, {}).get("novels", [])
        if not genre_novels:
            _notify_progress(on_progress, "collect", 0, 0)
            return (
                [], [], [("data/raw/novel_index.json", _validated_sha256_file(
                    index_path, PROJECT_ROOT, "源 novel_index.json"
                ))],
                0, 0, 0, [],
            )

        all_scenes = []
        all_metadata = []
        source_entries = [("data/raw/novel_index.json", _validated_sha256_file(
            index_path, PROJECT_ROOT, "源 novel_index.json"
        ))]
        book_count = 0
        oversized_scene_count = 0
        sub_scene_count = 0
        book_reports = []
        for novel in genre_novels:
            book_name = novel.get("file", "").replace(".txt", "")
            book_report = {
                "book_name": book_name,
                "indexed": False,
                "chapter_count": 0,
                "max_chapter_chars": 0,
                "total_chapter_chars": 0,
                "abnormal_chapter_count": 0,
            }
            book_reports.append(book_report)
            novel_path = _novel_source_path(self.genre, novel.get("file", ""))
            novel_path = _validated_optional_file(
                novel_path, PROJECT_ROOT, "小说源文件"
            )
            if novel_path is None:
                book_report["abnormal_chapter_count"] = 1
                continue
            rhythm_data = _load_rhythm_data(self.genre, book_name)
            if not rhythm_data:
                book_report["abnormal_chapter_count"] = 1
                continue
            source_entries.append((
                str(novel_path.relative_to(PROJECT_ROOT)).replace("\\", "/"),
                _validated_sha256_file(novel_path, PROJECT_ROOT, "小说源文件"),
            ))
            rhythm_path = _rhythm_csv_path(self.genre, book_name)
            rhythm_path = _validated_optional_file(
                rhythm_path, PROJECT_ROOT, "节奏 CSV"
            )
            if rhythm_path is None:
                continue
            source_entries.append((
                str(rhythm_path.relative_to(PROJECT_ROOT)).replace("\\", "/"),
                _validated_sha256_file(rhythm_path, PROJECT_ROOT, "节奏 CSV"),
            ))
            try:
                novel_path = _validated_file_for_read(
                    novel_path, PROJECT_ROOT, "小说源文件"
                )
                chapters = extract_chapters(str(novel_path))
            except Exception as exc:
                print(f"  [WARN] 跳过 {book_name}: 章节抽取失败 {exc}")
                book_report["abnormal_chapter_count"] = 1
                continue
            for chapter in chapters:
                ch_num = chapter.get("num", 0)
                ch_text = chapter.get("raw_body")
                book_report["chapter_count"] += 1
                if not isinstance(ch_text, str):
                    book_report["abnormal_chapter_count"] += 1
                    raise CorpusContractError(
                        f"{book_name} 第{ch_num}章缺少字符串 raw_body"
                    )
                book_report["max_chapter_chars"] = max(
                    book_report["max_chapter_chars"], len(ch_text)
                )
                book_report["total_chapter_chars"] += len(ch_text)
                ch_rhythm = rhythm_data.get(ch_num, {})
                scenes = _split_scenes(ch_text, self.min_scene_chars, self.max_scene_chars)
                for scene_idx, scene_text in enumerate(scenes):
                    if tokenizer is None:
                        scene_parts = [(scene_text, 0, "token_count_deferred")]
                    else:
                        scene_parts = _split_scene_by_tokens(
                            scene_text, tokenizer, self.token_max
                        )
                    if len(scene_parts) > 1:
                        oversized_scene_count += 1
                        sub_scene_count += len(scene_parts)
                    for sub_scene_idx, (part_text, token_count, split_reason) in enumerate(scene_parts):
                        all_scenes.append(part_text)
                        all_metadata.append(
                            _build_scene_metadata(
                                book_name,
                                ch_num,
                                scene_idx,
                                part_text,
                                ch_rhythm,
                                parent_scene_index=scene_idx,
                                sub_scene_index=sub_scene_idx,
                                token_count=token_count,
                                split_reason=split_reason,
                            )
                        )
            book_report["indexed"] = True
            book_count += 1
            _notify_progress(on_progress, "collect", book_count, len(genre_novels))
            if book_count % 5 == 0:
                print(f"  [OK] 已处理 {book_count}/{len(genre_novels)} 本...")
            if limit > 0 and book_count >= limit:
                break
        return (
            all_scenes,
            all_metadata,
            source_entries,
            book_count,
            oversized_scene_count,
            sub_scene_count,
            book_reports,
        )

    def _build_index_unlocked(
        self,
        force=False,
        limit=0,
        on_progress: Optional[BuildProgressCallback] = None,
        publish_backup_dir: Optional[Path] = None,
        staging_dir: Optional[Path] = None,
    ):
        """Build scene search index from all novels in the genre.

        Args:
            force: if True, rebuild even if cache exists
            limit: max books to process (0 = all)
        """
        model_identity = self._model_identity()

        cache_files = tuple(
            self._cache / name
            for name in ("bm25_index.pkl", "bge_embeddings.npy", "metadata.json", "manifest.json")
        )
        cache_ready = all(
            _validated_optional_file(path, self._cache_boundary, "索引缓存") is not None
            for path in cache_files
        )
        if not force and cache_ready:
            self._load_cache_unlocked(expected_limit=limit)
            print(f"[OK] 从缓存加载索引: {len(self._metadata)} 个场景")
            return len(self._metadata)

        self._cache.mkdir(parents=True, exist_ok=True)
        cache_parent = self._cache.parent.resolve(strict=True)
        _reject_contained_path(self._cache, cache_parent, "索引缓存")
        tokenizer, tokenizer_max_length = self._tokenizer_contract()
        (
            all_scenes,
            all_metadata,
            source_entries,
            book_count,
            oversized_scene_count,
            sub_scene_count,
            book_reports,
        ) = (
            self._collect_corpus(limit=limit, tokenizer=tokenizer)
            if on_progress is None
            else self._collect_corpus(
                limit=limit, tokenizer=tokenizer, on_progress=on_progress
            )
        )
        if not all_scenes:
            print(f"[FAIL] 题材 '{self.genre}' 无入库小说")
            return 0

        n_scenes = len(all_scenes)
        index_path = _validated_novel_index_path()
        if index_path is None:
            raise IndexNotReadyError("源 novel_index.json 不存在")
        print(f"[OK] 切分完成: {n_scenes} 个场景, 开始构建双通道索引...")

        # 通道A: BM25 索引 (jieba 分词)
        print(f"  [BM25] 分词 + 索引构建...")
        _notify_progress(on_progress, "tokenize", 0, n_scenes)
        tokenized_corpus = []
        for index, scene in enumerate(all_scenes, start=1):
            tokenized_corpus.append(_jieba_tokenize(scene))
            if index % 100 == 0 or index == n_scenes:
                _notify_progress(on_progress, "tokenize", index, n_scenes)
        bm25 = BM25Okapi(tokenized_corpus)
        print(f"  [BM25] 索引就绪, 词表规模={len(bm25.get_scores(tokenized_corpus[0] if tokenized_corpus else ['']))}")

        # 通道B: BGE 嵌入
        print(f"  [BGE] 嵌入 {n_scenes} 个场景...")
        _notify_progress(on_progress, "encode", 0, n_scenes)
        bge_embeddings = self._bge_encode(
            all_scenes,
            show_progress=False,
            on_progress=on_progress,
        )
        _notify_progress(on_progress, "encode", n_scenes, n_scenes)
        print(f"  [BGE] 嵌入矩阵 shape={bge_embeddings.shape}")
        if (bge_embeddings.ndim != 2 or bge_embeddings.shape[0] != n_scenes
                or bge_embeddings.dtype != np.float32
                or not np.isfinite(bge_embeddings).all()):
            raise IndexNotReadyError("模型生成的向量矩阵无效")

        # worker 批次将 staging 放在 D 盘 run 目录，避免向项目工作区写临时载荷。
        staging_root = (staging_dir or self._cache.parent).absolute()
        _reject_reparse_ancestors(staging_root, "索引 staging 根")
        staging_root.mkdir(parents=True, exist_ok=True)
        staging_root = staging_root.resolve(strict=True)
        staging = staging_root / f".{self._cache.name}.staging-{uuid.uuid4().hex}"
        cache_bm25 = staging / "bm25_index.pkl"
        cache_bge = staging / "bge_embeddings.npy"
        cache_meta = staging / "metadata.json"
        cache_manifest = staging / "manifest.json"
        build_error: BaseException | None = None
        try:
            _notify_progress(on_progress, "publish", 0, 1)
            staging.mkdir(parents=True, exist_ok=False)
            _reject_contained_path(staging, staging_root, "索引 staging")
            with cache_bm25.open("wb") as handle:
                pickle.dump({"bm25": bm25, "tokenized_corpus": tokenized_corpus}, handle)
            _reject_contained_path(staging, staging_root, "索引 staging")
            np.save(str(cache_bge), bge_embeddings)
            _reject_contained_path(staging, staging_root, "索引 staging")
            with cache_meta.open("w", encoding="utf-8") as handle:
                json.dump(all_metadata, handle, ensure_ascii=False, indent=2)

            _reject_reparse_file(cache_bm25, staging, "索引 staging")
            _reject_reparse_file(cache_bge, staging, "索引 staging")
            _reject_reparse_file(cache_meta, staging, "索引 staging")

            manifest = {
                "schema_version": self.manifest_schema_version,
                "genre": self.genre,
                "embedding_model": model_identity["model_id"],
                "model_local_path": model_identity["model_local_path"],
                "model_config_sha256": model_identity["model_config_sha256"],
                "model_tokenizer_config_sha256": model_identity["model_tokenizer_config_sha256"],
                "model_weight_file": model_identity["model_weight_file"],
                "model_weight_bytes": model_identity["model_weight_bytes"],
                "model_weight_sha256": model_identity["model_weight_sha256"],
                "embedding_dim": int(bge_embeddings.shape[1]),
                "method": self.method,
                "offline": self.offline,
                "min_scene_chars": self.min_scene_chars,
                "max_scene_chars": self.max_scene_chars,
                "merge_min_chars": _MERGE_MIN_CHARS,
                "rrf_k": self.rrf_k,
                "build_scope": "full" if limit == 0 else "sample",
                "source_novel_index_sha256": _validated_sha256_file(
                    index_path, PROJECT_ROOT, "源 novel_index.json"
                ),
                "source_corpus_sha256": _digest_entries(source_entries),
                "build_limit": limit,
                "n_books": book_count,
                "n_scenes": n_scenes,
                "corpus_total_chars": _reported_corpus_chars(book_reports),
                "tokenizer_max_length": tokenizer_max_length,
                "token_max": self.token_max,
                "truncate_strategy": "split_no_silent_truncate",
                "oversized_scene_count": oversized_scene_count,
                "sub_scene_count": sub_scene_count,
                "book_reports": book_reports,
                "artifacts": {
                    "bm25_index.pkl": _validated_sha256_file(
                        cache_bm25, staging, "索引 staging"
                    ),
                    "bge_embeddings.npy": _validated_sha256_file(
                        cache_bge, staging, "索引 staging"
                    ),
                    "metadata.json": _validated_sha256_file(
                        cache_meta, staging, "索引 staging"
                    ),
                },
            }
            with cache_manifest.open("w", encoding="utf-8") as handle:
                json.dump(manifest, handle, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
            _reject_reparse_file(cache_manifest, staging, "索引 staging")
            _publish_staged_artifacts(
                staging,
                self._cache,
                cache_parent,
                backup_dir=publish_backup_dir,
            )
            _notify_progress(on_progress, "publish", 1, 1)
        except BaseException as exc:
            build_error = exc
            self._clear_loaded_state()
            raise
        finally:
            cleanup_errors: list[str] = []
            try:
                _notify_progress(on_progress, "cleanup", 0, 1)
            except BaseException as cleanup_exc:
                cleanup_errors.append(f"cleanup 开始事件失败：{cleanup_exc}")
            if staging.exists():
                try:
                    shutil.rmtree(staging)
                except OSError as cleanup_exc:
                    cleanup_errors.append(f"索引 staging 清理失败：{staging}：{cleanup_exc}")
            try:
                _notify_progress(on_progress, "cleanup", 1, 1)
            except BaseException as cleanup_exc:
                cleanup_errors.append(f"cleanup 完成事件失败：{cleanup_exc}")
            if cleanup_errors:
                cleanup_message = "；".join(cleanup_errors)
                if build_error is None:
                    raise IndexStagingCleanupError(cleanup_message)
                setattr(build_error, "cleanup_error", cleanup_message)

        self._bm25 = bm25
        self._tokenized_corpus = tokenized_corpus
        self._bge_embeddings = bge_embeddings
        self._metadata = all_metadata
        self._loaded_build_limit = limit

        print(f"[OK] 索引构建完成: {len(all_metadata)} 场景, {book_count} 本书")
        return len(all_metadata)

    def _load_cache(self):
        """在锁内校验并加载 BM25、BGE、元数据和 manifest。"""
        with self._state_lock:
            with self._filesystem_lock():
                self._load_cache_unlocked(expected_limit=0)

    def _load_cache_unlocked(self, expected_limit=0):
        cache_bm25 = self._cache / "bm25_index.pkl"
        cache_bge = self._cache / "bge_embeddings.npy"
        cache_meta = self._cache / "metadata.json"
        cache_manifest = self._cache / "manifest.json"

        required = (cache_bm25, cache_bge, cache_meta, cache_manifest)
        if any(
            _validated_optional_file(item, self._cache_boundary, "索引") is None
            for item in required
        ):
            raise IndexNotReadyError("索引未建立，请先执行索引构建")
        cache_root = _validated_file_for_read(
            cache_manifest, self._cache_boundary, "索引 manifest"
        ).parent.resolve(strict=True)
        for path in required:
            _validated_file_for_read(path, cache_root, "索引")

        try:
            manifest = json.loads(cache_manifest.read_text(encoding="utf-8"))
            if not isinstance(manifest, dict):
                raise ValueError("manifest 根节点必须是对象")
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
            raise IndexNotReadyError("索引 manifest 无法读取") from exc
        if manifest.get("schema_version") != self.manifest_schema_version:
            raise IndexNotReadyError("索引 manifest schema_version 不匹配")
        required_manifest_fields = (
            "genre", "build_scope", "build_limit", "n_books", "n_scenes",
            "corpus_total_chars", "source_corpus_sha256", "tokenizer_max_length",
            "token_max", "truncate_strategy", "oversized_scene_count",
            "sub_scene_count", "book_reports", "artifacts",
        )
        if any(field not in manifest for field in required_manifest_fields):
            raise IndexNotReadyError("索引 manifest 缺少必要字段")

        model_identity = self._model_identity()
        tokenizer, tokenizer_max_length = self._tokenizer_contract()
        build_limit = manifest.get("build_limit")
        nonnegative_fields = (
            "build_limit", "n_books", "n_scenes", "corpus_total_chars",
            "oversized_scene_count", "sub_scene_count", "model_weight_bytes",
            "embedding_dim",
        )
        for field in nonnegative_fields:
            value = manifest.get(field)
            if not _is_strict_int(value) or value < 0:
                raise IndexNotReadyError(f"索引 manifest 的 {field} 无效")
        if not _is_strict_int(manifest.get("tokenizer_max_length")):
            raise IndexNotReadyError("索引 manifest 的 tokenizer_max_length 无效")
        if not _is_strict_int(manifest.get("token_max")) or manifest["token_max"] <= 0:
            raise IndexNotReadyError("索引 manifest 的 token_max 无效")
        if not _valid_book_reports(manifest.get("book_reports")):
            raise IndexNotReadyError("索引 manifest 的 book_reports 无效")
        if expected_limit is not None and build_limit != expected_limit:
            raise IndexNotReadyError("索引的构建范围与当前请求不一致")
        index_path = _validated_novel_index_path()
        if index_path is None:
            raise IndexNotReadyError("源 novel_index.json 不存在")
        expected = {
            "schema_version": self.manifest_schema_version,
            "genre": self.genre,
            "embedding_model": model_identity["model_id"],
            "model_local_path": model_identity["model_local_path"],
            "model_config_sha256": model_identity["model_config_sha256"],
            "model_tokenizer_config_sha256": model_identity["model_tokenizer_config_sha256"],
            "model_weight_file": model_identity["model_weight_file"],
            "model_weight_bytes": model_identity["model_weight_bytes"],
            "model_weight_sha256": model_identity["model_weight_sha256"],
            "method": self.method,
            "offline": self.offline,
            "min_scene_chars": self.min_scene_chars,
            "max_scene_chars": self.max_scene_chars,
            "merge_min_chars": _MERGE_MIN_CHARS,
            "rrf_k": self.rrf_k,
            "build_scope": "full" if build_limit == 0 else "sample",
            "source_novel_index_sha256": _validated_sha256_file(
                index_path, PROJECT_ROOT, "源 novel_index.json"
            ),
            "tokenizer_max_length": tokenizer_max_length,
            "token_max": self.token_max,
            "truncate_strategy": "split_no_silent_truncate",
        }
        if any(manifest.get(key) != value for key, value in expected.items()):
            raise IndexNotReadyError("索引 manifest 与当前模型、配置或题材不一致")

        artifacts = manifest.get("artifacts")
        if not isinstance(artifacts, dict):
            raise IndexNotReadyError("索引 manifest 缺少 artifacts 校验段")
        for path in (cache_bm25, cache_bge, cache_meta):
            if artifacts.get(path.name) != _validated_sha256_file(
                path, cache_root, "索引"
            ):
                raise IndexNotReadyError(f"索引文件校验失败：{path.name}")

        (
            _, current_metadata, source_entries, current_books,
            current_oversized_scene_count, current_sub_scene_count,
            current_book_reports,
        ) = self._collect_corpus(limit=build_limit, tokenizer=tokenizer)
        current_chars = _reported_corpus_chars(current_book_reports)
        if (manifest.get("source_corpus_sha256") != _digest_entries(source_entries)
                or manifest.get("n_books") != current_books
                or manifest.get("n_scenes") != len(current_metadata)
                or manifest.get("corpus_total_chars") != current_chars
                or manifest.get("oversized_scene_count") != current_oversized_scene_count
                or manifest.get("sub_scene_count") != current_sub_scene_count
                or manifest.get("book_reports") != current_book_reports):
            raise IndexNotReadyError("索引 manifest 与当前语料快照不一致")

        try:
            safe_bm25 = _validated_file_for_read(cache_bm25, cache_root, "索引")
            safe_bge = _validated_file_for_read(cache_bge, cache_root, "索引")
            safe_meta = _validated_file_for_read(cache_meta, cache_root, "索引")
            with safe_bm25.open("rb") as f:
                data = pickle.load(f)
            embeddings = np.load(str(safe_bge), allow_pickle=False)
            metadata = json.loads(safe_meta.read_text(encoding="utf-8"))
        except (OSError, EOFError, ValueError, TypeError, KeyError, AttributeError,
                pickle.UnpicklingError, json.JSONDecodeError) as exc:
            raise IndexNotReadyError("索引文件损坏或格式无效") from exc

        tokenized_corpus = data.get("tokenized_corpus") if isinstance(data, dict) else None
        bm25 = data.get("bm25") if isinstance(data, dict) else None
        n_scenes = manifest.get("n_scenes")
        embedding_dim = manifest.get("embedding_dim")
        valid_tokens = (isinstance(tokenized_corpus, list)
                        and all(isinstance(row, list) and all(isinstance(token, str) for token in row)
                                for row in tokenized_corpus))
        valid_metadata = (isinstance(metadata, list)
                          and all(self._valid_metadata_item(item, self.token_max)
                                  for item in metadata))
        if (bm25 is None or not callable(getattr(bm25, "get_scores", None))
                or not valid_tokens
                or not valid_metadata
                or not _is_strict_int(n_scenes) or not _is_strict_int(embedding_dim)
                or embedding_dim <= 0
                or not _is_strict_int(manifest.get("n_books"))
                or not _is_strict_int(manifest.get("corpus_total_chars"))
                or len(tokenized_corpus) != n_scenes
                or len(metadata) != n_scenes
                or embeddings.ndim != 2
                or embeddings.dtype != np.float32
                or embeddings.shape != (n_scenes, embedding_dim)):
            raise IndexNotReadyError("索引维度或场景数量与 manifest 不一致")
        if not np.isfinite(embeddings).all():
            raise IndexNotReadyError("索引向量包含非有限数值")
        try:
            bm25_corpus = getattr(bm25, "corpus")
            probe_scores = np.asarray(bm25.get_scores(["__mpv_contract_probe__"]))
        except (AttributeError, TypeError, ValueError, IndexError) as exc:
            raise IndexNotReadyError("BM25 索引结构无效") from exc
        if (not isinstance(bm25_corpus, list)
                or len(bm25_corpus) != n_scenes
                or probe_scores.shape != (n_scenes,)
                or not np.isfinite(probe_scores).all()):
            raise IndexNotReadyError("BM25 语料或评分维度无效")

        self._bm25 = bm25
        self._tokenized_corpus = tokenized_corpus
        self._bge_embeddings = embeddings
        self._metadata = metadata
        self._loaded_build_limit = build_limit

    @staticmethod
    def _valid_metadata_item(item: Any, token_max: Optional[int] = None) -> bool:
        """校验 API 会直接读取的全部 metadata 字段。"""
        if not isinstance(item, dict):
            return False
        if any(not isinstance(item.get(name), str) for name in _METADATA_STRING_FIELDS):
            return False
        if any(not isinstance(item.get(name), int) or isinstance(item.get(name), bool)
               for name in _METADATA_INT_FIELDS):
            return False
        token_count = item["token_count"]
        if token_count < 0 or (token_max is not None and token_count > token_max):
            return False
        return all(
            isinstance(item.get(name), (int, float))
            and not isinstance(item.get(name), bool)
            and np.isfinite(float(item.get(name)))
            for name in _METADATA_FLOAT_FIELDS
        )

    # ── 检索 ──

    def search(self, query, top_k=None):
        """Hybrid search: BM25 + BGE + RRF fusion.

        Args:
            query: 自然语言查询
            top_k: 返回结果数 (默认 self.top_k)

        Returns:
            list of dicts with keys:
              - book_name, chapter, scene_index
              - text_preview, char_count
              - emotion, pace, conflict_level, pleasure_type, dominant_sub
              - technique_summary
              - similarity (RRF 融合分数, 已归一化到 0-1)
              - bm25_rank, bge_rank (各通道原始排名, 1-based, 用于可解释性)
        """
        if top_k is None:
            top_k = self.top_k
        try:
            with self._state_lock:
                with self._filesystem_lock():
                    if (self._bm25 is None or self._bge_embeddings is None
                            or not self._metadata or self._loaded_build_limit is None):
                        self._load_cache_unlocked(expected_limit=0)
                    if (self._bm25 is None or self._bge_embeddings is None
                            or not self._metadata or self._loaded_build_limit != 0):
                        raise IndexNotReadyError("索引未建立，请先执行索引构建")

                    n = len(self._metadata)
                    tokenizer, _ = self._tokenizer_contract()
                    query_token_count = _token_count(tokenizer, query)
                    if query_token_count > self.token_max:
                        raise QueryTooLongError(query_token_count, self.token_max)
        # 检索深度: 取 top_n_candidate, 然后 RRF 融合后取 top_k
        # 取 5x top_k 作为候选池, 保证 RRF 融合有足够多样性
                    candidate_pool = min(max(top_k * 5, 20), n)

        # 通道A: BM25 检索
                    tokenized_query = _jieba_tokenize(query)
                    bm25_scores = self._bm25.get_scores(tokenized_query)
                    bm25_rank_indices = np.argsort(bm25_scores)[::-1][:candidate_pool]

        # 通道B: BGE 语义检索
                    query_emb = self._bge_encode([query], show_progress=False)  # (1, 512)
        # cosine 相似度 (BGE 已 L2 归一化, dot product = cosine)
                    bge_sims = (self._bge_embeddings @ query_emb[0]).ravel()
                    bge_rank_indices = np.argsort(bge_sims)[::-1][:candidate_pool]

        # RRF 融合
                    fused_indices = _rrf_fuse(
                        list(bm25_rank_indices),
                        list(bge_rank_indices),
                        k=self.rrf_k,
                    )

        # 取 top_k, 计算可解释性字段
                    top_indices = fused_indices[:top_k]

        # 构造 rank 映射 (idx → rank, 1-based)
                    bm25_rank_map = {int(idx): r for r, idx in enumerate(bm25_rank_indices, start=1)}
                    bge_rank_map = {int(idx): r for r, idx in enumerate(bge_rank_indices, start=1)}

        # RRF 分数归一化 (max-min → 0-1, 便于展示)
                    rrf_scores_raw = []
                    for idx in top_indices:
                        rrf_score = 0.0
                        if idx in bm25_rank_map:
                            rrf_score += 1.0 / (self.rrf_k + bm25_rank_map[idx])
                        if idx in bge_rank_map:
                            rrf_score += 1.0 / (self.rrf_k + bge_rank_map[idx])
                        rrf_scores_raw.append(rrf_score)
                    max_score = max(rrf_scores_raw) if rrf_scores_raw else 1.0
                    min_score = min(rrf_scores_raw) if rrf_scores_raw else 0.0
                    denom = max_score - min_score if max_score > min_score else 1.0

                    results = []
                    for i, idx in enumerate(top_indices):
                        meta = dict(self._metadata[idx])
                        meta["similarity"] = round(float((rrf_scores_raw[i] - min_score) / denom), 3)
                        meta["bm25_rank"] = bm25_rank_map.get(int(idx), None)
                        meta["bge_rank"] = bge_rank_map.get(int(idx), None)
                        results.append(meta)
                    return results
        except QueryTooLongError as exc:
            return [{"error": QueryTooLongError.code, "message": str(exc)}]
        except Exception as exc:
            return [{"error": "INDEX_NOT_READY", "message": f"索引查询未就绪：{exc}"}]

    # ── 统计 ──

    def index_stats(self):
        """Return index statistics."""
        try:
            with self._state_lock:
                with self._filesystem_lock():
                    if (self._bm25 is None or self._bge_embeddings is None
                            or self._loaded_build_limit is None):
                        self._load_cache_unlocked(expected_limit=0)
                    if not self._metadata or self._loaded_build_limit != 0:
                        raise IndexNotReadyError("索引未建立，请先执行索引构建")
                    books = set(m["book_name"] for m in self._metadata)
                    return {
                        "status": "ready",
                        "index_not_ready": None,
                        "total_scenes": len(self._metadata),
                        "total_books": len(books),
                        "embedding_dim": int(self._bge_embeddings.shape[1]),
                        "method": self.method,
                        "embedding_model": self.embedding_model_name,
                        "rrf_k": self.rrf_k,
                        "genre": self.genre,
                    }
        except Exception as exc:
            return {
                "status": "index_not_ready",
                "index_not_ready": f"索引统计未就绪：{exc}",
                "total_scenes": 0,
                "total_books": 0,
                "genre": self.genre,
            }


# ── CLI ──

def _format_result(r, i):
    """Format a single search result for CLI output."""
    lines = []
    lines.append(f"-- {i}. [score={r['similarity']:.2f}] {r['book_name']} 第{r['chapter']}章 --")
    bm25_rank = r.get("bm25_rank")
    bge_rank = r.get("bge_rank")
    lines.append(f"   排名: BM25#{bm25_rank}  BGE#{bge_rank}  (低=更相关)")
    lines.append(f"   技法: {r['technique_summary']}")
    lines.append(f"   情绪: {r['emotion']} | 节奏: {r['pace']} | 冲突: {r['conflict_level']}")
    lines.append(f"   预览: {r['text_preview'][:120]}...")
    lines.append("")
    return "\n".join(lines)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="场景级写作参考检索引擎 (混合检索: BM25+BGE+RRF)")
    parser.add_argument("query", nargs="?", help="搜索查询（自然语言）")
    parser.add_argument("--genre", default="末世", help="题材 (default: 末世)")
    parser.add_argument("--top", type=int, default=5, help="返回结果数 (default: 5)")
    parser.add_argument("--build", action="store_true", help="重建索引")
    parser.add_argument("--limit", type=int, default=0, help="限制处理书籍数量（0=全量，用于测试）")
    parser.add_argument("--stats", action="store_true", help="显示索引统计")
    args = parser.parse_args()

    try:
        validated_cache = _cache_dir(args.genre)
    except IndexNotReadyError as exc:
        parser.error(str(exc))

    ss = SceneSearch(args.genre)

    if args.build:
        print(f"构建 {args.genre} 题材场景索引 (BM25+BGE+RRF)...")
        built_scenes = ss.build_index(force=True, limit=args.limit)
        if args.limit > 0:
            print(f"  样本索引构建完成: {built_scenes} 个场景 (正式索引未覆盖)")
            return
        stats = ss.index_stats()
        print(f"  总场景: {stats['total_scenes']}, 总书数: {stats['total_books']}")
        return

    if args.stats:
        stats = ss.index_stats()
        print(json.dumps(stats, ensure_ascii=False, indent=2))
        return

    if not args.query:
        parser.print_help()
        return

    # Ensure index exists
    cache_bm25 = validated_cache / "bm25_index.pkl"
    if _validated_optional_file(cache_bm25, PROJECT_ROOT, "索引缓存") is None:
        print(f"首次使用，正在构建 {args.genre} 题材索引 (BM25+BGE+RRF)...")
        ss.build_index()

    results = ss.search(args.query, top_k=args.top)
    if not results:
        print("[FAIL] 无结果")
        return
    if "error" in results[0]:
        print(f"[FAIL] {results[0]['error']}")
        return

    print(f"\n查询: \"{args.query}\" -> {len(results)} 个结果 (混合检索: BM25+BGE+RRF)\n")
    for i, r in enumerate(results, 1):
        print(_format_result(r, i))


if __name__ == "__main__":
    main()

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
import stat
import threading
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Optional, TYPE_CHECKING

import jieba
import numpy as np
from rank_bm25 import BM25Okapi

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

from xiaoshuo import PROJECT_ROOT
from xiaoshuo.infra.config_manager import get_config
from xiaoshuo.pipeline.rhythm_analyzer import extract_chapters
from xiaoshuo.pipeline.paths import rhythm_dir as _rhythm_dir

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

_METADATA_STRING_FIELDS = (
    "book_name", "text_preview", "emotion", "pace", "conflict_level",
    "pleasure_type", "dominant_sub", "hook_type", "technique_summary",
)
_METADATA_INT_FIELDS = ("chapter", "scene_index", "char_count")
_METADATA_FLOAT_FIELDS = ("dialogue_ratio",)


class IndexNotReadyError(RuntimeError):
    """索引不存在、损坏或与当前模型/语料合同不一致。"""


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _digest_entries(entries: list[tuple[str, str]]) -> str:
    payload = json.dumps(sorted(entries), ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


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
        if current.exists() and _is_reparse_point(current):
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


def _reject_contained_path(path: Path, root: Path, label: str) -> None:
    """拒绝 reparse 路径，并确认解析后的目标仍在批准目录内。"""
    _reject_reparse_ancestors(path, label)
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(root.resolve(strict=True))
    except (OSError, ValueError) as exc:
        raise IndexNotReadyError(f"{label} 文件越出批准目录：{path}") from exc


def _resolve_project_cache_path(path: Path) -> Path:
    """将缓存路径固定在项目根内，并拒绝越界和 reparse。"""
    if ".." in path.parts:
        raise IndexNotReadyError("scene_search.cache_dir 不得包含 ..")
    resolved = path.resolve(strict=False)
    project_root = PROJECT_ROOT.resolve()
    try:
        resolved.relative_to(project_root)
    except ValueError as exc:
        raise IndexNotReadyError("scene_search.cache_dir 必须位于项目目录内") from exc
    _reject_reparse_ancestors(resolved, "索引缓存")
    return resolved

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




def _cache_dir(genre):
    return PROJECT_ROOT / "data" / "processed" / genre / "scene_index"


def _load_novel_index():
    if _INDEX_PATH.exists():
        with open(_INDEX_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def _load_rhythm_data(genre, book_name):
    """Load rhythm CSV for a book, return {ch_num: dict}."""
    csv_path = _rhythm_dir(genre) / f"rhythm_{book_name}.csv"
    if not csv_path.exists():
        return {}
    data = {}
    with open(csv_path, "r", encoding="utf-8-sig") as f:
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
            if len(g) >= min_chars:
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
            if chunk and len(chunk) >= min_chars:
                scenes.append(chunk.strip())

    return scenes


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


def _build_scene_metadata(book_name, ch_num, scene_idx, scene_text, rhythm_data):
    """Build metadata dict for a single scene."""
    return {
        "book_name": book_name,
        "chapter": ch_num,
        "scene_index": scene_idx,
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

    def __init__(self, genre="末世"):
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
        self.rrf_k = int(ss_cfg.get("rrf_k", _RRF_K))
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
        self._state_lock = threading.RLock()
        # BM25 状态
        self._bm25: Optional[BM25Okapi] = None
        self._tokenized_corpus: list = []
        # BGE 状态
        self._bge_model: Optional[Any] = None
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
                model_path = self._validated_model_path()
                from sentence_transformers import SentenceTransformer

                print(f"  [BGE] 加载本地模型 {model_path} ...")
                self._bge_model = SentenceTransformer(
                    str(model_path),
                    cache_folder=str(_BGE_CACHE_DIR),
                    local_files_only=True,
                )
                print(f"  [BGE] 模型就绪, dim={self._bge_model.get_sentence_embedding_dimension()}")
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
            _reject_reparse_file(path / name, model_root, "BGE 模型")
        if not any(weight.is_file() and not _is_reparse_point(weight)
                   for weight in weights):
            raise IndexNotReadyError("D 盘 BGE 模型缺少权重文件")
        for weight in weights:
            if weight.is_file():
                _reject_reparse_file(weight, model_root, "BGE 模型")
        return path

    def _model_identity(self) -> dict[str, Any]:
        path = self._validated_model_path()
        config_path = path / "config.json"
        weight = next(item for item in (path / "model.safetensors", path / "pytorch_model.bin") if item.is_file())
        return {
            "model_id": self.embedding_model_name,
            "model_local_path": path.as_posix(),
            "model_config_sha256": _sha256_file(config_path),
            "model_tokenizer_config_sha256": _sha256_file(path / "tokenizer_config.json"),
            "model_weight_file": weight.name,
            "model_weight_bytes": weight.stat().st_size,
            "model_weight_sha256": _sha256_file(weight),
        }

    def _bge_encode(self, texts, batch_size=32, show_progress=False):
        """文本 → BGE 嵌入向量 (L2 归一化, 便于 cosine 相似度)."""
        model = self._get_bge_model()
        embeddings = model.encode(
            texts,
            batch_size=batch_size,
            show_progress_bar=show_progress,
            normalize_embeddings=True,  # L2 归一化, dot product = cosine
            convert_to_numpy=True,
        )
        return embeddings.astype(np.float32, copy=False)

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
        if not self._cache.parent.is_dir():
            raise IndexNotReadyError("索引目录尚未建立，请先执行索引构建")
        try:
            _reject_reparse_ancestors(self._cache.parent, "索引缓存")
            with lock_path.open("a+b") as handle:
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

    def build_index(self, force=False, limit=0):
        """在进程内和跨进程锁内构建或加载索引。"""
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 0:
            raise IndexNotReadyError("索引构建 limit 必须是非负整数")
        self._validate_method()
        self._cache.parent.mkdir(parents=True, exist_ok=True)
        _reject_reparse_ancestors(self._cache.parent, "索引缓存")
        with self._state_lock:
            with self._filesystem_lock():
                return self._build_index_unlocked(force=force, limit=limit)

    def _collect_corpus(self, limit=0):
        """读取当前语料并返回构建结果与可复算的源快照。"""
        if not _INDEX_PATH.is_file():
            raise IndexNotReadyError("源 novel_index.json 不存在")
        novel_index = _load_novel_index()
        genre_novels = novel_index.get("genres", {}).get(self.genre, {}).get("novels", [])
        if not genre_novels:
            return [], [], [("data/raw/novel_index.json", _sha256_file(_INDEX_PATH))], 0

        all_scenes = []
        all_metadata = []
        source_entries = [("data/raw/novel_index.json", _sha256_file(_INDEX_PATH))]
        book_count = 0
        for novel in genre_novels:
            book_name = novel.get("file", "").replace(".txt", "")
            novel_path = _NOVELS_DIR / self.genre / novel.get("file", "")
            if not novel_path.is_file():
                continue
            rhythm_data = _load_rhythm_data(self.genre, book_name)
            if not rhythm_data:
                continue
            source_entries.append((
                str(novel_path.relative_to(PROJECT_ROOT)).replace("\\", "/"),
                _sha256_file(novel_path),
            ))
            rhythm_path = _rhythm_dir(self.genre) / f"rhythm_{book_name}.csv"
            if not rhythm_path.is_file():
                continue
            source_entries.append((
                str(rhythm_path.relative_to(PROJECT_ROOT)).replace("\\", "/"),
                _sha256_file(rhythm_path),
            ))
            try:
                chapters = extract_chapters(str(novel_path))
            except Exception as exc:
                print(f"  [WARN] 跳过 {book_name}: 章节抽取失败 {exc}")
                continue
            for chapter in chapters:
                ch_num = chapter.get("num", 0)
                ch_text = chapter.get("text", "")
                ch_rhythm = rhythm_data.get(ch_num, {})
                scenes = _split_scenes(ch_text, self.min_scene_chars, self.max_scene_chars)
                for scene_idx, scene_text in enumerate(scenes):
                    all_scenes.append(scene_text)
                    all_metadata.append(
                        _build_scene_metadata(book_name, ch_num, scene_idx, scene_text, ch_rhythm)
                    )
            book_count += 1
            if book_count % 5 == 0:
                print(f"  [OK] 已处理 {book_count}/{len(genre_novels)} 本...")
            if limit > 0 and book_count >= limit:
                break
        return all_scenes, all_metadata, source_entries, book_count

    def _build_index_unlocked(self, force=False, limit=0):
        """Build scene search index from all novels in the genre.

        Args:
            force: if True, rebuild even if cache exists
            limit: max books to process (0 = all)
        """
        model_identity = self._model_identity()

        if (not force and all((self._cache / name).is_file() for name in (
                "bm25_index.pkl", "bge_embeddings.npy", "metadata.json", "manifest.json"))):
            self._load_cache_unlocked(expected_limit=limit)
            print(f"[OK] 从缓存加载索引: {len(self._metadata)} 个场景")
            return len(self._metadata)

        self._cache.mkdir(parents=True, exist_ok=True)
        cache_parent = self._cache.parent.resolve(strict=True)
        _reject_contained_path(self._cache, cache_parent, "索引缓存")
        all_scenes, all_metadata, source_entries, book_count = self._collect_corpus(limit=limit)
        if not all_scenes:
            print(f"[FAIL] 题材 '{self.genre}' 无入库小说")
            return 0

        n_scenes = len(all_scenes)
        print(f"[OK] 切分完成: {n_scenes} 个场景, 开始构建双通道索引...")

        # 通道A: BM25 索引 (jieba 分词)
        print(f"  [BM25] 分词 + 索引构建...")
        tokenized_corpus = [_jieba_tokenize(s) for s in all_scenes]
        bm25 = BM25Okapi(tokenized_corpus)
        print(f"  [BM25] 索引就绪, 词表规模={len(bm25.get_scores(tokenized_corpus[0] if tokenized_corpus else ['']))}")

        # 通道B: BGE 嵌入
        print(f"  [BGE] 嵌入 {n_scenes} 个场景...")
        bge_embeddings = self._bge_encode(all_scenes, show_progress=False)
        print(f"  [BGE] 嵌入矩阵 shape={bge_embeddings.shape}")
        if (bge_embeddings.ndim != 2 or bge_embeddings.shape[0] != n_scenes
                or bge_embeddings.dtype != np.float32
                or not np.isfinite(bge_embeddings).all()):
            raise IndexNotReadyError("模型生成的向量矩阵无效")

        # 先在独立 staging 目录生成完整载荷，manifest 最后发布。
        staging = self._cache.parent / f".{self._cache.name}.staging-{uuid.uuid4().hex}"
        cache_bm25 = staging / "bm25_index.pkl"
        cache_bge = staging / "bge_embeddings.npy"
        cache_meta = staging / "metadata.json"
        cache_manifest = staging / "manifest.json"
        try:
            staging.mkdir(parents=True, exist_ok=False)
            _reject_contained_path(staging, cache_parent, "索引 staging")
            with cache_bm25.open("wb") as handle:
                pickle.dump({"bm25": bm25, "tokenized_corpus": tokenized_corpus}, handle)
            _reject_contained_path(staging, cache_parent, "索引 staging")
            np.save(str(cache_bge), bge_embeddings)
            _reject_contained_path(staging, cache_parent, "索引 staging")
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
                "source_novel_index_sha256": _sha256_file(_INDEX_PATH),
                "source_corpus_sha256": _digest_entries(source_entries),
                "build_limit": limit,
                "n_books": book_count,
                "n_scenes": n_scenes,
                "corpus_total_chars": sum(item["char_count"] for item in all_metadata),
                "artifacts": {
                    "bm25_index.pkl": _sha256_file(cache_bm25),
                    "bge_embeddings.npy": _sha256_file(cache_bge),
                    "metadata.json": _sha256_file(cache_meta),
                },
            }
            with cache_manifest.open("w", encoding="utf-8") as handle:
                json.dump(manifest, handle, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
            _reject_reparse_file(cache_manifest, staging, "索引 staging")
            for name in ("bm25_index.pkl", "bge_embeddings.npy", "metadata.json"):
                source = staging / name
                target = self._cache / name
                _reject_reparse_file(source, staging, "索引 staging")
                _reject_contained_path(self._cache, cache_parent, "索引缓存")
                _reject_reparse_ancestors(target, "索引缓存")
                os.replace(source, target)
            _reject_reparse_file(cache_manifest, staging, "索引 staging")
            _reject_contained_path(self._cache, cache_parent, "索引缓存")
            _reject_reparse_ancestors(self._cache / "manifest.json", "索引缓存")
            os.replace(cache_manifest, self._cache / "manifest.json")
        except Exception:
            self._clear_loaded_state()
            raise
        finally:
            try:
                staging.rmdir()
            except OSError:
                pass

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
        if any(not item.is_file() for item in required):
            raise IndexNotReadyError("索引未建立，请先执行索引构建")
        _reject_reparse_ancestors(self._cache, "索引缓存")
        cache_root = self._cache.resolve(strict=True)
        for path in required:
            _reject_reparse_file(path, cache_root, "索引")

        try:
            manifest = json.loads(cache_manifest.read_text(encoding="utf-8"))
            if not isinstance(manifest, dict):
                raise ValueError("manifest 根节点必须是对象")
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
            raise IndexNotReadyError("索引 manifest 无法读取") from exc

        model_identity = self._model_identity()
        build_limit = manifest.get("build_limit")
        if not isinstance(build_limit, int) or build_limit < 0:
            raise IndexNotReadyError("索引 manifest 的 build_limit 无效")
        if expected_limit is not None and build_limit != expected_limit:
            raise IndexNotReadyError("索引的构建范围与当前请求不一致")
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
            "source_novel_index_sha256": _sha256_file(_INDEX_PATH),
        }
        if any(manifest.get(key) != value for key, value in expected.items()):
            raise IndexNotReadyError("索引 manifest 与当前模型、配置或题材不一致")

        artifacts = manifest.get("artifacts")
        if not isinstance(artifacts, dict):
            raise IndexNotReadyError("索引 manifest 缺少 artifacts 校验段")
        for path in (cache_bm25, cache_bge, cache_meta):
            if artifacts.get(path.name) != _sha256_file(path):
                raise IndexNotReadyError(f"索引文件校验失败：{path.name}")

        _, current_metadata, source_entries, current_books = self._collect_corpus(limit=build_limit)
        current_chars = sum(item.get("char_count", 0) for item in current_metadata)
        if (manifest.get("source_corpus_sha256") != _digest_entries(source_entries)
                or manifest.get("n_books") != current_books
                or manifest.get("n_scenes") != len(current_metadata)
                or manifest.get("corpus_total_chars") != current_chars):
            raise IndexNotReadyError("索引 manifest 与当前语料快照不一致")

        try:
            with cache_bm25.open("rb") as f:
                data = pickle.load(f)
            embeddings = np.load(str(cache_bge), allow_pickle=False)
            metadata = json.loads(cache_meta.read_text(encoding="utf-8"))
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
                          and all(self._valid_metadata_item(item) for item in metadata))
        if (bm25 is None or not callable(getattr(bm25, "get_scores", None))
                or not valid_tokens
                or not valid_metadata
                or not isinstance(n_scenes, int) or not isinstance(embedding_dim, int)
                or not isinstance(manifest.get("n_books"), int)
                or not isinstance(manifest.get("corpus_total_chars"), int)
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
    def _valid_metadata_item(item: Any) -> bool:
        """校验 API 会直接读取的全部 metadata 字段。"""
        if not isinstance(item, dict):
            return False
        if any(not isinstance(item.get(name), str) for name in _METADATA_STRING_FIELDS):
            return False
        if any(not isinstance(item.get(name), int) or isinstance(item.get(name), bool)
               for name in _METADATA_INT_FIELDS):
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

    ss = SceneSearch(args.genre)

    if args.build:
        print(f"构建 {args.genre} 题材场景索引 (BM25+BGE+RRF)...")
        ss.build_index(force=True, limit=args.limit)
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
    cache_bm25 = _cache_dir(args.genre) / "bm25_index.pkl"
    if not cache_bm25.exists():
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

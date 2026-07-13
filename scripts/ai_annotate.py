#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""ai_annotate.py — AI标注全读策略工具 v2

从小说原文提取章节全文(不截断), 分层采样, 批次输出供 AI 标注。
v2改进: 支持API自动评分, 多书扩展, 防上下文过载, 省token设计。

== 踩坑经验固化 ==

1. 上下文过载 (根因: 一次读5章~12000字导致AI罐头回复)
   → 默认 batch_size=2 (约5000字), 可配置
   → API模式每次只发2章 + 精简prompt

2. PowerShell编码乱码 (根因: PowerShell默认GBK, 中文输出乱码)
   → 所有JSON文件用 utf-8 编码
   → CSV文件用 utf-8-sig (带BOM, Excel兼容)
   → 脚本输出用 sys.stdout.reconfigure(encoding='utf-8')

3. BOM头导致KeyError (根因: utf-8-sig的BOM被当作列名前缀)
   → 读取CSV时统一用 utf-8-sig
   → 验证脚本也用 utf-8-sig

4. && 语法错误 (根因: PowerShell不支持&&连接)
   → 所有复杂逻辑用Python脚本执行, 不依赖shell管道

5. JSON格式不统一 (根因: 手写JSON容易出错)
   → API模式: LLM输出JSON → 验证 → 写入, 自动化
   → 手动模式: --print 输出全文供AI阅读, 仍支持

== 设计原则 (为DSV4 Flash接入) ==

- 省token: system prompt一行, rubric精简, 每次只发2章
- 可恢复: 已评分的批次自动跳过
- 可配置: --api-base / --api-key / --api-model 支持外部API
- 多书支持: --book 参数指定书籍, 不再硬编码废土崛起
- 10%采样: 保持不变, 验证结果优秀(MAE=0.55)

用法:
  python scripts/ai_annotate.py --status                    # 查看标注进度
  python scripts/ai_annotate.py --extract 废土崛起            # 提取全书章节(全读)
  python scripts/ai_annotate.py --print 0                    # 打印指定批次供AI阅读
  python scripts/ai_annotate.py --score 废土崛起              # API自动评分(本地LLM)
  python scripts/ai_annotate.py --score 废土崛起 --api-base https://api.deepseek.com/v1 --api-key sk-xxx --api-model deepseek-chat
  python scripts/ai_annotate.py --merge 废土崛起              # 合并为完整CSV
  python scripts/ai_annotate.py --validate 废土崛起           # 质量验证(vs golden)
"""
import json
import csv
import sys
import math
import argparse
import time
import re
from pathlib import Path
from typing import List, Dict, Optional, Tuple

# 项目路径
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from xiaoshuo.pipeline.rhythm_analyzer import extract_chapters

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')

# ============================================================
# 配置
# ============================================================

RAW_DIR = PROJECT_ROOT / "data" / "raw" / "novels" / "末世"
SCORES_DIR = PROJECT_ROOT / "data" / "processed" / "末世" / "scores"
BATCH_DIR = SCORES_DIR / "ai_annotate_batches"

# v8.8: 从novel_index.json动态加载全部33本书籍
import json as _json
_INDEX_PATH = PROJECT_ROOT / "data" / "raw" / "novel_index.json"
BOOKS = {}
if _INDEX_PATH.exists():
    with open(_INDEX_PATH, 'r', encoding='utf-8') as _f:
        _idx = _json.load(_f)
    for _n in _idx.get('genres', {}).get('末世', {}).get('novels', []):
        _fname = _n['file']
        # 短名: 去掉《》和作者后缀，取书名部分
        _short = _fname.replace('.txt', '')
        # 提取书名: 《xxx》或纯名字
        if _short.startswith('《'):
            _match = re.search(r'《(.+?)》', _short)
            _short = _match.group(1) if _match else _short
        BOOKS[_short] = _fname

# 黄金分层比例 (保持不变, 10%采样验证结果优秀)
STRATA = [
    {"name": "Opening", "start": 0.00, "end": 0.03, "ratio": 0.03},
    {"name": "Rising",  "start": 0.03, "end": 0.30, "ratio": 0.27},
    {"name": "Mid",     "start": 0.30, "end": 0.60, "ratio": 0.30},
    {"name": "Climax",  "start": 0.60, "end": 0.90, "ratio": 0.30},
    {"name": "Ending",  "start": 0.90, "end": 1.00, "ratio": 0.10},
]

# 坑1修复: 默认2章/批, 防上下文过载
DEFAULT_BATCH_SIZE = 2

SAMPLE_RATE = 0.10  # 10%分层采样

# 废土崛起 pilot 40章中因截断(wc>2500)需要重跑的17章
RERUN_CHAPTERS = [1, 193, 385, 577, 648, 769, 788, 868, 961, 1008, 1153, 1297, 1345, 1367, 1729, 1794, 1862]

# pilot 40章中wc<=2500可保留的23章
KEEP_CHAPTERS = [20, 39, 58, 107, 166, 225, 284, 343, 402, 461, 520, 579, 718, 938, 1078, 1158, 1227, 1447, 1517, 1537, 1587, 1657, 1737]

SCORE_FIELDS = ["ai_intensity", "ai_conflict", "ai_emotion", "ai_pace", "ai_hook", "ai_retention", "ai_analysis"]
CSV_FIELDS = ["ch_num", "stratum", "wc"] + SCORE_FIELDS

# 坑5修复: 精简prompt, 省token (为DSV4 Flash优化)
SYSTEM_PROMPT = "你是网文评分专家。阅读章节全文，按RUBRIC打分，只输出JSON数组。"

RUBRIC_TEXT = """\
评分维度:
- intensity: 1-10 爽感强度 (1=极度无聊, 10=极致爽感)
- conflict: low/medium/high 冲突激烈程度
- emotion: 日常/紧张/爽快/悬疑/压抑/感动 主要情绪基调
- pace: slow/medium/fast 叙事节奏
- hook: weak/medium/strong 章末悬念
- retention: 1-10 读者追读下一章意愿
- analysis: 20-50字中文评分理由"""


# ============================================================
# 分层采样
# ============================================================

def stratified_sample(chapters: List[Dict], sample_rate: float = SAMPLE_RATE) -> List[Tuple[int, str]]:
    """按黄金分层比例从章节列表中分层采样。"""
    total = len(chapters)
    if total == 0:
        return []

    sorted_chs = sorted(chapters, key=lambda c: c["num"])
    all_nums = [c["num"] for c in sorted_chs]

    sampled = []
    for stratum in STRATA:
        start_idx = int(total * stratum["start"])
        end_idx = int(total * stratum["end"])
        if end_idx <= start_idx:
            continue

        stratum_chs = all_nums[start_idx:end_idx]
        n_sample = max(1, math.ceil(len(stratum_chs) * sample_rate))

        if len(stratum_chs) <= n_sample:
            selected = stratum_chs
        else:
            step = len(stratum_chs) / n_sample
            indices = [int(i * step) for i in range(n_sample)]
            indices = sorted(set(min(i, len(stratum_chs)-1) for i in indices))
            selected = [stratum_chs[i] for i in indices]

        for ch_num in selected:
            sampled.append((ch_num, stratum["name"]))

        print(f"  {stratum['name']}: {len(stratum_chs)}ch → sampled {len(selected)}")

    return sampled


# ============================================================
# 章节提取 (全读, 不截断)
# ============================================================

def extract_full_chapters(book_name: str) -> List[Dict]:
    """从原文提取全部章节, 保留全文(raw_body), 不截断。"""
    txt_file = BOOKS.get(book_name)
    if not txt_file:
        print(f"[ERROR] 未知书籍: {book_name}. 可选: {list(BOOKS.keys())}")
        return []

    txt_path = RAW_DIR / txt_file
    if not txt_path.exists():
        print(f"[ERROR] 文件不存在: {txt_path}")
        return []

    print(f"提取 {book_name} 全文章节...")
    chapters = extract_chapters(str(txt_path))
    print(f"  总章节: {len(chapters)}")

    sampled = stratified_sample(chapters, sample_rate=SAMPLE_RATE)
    stratum_map = {ch_num: s for ch_num, s in sampled}

    result = []
    ch_map = {ch["num"]: ch for ch in chapters}
    for ch_num, stratum in sampled:
        ch = ch_map.get(ch_num)
        if not ch:
            continue
        body = ch.get("raw_body", ch.get("text", ""))
        result.append({
            "book": book_name,
            "ch_num": ch_num,
            "stratum": stratum,
            "wc": len(body),
            "body": body,
        })

    print(f"  提取完成: {len(result)} 章 (全文)")
    return result


def get_book_batch_dir(book_name: str) -> Path:
    """获取书籍专属的批次目录。"""
    # 废土崛起保持向后兼容
    if book_name == "废土崛起":
        return BATCH_DIR
    return SCORES_DIR / "ai_annotate_batches" / book_name


# ============================================================
# 批次输出
# ============================================================

def write_batches(chapters: List[Dict], book_name: str, prefix: str = "new",
                  batch_size: int = None) -> List[Path]:
    """将章节列表分批写入JSON文件。每批 batch_size 章。"""
    if batch_size is None:
        batch_size = BATCH_SIZE
    batch_dir = get_book_batch_dir(book_name)
    batch_dir.mkdir(parents=True, exist_ok=True)

    batch_paths = []
    for i in range(0, len(chapters), batch_size):
        batch = chapters[i:i + batch_size]
        batch_num = i // BATCH_SIZE
        fname = f"{prefix}_{batch_num:02d}.json"
        fpath = batch_dir / fname

        # 坑2修复: 统一用 utf-8 (无BOM) 写JSON
        with open(fpath, "w", encoding="utf-8") as f:
            json.dump(batch, f, ensure_ascii=False, indent=2)

        total_chars = sum(c["wc"] for c in batch)
        print(f"  {fname}: {len(batch)}章, {total_chars}字")
        batch_paths.append(fpath)

    return batch_paths


def print_batch(fpath: Path):
    """打印一个批次的内容供AI阅读。"""
    # 坑2修复: 统一用 utf-8 读JSON
    with open(fpath, "r", encoding="utf-8") as f:
        batch = json.load(f)

    print(f"\n{'='*60}")
    print(f"批次: {fpath.name} | {len(batch)}章")
    print(f"{'='*60}")
    print(RUBRIC_TEXT)
    print(f"{'='*60}\n")

    for ch in batch:
        print(f"--- {ch['book']} 第{ch['ch_num']}章 [{ch['stratum']}] | {ch['wc']}字 ---")
        print(ch["body"])
        print()


# ============================================================
# API 自动评分 (为 DSV4 Flash 设计)
# ============================================================

def build_score_prompt(batch: List[Dict]) -> str:
    """构建评分prompt。坑5修复: 精简, 省token。"""
    parts = [RUBRIC_TEXT, ""]
    for ch in batch:
        parts.append(f"=== ch{ch['ch_num']} ({ch['stratum']}, {ch['wc']}字) ===")
        parts.append(ch["body"])
        parts.append("")
    parts.append("输出JSON数组，每个元素: {ch_num, stratum, wc, ai_intensity(int), ai_conflict, ai_emotion, ai_pace, ai_hook, ai_retention(int), ai_analysis}")
    return "\n".join(parts)


def call_llm_api(prompt: str, system: str, api_base: str, api_key: str,
                 api_model: str, max_tokens: int = 800, timeout: int = 120) -> Optional[str]:
    """调用 LLM API (OpenAI兼容格式)。

    支持本地 llama-server 和外部API (DeepSeek, Gemini Flash等)。
    """
    import http.client
    from urllib.parse import urlparse

    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": prompt},
    ]

    payload = {
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": 0.0,
    }
    if api_model:
        payload["model"] = api_model

    data = json.dumps(payload).encode("utf-8")

    # 解析URL
    parsed = urlparse(api_base)
    host = parsed.hostname
    port = parsed.port or (443 if parsed.scheme == "https" else 80)

    # 构建路径
    path = parsed.path.rstrip("/")
    if not path.endswith("/v1/chat/completions"):
        if path.endswith("/v1"):
            path = path + "/chat/completions"
        else:
            path = path.rstrip("/") + "/v1/chat/completions"

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        if parsed.scheme == "https":
            conn = http.client.HTTPSConnection(host, port, timeout=timeout)
        else:
            conn = http.client.HTTPConnection(host, port, timeout=timeout)

        conn.request("POST", path, body=data, headers=headers)
        resp = conn.getresponse()
        raw = resp.read()
        conn.close()

        result = json.loads(raw)
        content = result.get("choices", [{}])[0].get("message", {}).get("content", "")

        # 清理 thinking tags (DeepSeek-R1兼容)
        content = re.sub(r"<think>[\s\S]*?</think>\s*", "", content).strip()
        return content
    except Exception as e:
        print(f"  [ERROR] API调用失败: {e}")
        return None


def parse_scores(raw: str, batch: List[Dict]) -> Optional[List[Dict]]:
    """解析LLM输出的JSON评分。坑5修复: 多重解析策略。"""
    if not raw:
        return None

    # 尝试直接解析
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            return data
    except json.JSONDecodeError:
        pass

    # 尝试提取 ```json ... ``` 代码块
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw)
    if m:
        try:
            data = json.loads(m.group(1).strip())
            if isinstance(data, list):
                return data
        except json.JSONDecodeError:
            pass

    # 尝试提取第一个 [ ... ] 块
    m = re.search(r"\[[\s\S]*\]", raw)
    if m:
        try:
            data = json.loads(m.group(0))
            if isinstance(data, list):
                return data
        except json.JSONDecodeError:
            pass

    print(f"  [WARN] JSON解析失败, 原始输出前200字: {raw[:200]}")
    return None


def validate_scores(scores: List[Dict], batch: List[Dict]) -> bool:
    """验证评分数据完整性。"""
    if not scores or len(scores) != len(batch):
        print(f"  [WARN] 评分数量不匹配: 期望{len(batch)}, 实际{len(scores)}")
        return False

    batch_chs = {ch["ch_num"] for ch in batch}
    valid_emotions = {"日常", "紧张", "爽快", "悬疑", "压抑", "感动", "悲壮", "温馨", "感慨", "振奋", "热血"}
    valid_levels = {"low", "medium", "high"}
    valid_pace = {"slow", "medium", "fast"}
    valid_hook = {"weak", "medium", "strong"}

    for s in scores:
        # 检查必需字段
        if "ch_num" not in s or "ai_intensity" not in s or "ai_retention" not in s:
            print(f"  [WARN] 缺少必需字段: {s}")
            return False

        # 检查 ch_num 匹配
        if s["ch_num"] not in batch_chs:
            print(f"  [WARN] ch_num不匹配: {s['ch_num']} 不在批次中")
            return False

        # 检查分数范围
        try:
            intensity = int(s["ai_intensity"])
            retention = int(s["ai_retention"])
            if not (1 <= intensity <= 10):
                print(f"  [WARN] intensity超出范围: {intensity}")
                return False
            if not (1 <= retention <= 10):
                print(f"  [WARN] retention超出范围: {retention}")
                return False
        except (ValueError, TypeError):
            print(f"  [WARN] 分数不是整数: {s}")
            return False

    return True


def load_chapter_list(csv_path: Path) -> Optional[set]:
    """从CSV文件加载章节号列表 (用于Tier 2自定义采样)。"""
    if not csv_path or not csv_path.exists():
        return None
    ch_nums = set()
    with open(csv_path, "r", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            ch_nums.add(int(row["ch_num"]))
    return ch_nums


def score_book(book_name: str, api_base: str = "", api_key: str = "",
               api_model: str = "", batch_size: int = DEFAULT_BATCH_SIZE,
               max_chapters: int = 0, dry_run: bool = False,
               max_batches: int = 0, chapter_list_csv: str = "",
               tier2_mode: bool = False) -> int:
    """API自动评分。返回已评分章节数。

    流程:
    1. 提取全书章节(全读)
    2. 如有chapter_list_csv, 只评分指定章节 (Tier 2模式)
    3. 检查已有评分, 跳过已完成批次
    4. 每次发 batch_size 章给API, 获取评分
    5. 验证 + 写入 scores JSON
    6. max_batches限制单次运行批次数, 防止CatPaw会话超时
    """
    global BATCH_SIZE
    BATCH_SIZE = batch_size

    # 确定批次目录 (Tier 2 用独立子目录)
    if tier2_mode:
        batch_dir = SCORES_DIR / "ai_annotate_batches" / f"tier2_{book_name}"
    else:
        batch_dir = get_book_batch_dir(book_name)

    # Step 1: 提取章节
    mode_label = "Tier2本地模型" if tier2_mode else "AI全读"
    print(f"=== {mode_label}评分: {book_name} ===\n")
    all_chapters = extract_full_chapters(book_name)
    if not all_chapters:
        return 0

    # Step 1.5: 如有chapter_list, 过滤章节
    if chapter_list_csv:
        cl_path = Path(chapter_list_csv)
        ch_set = load_chapter_list(cl_path)
        if ch_set is not None:
            before = len(all_chapters)
            all_chapters = [c for c in all_chapters if c["ch_num"] in ch_set]
            print(f"  章节列表过滤: {before}→{len(all_chapters)}章 (来自 {cl_path.name})")

    # 限制章节数 (用于测试)
    if max_chapters > 0:
        all_chapters = all_chapters[:max_chapters]
        print(f"  限制评分: 前{len(all_chapters)}章 (测试模式)")

    # Step 2: 分批
    batches = []
    for i in range(0, len(all_chapters), BATCH_SIZE):
        batches.append(all_chapters[i:i + BATCH_SIZE])

    print(f"\n共 {len(all_chapters)} 章, 分 {len(batches)} 批 (每批{BATCH_SIZE}章)")

    # Step 3: 确定API地址
    if not api_base:
        # 默认用本地LLM
        try:
            from xiaoshuo.infra.llm_client import get_llm_base_url
            api_base = get_llm_base_url()
        except Exception:
            api_base = "http://127.0.0.1:8000"
    print(f"API: {api_base} | model: {api_model or 'default'}")

    if dry_run:
        print("\n[DRY RUN] 只展示将要评分的批次, 不调用API:")
        for i, batch in enumerate(batches):
            chs = [c["ch_num"] for c in batch]
            total_wc = sum(c["wc"] for c in batch)
            score_file = batch_dir / f"scores_new_{i:02d}.json"
            status = "✓已有" if score_file.exists() else "待评分"
            print(f"  batch {i:02d}: ch{chs} ({total_wc}字) [{status}]")
        return 0

    # Step 4: 逐批评分
    scored_count = 0
    skipped_count = 0
    new_batch_count = 0  # 本次新评分的批次数

    for i, batch in enumerate(batches):
        batch_num = i
        score_file = batch_dir / f"scores_new_{batch_num:02d}.json"

        # 坑6修复: 可恢复 — 跳过已有评分
        if score_file.exists():
            try:
                with open(score_file, "r", encoding="utf-8") as f:
                    existing = json.load(f)
                if len(existing) == len(batch):
                    chs = [c["ch_num"] for c in batch]
                    print(f"  [{i+1}/{len(batches)}] ch{chs} ✓已有评分, 跳过")
                    skipped_count += len(batch)
                    continue
            except (json.JSONDecodeError, IOError):
                pass  # 文件损坏, 重新评分

        # max_batches限制: 防止CatPaw会话超时
        if max_batches > 0 and new_batch_count >= max_batches:
            print(f"\n  [STOP] 已达max_batches={max_batches}限制, 剩余{len(batches)-i}批待下次运行")
            break

        chs = [c["ch_num"] for c in batch]
        total_wc = sum(c["wc"] for c in batch)
        print(f"\n  [{i+1}/{len(batches)}] 评分 ch{chs} ({total_wc}字)...")

        # 构建prompt
        prompt = build_score_prompt(batch)

        # 调用API (带重试)
        max_retries = 3
        scores = None
        for attempt in range(max_retries):
            raw = call_llm_api(
                prompt=prompt,
                system=SYSTEM_PROMPT,
                api_base=api_base,
                api_key=api_key,
                api_model=api_model,
                max_tokens=800,
                timeout=120,
            )
            if raw:
                scores = parse_scores(raw, batch)
                if scores and validate_scores(scores, batch):
                    break
                print(f"  [RETRY {attempt+1}] 评分验证失败, 重试...")
            else:
                print(f"  [RETRY {attempt+1}] API无响应, 重试...")
            time.sleep(2 ** attempt)

        if not scores or not validate_scores(scores, batch):
            print(f"  [FAIL] ch{chs} 评分失败, 跳过 (已重试{max_retries}次)")
            continue

        # 写入评分文件 (坑2修复: utf-8无BOM)
        batch_dir.mkdir(parents=True, exist_ok=True)
        with open(score_file, "w", encoding="utf-8") as f:
            json.dump(scores, f, ensure_ascii=False, indent=2)

        scored_count += len(batch)
        new_batch_count += 1
        print(f"  [OK] ch{chs} 评分完成 → {score_file.name}")

    print(f"\n=== 评分完成 ===")
    print(f"  新评分: {scored_count}章 ({new_batch_count}批)")
    print(f"  已跳过: {skipped_count}章")
    print(f"  总计: {scored_count + skipped_count}章")
    if max_batches > 0 and new_batch_count >= max_batches:
        remaining = len(batches) - i
        print(f"  剩余: ~{remaining}批 (重新运行命令继续)")

    return scored_count


# ============================================================
# 标注结果合并
# ============================================================

def load_ai_csv(book_name: str) -> Dict[int, Dict]:
    """加载已有的AI标注CSV (pilot截断版)。"""
    ai_csv = SCORES_DIR / f"{book_name}_ai.csv"
    if not ai_csv.exists():
        return {}

    result = {}
    # 坑3修复: 用 utf-8-sig 读取 (处理BOM)
    with open(ai_csv, "r", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            ch_num = int(r["ch_num"])
            result[ch_num] = r
    return result


def merge_csv(book_name: str):
    """合并已标注数据为完整CSV。"""
    ai_csv = SCORES_DIR / f"{book_name}_ai.csv"
    out_csv = SCORES_DIR / f"{book_name}_ai_full.csv"
    batch_dir = get_book_batch_dir(book_name)

    # 加载已有标注
    existing = load_ai_csv(book_name)
    print(f"已有标注: {len(existing)}章")

    # 加载新标注批次 (P1修复: 保留首次评分, 丢弃重复ch_num)
    new_scores = {}
    dup_count = 0
    for batch_file in sorted(batch_dir.glob("scores_*.json")):
        # 坑2修复: 统一用 utf-8 读JSON
        with open(batch_file, "r", encoding="utf-8") as f:
            for row in json.load(f):
                ch_num = int(row["ch_num"])
                if ch_num in new_scores:
                    dup_count += 1
                    continue  # 保留首次评分, 跳过重复
                new_scores[ch_num] = row
    if dup_count:
        print(f"[去重] 丢弃 {dup_count} 个重复ch_num (保留首次评分)")
    print(f"新标注: {len(new_scores)}章")

    # 合并逻辑 (废土崛起特殊处理: 保留23章pilot + 新标注覆盖)
    merged = {}
    if book_name == "废土崛起":
        for ch_num, row in existing.items():
            if ch_num in new_scores:
                merged[ch_num] = new_scores[ch_num]
            elif ch_num in KEEP_CHAPTERS:
                merged[ch_num] = row
    else:
        # 其他书: 新标注为主, 无pilot保留
        pass

    # 添加纯新标注
    for ch_num, row in new_scores.items():
        if ch_num not in merged:
            merged[ch_num] = row

    # 排序输出 (坑2修复: utf-8-sig带BOM, Excel兼容)
    with open(out_csv, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for ch_num in sorted(merged.keys()):
            row = merged[ch_num]
            writer.writerow({k: row.get(k, "") for k in CSV_FIELDS})

    print(f"\n合并完成: {len(merged)}章 → {out_csv}")
    return out_csv


# ============================================================
# 质量验证
# ============================================================

def validate_quality(book_name: str):
    """对比AI全读版 vs 人工Golden的MAE/Bias。"""
    import statistics

    # 加载Golden set
    # v8.8: 从保护目录读取golden数据(AI不可修改)
    GOLDEN_DIR = PROJECT_ROOT / "data" / "golden" / "末世"
    golden_csv = GOLDEN_DIR / "human_golden.csv"
    if not golden_csv.exists():
        print("[ERROR] human_golden.csv 不存在")
        return

    golden = {}
    with open(golden_csv, "r", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            if row["book"] == book_name:
                ch = int(row["ch_num"])
                golden[ch] = (float(row["human_intensity"]), float(row["human_retention"]))

    if not golden:
        print(f"[ERROR] Golden set中没有 {book_name} 的数据")
        return

    # 加载AI全读版
    ai_csv = SCORES_DIR / f"{book_name}_ai_full.csv"
    if not ai_csv.exists():
        print(f"[ERROR] {ai_csv.name} 不存在, 请先 --merge")
        return

    ai_scores = {}
    with open(ai_csv, "r", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            ch = int(row["ch_num"])
            ai_scores[ch] = {
                "intensity": int(row["ai_intensity"]),
                "retention": int(row["ai_retention"]),
                "stratum": row.get("stratum", ""),
            }

    # 匹配计算
    matched = []
    for ch in sorted(golden.keys()):
        if ch in ai_scores:
            hi, hr = golden[ch]
            ai_i = ai_scores[ch]["intensity"]
            ai_r = ai_scores[ch]["retention"]
            matched.append({"ch": ch, "hi": hi, "hr": hr, "ai_i": ai_i, "ai_r": ai_r})

    if not matched:
        print("[ERROR] 没有匹配的章节")
        return

    i_diffs = [m["ai_i"] - m["hi"] for m in matched]
    r_diffs = [m["ai_r"] - m["hr"] for m in matched]

    mae_i = statistics.mean([abs(d) for d in i_diffs])
    mae_r = statistics.mean([abs(d) for d in r_diffs])
    bias_i = statistics.mean(i_diffs)
    bias_r = statistics.mean(r_diffs)

    print(f"\n{'='*60}")
    print(f"质量验证: {book_name} (n={len(matched)})")
    print(f"{'='*60}")
    print(f"  Intensity MAE = {mae_i:.2f}")
    print(f"  Retention MAE = {mae_r:.2f}")
    print(f"  Intensity Bias = {bias_i:+.2f}")
    print(f"  Retention Bias = {bias_r:+.2f}")

    # 与pilot对比 (废土崛起)
    if book_name == "废土崛起":
        print(f"\n  Pilot截断版参考: MAE=0.75/1.00, Bias=-0.45")
        print(f"  全读版改善: Intensity {'✓' if mae_i < 0.75 else '✗'}, Retention {'✓' if mae_r < 1.00 else '✗'}")

    # 逐章详情
    print(f"\n  {'ch':>6} | {'Human_I':>8} {'AI_I':>6} {'Diff':>6} | {'Human_R':>8} {'AI_R':>6} {'Diff':>6}")
    print(f"  {'-'*50}")
    for m in matched:
        print(f"  {m['ch']:>6} | {m['hi']:>8.1f} {m['ai_i']:>6} {m['ai_i']-m['hi']:>+6.1f} | {m['hr']:>8.1f} {m['ai_r']:>6} {m['ai_r']-m['hr']:>+6.1f}")


# ============================================================
# 状态查询
# ============================================================

def show_status():
    """显示所有书籍的标注进度。"""
    print("=" * 60)
    print("AI标注进度 (全读策略 v2)")
    print("=" * 60)

    for book_name in BOOKS:
        txt_file = BOOKS[book_name]
        txt_path = RAW_DIR / txt_file
        if not txt_path.exists():
            print(f"\n{book_name}: 文件不存在, 跳过")
            continue

        chapters = extract_chapters(str(txt_path))
        total_all = len(chapters)
        sampled = stratified_sample(chapters, sample_rate=SAMPLE_RATE)
        total_sampled = len(sampled)

        batch_dir = get_book_batch_dir(book_name)
        score_files = list(batch_dir.glob("scores_*.json")) if batch_dir.exists() else []

        scored_count = 0
        for sf in score_files:
            try:
                with open(sf, "r", encoding="utf-8") as f:
                    scored_count += len(json.load(f))
            except (json.JSONDecodeError, IOError):
                pass

        # 检查是否已有合并CSV
        out_csv = SCORES_DIR / f"{book_name}_ai_full.csv"
        merged_count = 0
        if out_csv.exists():
            with open(out_csv, "r", encoding="utf-8-sig") as f:
                merged_count = sum(1 for _ in csv.DictReader(f))

        progress = scored_count / total_sampled * 100 if total_sampled > 0 else 0
        print(f"\n{book_name}: {total_all}章总 → 10%采样={total_sampled}章")
        print(f"  已评分: {scored_count}章 ({progress:.0f}%)")
        print(f"  已合并CSV: {merged_count}章 {'✓' if merged_count > 0 else '✗'}")
        print(f"  待评分: {total_sampled - scored_count}章")


# ============================================================
# 主入口
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="AI标注全读策略工具 v2",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例:\n"
               "  --status                              查看进度\n"
               "  --score 废土崛起                       本地LLM自动评分\n"
               "  --score 废土崛起 --max-batches 10      每次只跑10批(防CatPaw超时)\n"
               "  --score 末日蟑螂 --batch-size 3 --max-batches 10\n"
               "                                        每批3章, 每次跑10批\n"
               "  --score 废土崛起 --tier2 --chapter-list data/.../废土崛起_tier2_plan.csv\n"
               "                                        Tier2模式: 按计划CSV评分指定章节\n"
               "  --score 废土崛起 --api-base URL --api-key KEY --api-model MODEL\n"
               "                                        外部API评分(DSV4 Flash等)\n"
               "  --merge 废土崛起                       合并CSV\n"
               "  --validate 废土崛起                    质量验证\n"
    )

    parser.add_argument("--status", action="store_true", help="查看标注进度")
    parser.add_argument("--extract", type=str, metavar="BOOK", help="提取全书章节(全读)")
    parser.add_argument("--score", type=str, metavar="BOOK", help="API自动评分")
    parser.add_argument("--merge", type=str, metavar="BOOK", help="合并为完整CSV")
    parser.add_argument("--validate", type=str, metavar="BOOK", help="质量验证(vs golden)")
    parser.add_argument("--print", type=int, metavar="N", help="打印指定批次内容")
    parser.add_argument("--book", type=str, default="废土崛起", help="书籍名称")

    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE,
                        help=f"每批章节数 (默认{DEFAULT_BATCH_SIZE}, 防上下文过载)")
    parser.add_argument("--api-base", type=str, default="", help="API地址 (默认本地LLM)")
    parser.add_argument("--api-key", type=str, default="", help="API密钥")
    parser.add_argument("--api-model", type=str, default="", help="模型名称")
    parser.add_argument("--max-chapters", type=int, default=0, help="限制评分章节数(测试用)")
    parser.add_argument("--max-batches", type=int, default=0,
                        help="限制单次运行批次数(防CatPaw超时, 建议10)")
    parser.add_argument("--chapter-list", type=str, default="",
                        help="CSV文件路径, 只评分其中列出的章节(Tier 2模式)")
    parser.add_argument("--tier2", action="store_true",
                        help="Tier 2模式: 使用独立目录存储本地模型评分")
    parser.add_argument("--dry-run", action="store_true", help="只展示不执行")

    args = parser.parse_args()

    global BATCH_SIZE
    BATCH_SIZE = args.batch_size

    if args.status:
        show_status()
        return

    if args.extract:
        chapters = extract_full_chapters(args.extract)
        if chapters:
            paths = write_batches(chapters, args.extract, prefix="new")
            print(f"\n提取完成: {len(chapters)}章 → {len(paths)}个批次")
            print(f"批次目录: {get_book_batch_dir(args.extract)}")
            print(f"\n下一步: python scripts/ai_annotate.py --print 0")
        return

    if args.score:
        score_book(
            book_name=args.score,
            api_base=args.api_base,
            api_key=args.api_key,
            api_model=args.api_model,
            batch_size=args.batch_size,
            max_chapters=args.max_chapters,
            dry_run=args.dry_run,
            max_batches=args.max_batches,
            chapter_list_csv=args.chapter_list,
            tier2_mode=args.tier2,
        )
        return

    if args.merge:
        merge_csv(args.merge)
        return

    if args.validate:
        validate_quality(args.validate)
        return

    if args.print is not None:
        batch_num = args.print
        book_name = args.book
        batch_dir = get_book_batch_dir(book_name)
        # 自动查找前缀
        for prefix in ["rerun", "new", "all", "batch"]:
            fpath = batch_dir / f"{prefix}_{batch_num:02d}.json"
            if fpath.exists():
                print_batch(fpath)
                return
        print(f"[ERROR] 批次 {batch_num} 不存在于 {book_name}。可用批次:")
        for f in sorted(batch_dir.glob("*.json")) if batch_dir.exists() else []:
            print(f"  {f.name}")
        return

    parser.print_help()


if __name__ == "__main__":
    main()

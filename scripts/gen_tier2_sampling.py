#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""gen_tier2_sampling.py — Tier 2 分级采样 + 批次生成

按质量分级决定采样量:
  S=50章/本, A=30章/本, B=30章/本, C=20章/本

节奏峰谷对齐:
  S级: 50%采自节奏高峰(top 25% pleasure_intensity)
  A级: 30%采自节奏中段(25-75% pleasure_intensity)
  B级: 20%采自节奏低谷(bottom 25% pleasure_intensity)
  C级: 均匀采样

避开Tier 1已采样章节(最大化覆盖)
"""
import sys, os, json, csv, re, random
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
sys.path.insert(0, os.path.dirname(__file__))

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')

import ai_annotate
ai_annotate.BATCH_SIZE = 2
from ai_annotate import extract_chapters, get_book_batch_dir

PROJECT_ROOT = Path(__file__).parent.parent
RHYTHM_DIR = PROJECT_ROOT / "data" / "processed" / "末世" / "rhythm"
TIER1_DIR = PROJECT_ROOT / "data" / "processed" / "末世" / "scores" / "ai_annotate_batches"
TIER2_DIR = PROJECT_ROOT / "data" / "processed" / "末世" / "scores" / "tier2_batches"

# ── 质量分级 ──
QUALITY_TIERS = {
    "S": ["地球游戏场", "末世大回炉", "异兽迷城", "黑暗血时代", "第一序列", "长夜余火", "末日乐园"],
    "A": ["我 的 末 世 领 地", "从红月开始", "世界末日从考试不及格开始", "末世魔神游戏",
           "末世召唤狂潮", "末日拼图游戏", "废土崛起", "全球变异，从灾厄降临开始",
           "末世之深渊召唤师", "神秘尽头", "狩魔手记_烟雨江南"],
    "B": ["全球进化", "我在末世有套房", "黑暗文明_古羲", "恐慌沸腾",
           "我的女友是丧尸", "灾厄纪元", "黑暗王者", "重卡战车在末世",
           "末日蟑螂", "第九特区", "末世超级商人", "我在末世种个田", "限制级末日症候"],
    "C": ["蹉跎", "黑暗末日"],
}

SAMPLE_SIZES = {"S": 50, "A": 30, "B": 30, "C": 20}

# 节奏峰谷对齐: 从指定rhythm区间采样的比例
RHYTHM_ALIGN = {
    "S": ("peak", 0.50),     # 50%从高峰(top 25%)
    "A": ("mid", 0.30),      # 30%从中段(25-75%)
    "B": ("valley", 0.20),   # 20%从低谷(bottom 25%)
    "C": ("uniform", 0.0),   # 均匀
}

# ── novel_index 加载 ──
INDEX_PATH = PROJECT_ROOT / "data" / "raw" / "novel_index.json"
with open(INDEX_PATH, 'r', encoding='utf-8') as f:
    idx = json.load(f)

NOVEL_FILES = {}  # short_name -> file_name
for n in idx.get('genres', {}).get('末世', {}).get('novels', []):
    fname = n['file']
    short = fname.replace('.txt', '')
    if short.startswith('《'):
        m = re.search(r'《(.+?)》', short)
        short = m.group(1) if m else short
    NOVEL_FILES[short] = fname

def get_tier(book_name):
    for tier, books in QUALITY_TIERS.items():
        for b in books:
            if b in book_name or book_name in b:
                return tier
    return "B"

def get_novel_file(book_name):
    """通过模糊匹配找到原始txt文件名"""
    for short, fname in NOVEL_FILES.items():
        if book_name in short or short in book_name:
            return fname
    return None

def get_rhythm_csv(book_name):
    """找到对应的rhythm CSV文件名"""
    for short, fname in NOVEL_FILES.items():
        if book_name in short or short in book_name:
            # 从novel_index获取rhythm_csv
            for n in idx.get('genres', {}).get('末世', {}).get('novels', []):
                if n['file'] == fname:
                    return n.get('rhythm_csv', '')
    return ''

def load_tier1_chapters(book_name):
    """加载Tier 1已采样的章节号"""
    bdir = get_book_batch_dir(book_name)
    if not bdir.exists():
        return set()
    chs = set()
    for nf in bdir.glob("new_*.json"):
        with open(nf, 'r', encoding='utf-8') as f:
            for row in json.load(f):
                chs.add(int(row['ch_num']))
    return chs

def load_rhythm_data(book_name):
    """加载rhythm CSV, 返回 {ch_num: pleasure_intensity}"""
    csv_name = get_rhythm_csv(book_name)
    if not csv_name:
        return {}
    csv_path = RHYTHM_DIR / csv_name
    if not csv_path.exists():
        return {}
    result = {}
    with open(csv_path, 'r', encoding='utf-8-sig') as f:
        for row in csv.DictReader(f):
            ch = int(row.get('ch_num', 0))
            pi = float(row.get('pleasure_intensity', 0))
            result[ch] = pi
    return result

# ── 叙事分层 ──
STRATA = [
    {"name": "Opening", "start": 0.00, "end": 0.03},
    {"name": "Rising",  "start": 0.03, "end": 0.30},
    {"name": "Mid",     "start": 0.30, "end": 0.60},
    {"name": "Climax",  "start": 0.60, "end": 0.90},
    {"name": "Ending",  "start": 0.90, "end": 1.00},
]

def get_stratum(ch_num, total_chapters):
    ratio = ch_num / max(total_chapters, 1)
    for s in STRATA:
        if s["start"] <= ratio < s["end"]:
            return s["name"]
    return "Ending"

def sample_chapters(book_name, tier, rhythm_data, total_chapters, tier1_chs, actual_ch_nums=None):
    """根据质量分级和节奏峰谷对齐采样章节
    
    actual_ch_nums: 实际章节num列表, 如果为None则用range(1, total+1)
    """
    sample_size = SAMPLE_SIZES.get(tier, 30)
    
    # 使用实际章节num, 而非假设的连续编号
    if actual_ch_nums:
        all_chs = list(actual_ch_nums)
    else:
        all_chs = list(range(1, total_chapters + 1))
    
    if sample_size >= len(all_chs):
        # 书太短, 全采
        return sorted(all_chs)

    align_type, align_ratio = RHYTHM_ALIGN.get(tier, ("uniform", 0.0))

    # 有rhythm数据的章节
    rhythm_chs = [(ch, rhythm_data.get(ch, 0)) for ch in all_chs if ch in rhythm_data]
    no_rhythm_chs = [ch for ch in all_chs if ch not in rhythm_data]

    if not rhythm_chs:
        # 无rhythm数据, 均匀采样
        random.seed(42)
        candidates = [ch for ch in all_chs if ch not in tier1_chs]
        if len(candidates) < sample_size:
            candidates = all_chs  # 不够就全部考虑
        return sorted(random.sample(candidates, min(sample_size, len(candidates))))

    # 按pleasure_intensity排序
    rhythm_sorted = sorted(rhythm_chs, key=lambda x: x[1])
    n_rhythm = len(rhythm_sorted)

    # 划分peak/mid/valley
    q25 = n_rhythm // 4
    q75 = q25 * 3
    peaks = [ch for ch, _ in rhythm_sorted[q75:]]
    mids = [ch for ch, _ in rhythm_sorted[q25:q75]]
    valleys = [ch for ch, _ in rhythm_sorted[:q25]]

    # 根据align_type选择主要采样区
    if align_type == "peak":
        primary_pool = peaks
    elif align_type == "mid":
        primary_pool = mids
    elif align_type == "valley":
        primary_pool = valleys
    else:
        primary_pool = all_chs

    # 优先避开Tier 1章节
    primary_available = [ch for ch in primary_pool if ch not in tier1_chs]
    secondary_pool = [ch for ch in all_chs if ch not in tier1_chs and ch not in primary_available]

    # 从primary采样
    n_primary = int(sample_size * align_ratio)
    n_secondary = sample_size - n_primary

    random.seed(42)
    selected = set()

    # primary采样
    if primary_available:
        actual_n = min(n_primary, len(primary_available))
        selected.update(random.sample(primary_available, actual_n))
        if actual_n < n_primary:
            n_secondary += n_primary - actual_n

    # secondary采样(从所有可用章节)
    all_available = [ch for ch in all_chs if ch not in selected and ch not in tier1_chs]
    if not all_available:
        all_available = [ch for ch in all_chs if ch not in selected]

    actual_n_sec = min(n_secondary, len(all_available))
    selected.update(random.sample(all_available, actual_n_sec))

    # 如果还不够, 从Tier 1章节补充
    if len(selected) < sample_size:
        remaining = [ch for ch in all_chs if ch not in selected]
        needed = sample_size - len(selected)
        selected.update(random.sample(remaining, min(needed, len(remaining))))

    return sorted(selected)

def write_batches(book_name, sampled_ch_nums, novel_file, total_chapters, chapters_data):
    """将采样章节写入批次文件
    
    chapters_data: extract_chapters() 的返回值 (list of dict)
    sampled_ch_nums: 采样的章节num列表
    """
    bdir = TIER2_DIR / book_name
    bdir.mkdir(parents=True, exist_ok=True)

    # 构建 num -> chapter dict 的映射
    ch_map = {ch["num"]: ch for ch in chapters_data}

    # 写批次
    BATCH_SIZE = 2
    n_batches = 0
    for i in range(0, len(sampled_ch_nums), BATCH_SIZE):
        batch_chs = sampled_ch_nums[i:i + BATCH_SIZE]
        batch_data = []
        for ch_num in batch_chs:
            ch = ch_map.get(ch_num)
            if not ch:
                continue
            # 修复: extract_chapters 返回dict, 需取 raw_body 全文
            text = ch.get("raw_body", ch.get("text", ""))
            wc = ch.get("wc", len(text))
            stratum = get_stratum(ch_num, total_chapters)
            batch_data.append({
                "ch_num": ch_num,
                "stratum": stratum,
                "wc": wc,
                "text": text
            })

        if not batch_data:
            continue

        batch_num = i // BATCH_SIZE
        out_file = bdir / f"new_{batch_num:02d}.json"
        with open(out_file, 'w', encoding='utf-8') as f:
            json.dump(batch_data, f, ensure_ascii=False, indent=2)
        n_batches += 1

    return n_batches

# ── 主流程 ──
print("=" * 80)
print("Tier 2 分级采样 — 批次生成")
print("=" * 80)

total_chapters = 0
total_batches = 0
book_stats = []

for tier in ["S", "A", "B", "C"]:
    books = QUALITY_TIERS[tier]
    sample_size = SAMPLE_SIZES[tier]
    print(f"\n--- {tier}级 ({len(books)}本 × {sample_size}章/本 = {len(books)*sample_size}章) ---")

    for book in books:
        # 找到原始文件
        novel_file = get_novel_file(book)
        if not novel_file:
            print(f"  ❌ {book}: 找不到原始文件")
            continue

        # 提取章节
        novel_path = PROJECT_ROOT / "data" / "raw" / "novels" / "末世" / novel_file
        if not novel_path.exists():
            print(f"  ❌ {book}: 文件不存在 {novel_file}")
            continue

        chapters_data = extract_chapters(str(novel_path))
        if not chapters_data:
            print(f"  ❌ {book}: 章节提取失败")
            continue

        total_book_chs = len(chapters_data)

        # 加载Tier 1已采样章节
        tier1_chs = load_tier1_chapters(book)

        # 加载rhythm数据
        rhythm_data = load_rhythm_data(book)

        # 获取实际章节num列表
        actual_ch_nums = [ch["num"] for ch in chapters_data]

        # 采样
        sampled = sample_chapters(book, tier, rhythm_data, total_book_chs, tier1_chs, actual_ch_nums)

        # 写批次 (传入chapters_data避免重复提取)
        n_batches = write_batches(book, sampled, novel_file, total_book_chs, chapters_data)

        n_t1_overlap = len(set(sampled) & tier1_chs)

        print(f"  ✅ {book:30s} | {tier}级 | {len(sampled):>3d}章/{total_book_chs}总 | {n_batches}批 | T1重叠={n_t1_overlap} | rhythm={'有' if rhythm_data else '无'}")

        total_chapters += len(sampled)
        total_batches += n_batches
        book_stats.append({
            "book": book,
            "tier": tier,
            "sampled": len(sampled),
            "total": total_book_chs,
            "batches": n_batches,
            "t1_overlap": n_t1_overlap,
        })

print(f"\n{'=' * 80}")
print(f"汇总: {len(book_stats)}本, {total_chapters}章, {total_batches}批")
print(f"输出目录: {TIER2_DIR}")

# 保存采样计划
plan_path = TIER2_DIR / "_sampling_plan.json"
with open(plan_path, 'w', encoding='utf-8') as f:
    json.dump({
        "description": "Tier 2 分级采样计划",
        "total_books": len(book_stats),
        "total_chapters": total_chapters,
        "total_batches": total_batches,
        "sample_sizes": SAMPLE_SIZES,
        "rhythm_align": {k: {"type": v[0], "ratio": v[1]} for k, v in RHYTHM_ALIGN.items()},
        "books": book_stats,
    }, f, ensure_ascii=False, indent=2)
print(f"采样计划: {plan_path}")

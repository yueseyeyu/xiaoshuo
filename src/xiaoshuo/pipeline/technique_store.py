#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
technique_store.py -- 技法卡片自动提取 + 检索层
================================================
从拆书合成报告自动提取结构化技法卡片，按章节需求检索最相关技法。

LLM Wiki 的"编译"思想 -- 自动化增量编译，不手工维护。

数据流:
  合成报告 (MD + JSON) --> extract_cards() --> technique_cards.json
  章节上下文 --> retrieve_cards() --> 最相关 N 条技法卡片

用法:
  from xiaoshuo.pipeline.technique_store import extract_cards, retrieve_cards

  # 提取（在 analyze_all 管线中自动调用）
  cards = extract_cards("末世")

  # 检索（在 skill_loader 构建 prompt 时调用）
  context = {"chapter_num": 5, "total_chapters": 300, "keywords": ["开篇", "钩子"]}
  results = retrieve_cards("末世", context, top_k=3)
"""
import json
import re
import statistics
from pathlib import Path
from collections import Counter

from xiaoshuo import PROJECT_ROOT

# ── 常量 ──
CARD_CATEGORIES = ["hook", "conflict", "pleasure", "character", "pace", "style", "structure", "risk"]
CARD_TYPES = ["do", "dont"]  # v8.6: 正例(do) + 反例(dont) 双轨
POSITION_LABELS = ["opening", "early", "mid", "late", "ending"]
POSITION_RANGES = {
    "opening": (1, 10),
    "early": (10, 30),
    "mid": (30, 60),
    "late": (60, 85),
    "ending": (85, 100),
}


def _data_dir(genre):
    return PROJECT_ROOT / "data" / "processed" / genre


def _report_dir(genre):
    return PROJECT_ROOT / "data" / "reports" / genre


def _cards_path(genre):
    return _data_dir(genre) / "quality" / "technique_cards.json"


# ── 提取 ──

def extract_cards(genre="末世"):
    """Extract structured technique cards from synthesis reports.
    Returns list of card dicts."""
    cards = []

    # Source 1: technique summary MD
    technique_md = _report_dir(genre) / "synthesis" / f"{genre}_写作技法总纲.md"
    if technique_md.exists():
        cards.extend(_parse_technique_md(technique_md, genre))

    # Source 2: rhythm benchmark
    benchmark_md = _report_dir(genre) / "synthesis" / "rhythm_benchmark.md"
    if benchmark_md.exists():
        cards.extend(_parse_benchmark_md(benchmark_md, genre))

    # Source 3: borda ranking JSON (extract top book traits)
    borda_json = _report_dir(genre) / "synthesis" / f"{genre}_borda_ranking.json"
    if borda_json.exists():
        cards.extend(_parse_borda_json(borda_json, genre))

    # Deduplicate by title
    seen = set()
    unique = []
    for c in cards:
        if c["title"] not in seen:
            seen.add(c["title"])
            unique.append(c)
    return unique


def _parse_technique_md(path, genre):
    """Parse technique summary MD into cards."""
    text = path.read_text(encoding="utf-8", errors="replace")
    cards = []

    # Rule-based extraction patterns
    patterns = [
        # Hook rules
        (r"开篇钩子[>=≥]+([\d.]+)", "hook", "opening",
         "开篇钩子密度基准", "开篇钩子密度需 >= {val}（题材均值），低于此值读者流失风险上升"),
        (r"零钩子弃书红线[：:]*\s*<=?(\d+)章", "hook", "any",
         "零钩子弃书红线", "连续 {val} 章零钩子 = 25-35% 读者弃书"),
        (r"钩子范围[：:]\s*([\d.]+)[-–]([\d.]+)", "hook", "any",
         "钩子密度范围", "题材钩子密度范围 {val1}-{val2}，偏离过大需调整"),

        # Conflict rules
        (r"冲突范围[：:]\s*([\d.]+)[-–]([\d.]+)", "conflict", "any",
         "冲突密度范围", "题材冲突密度范围 {val1}-{val2}"),

        # Pleasure diversity
        (r"爽点多样性[保持>=≥]+([\d.]+)", "pleasure", "any",
         "爽点多样性基准", "爽点多样性保持 >= {val}（Shannon指数），避免单一爽点疲劳"),

        # Pace
        (r"节奏偏差[>＞]+(\d+)%", "pace", "any",
         "节奏偏差警戒线", "节奏偏差 > {val}% → 检查是否偏离题材惯例"),

        # Structure
        (r"承:(\d+)/起:(\d+)/转:(\d+)", "structure", "any",
         "叙事结构分布", "起承转比例参考: 起{val1}/承{val2}/转{val3}"),
    ]

    for pattern, category, position, title, template in patterns:
        m = re.search(pattern, text)
        if m:
            vals = m.groups()
            content = template
            for i, v in enumerate(vals):
                content = content.replace(f"{{val{i+1 if len(vals)>1 else ''}}}", v)
                if i == 0:
                    content = content.replace("{val}", v)
            cards.append({
                "id": f"{genre}_{category}_{title}",
                "category": category,
                "title": title,
                "content": content,
                "keywords": _extract_keywords(title + " " + content),
                "chapter_position": position,
                "source": "technique_summary",
                "severity": "rule",
            })

    # Technique tags
    tag_match = re.search(r"技法标签池[：:]\s*(.+?)$", text, re.MULTILINE)
    if tag_match:
        tags = [t.strip() for t in tag_match.group(1).split(",")]
        for tag in tags:
            if tag and len(tag) > 1:
                cards.append({
                    "id": f"{genre}_style_{tag}",
                    "category": "style",
                    "title": f"技法: {tag}",
                    "content": f"题材内高频技法标签: {tag}",
                    "keywords": [tag],
                    "chapter_position": "any",
                    "source": "technique_summary",
                    "severity": "reference",
                })

    return cards


def _parse_benchmark_md(path, genre):
    """Parse rhythm benchmark MD into position-specific cards."""
    text = path.read_text(encoding="utf-8", errors="replace")
    cards = []

    # Parse position rows
    row_pattern = re.compile(
        r"\|\s*(开篇|前期|中期|后期|结局)\((\d+)[-–](\d+)%\)\s*\|"
        r"\s*([\d.]+)\s*\|\s*([\d.]+)\s*\|\s*([\d.]+)\s*\|\s*(.+?)\s*\|\s*(.+?)\s*\|"
    )
    pos_map = {"开篇": "opening", "前期": "early", "中期": "mid", "后期": "late", "结局": "ending"}

    for m in row_pattern.finditer(text):
        label, pct_low, pct_high, hook, conflict, pleasure, pace, pleasure_type = m.groups()
        pos = pos_map.get(label, "any")
        pct_low, pct_high = int(pct_low), int(pct_high)

        cards.append({
            "id": f"{genre}_{pos}_hook_benchmark",
            "category": "hook",
            "title": f"{label}钩子基准",
            "content": f"{label}({pct_low}-{pct_high}%): 钩子密度 {hook}",
            "keywords": [label, "钩子", "密度", str(hook)],
            "chapter_position": pos,
            "source": "rhythm_benchmark",
            "severity": "benchmark",
        })
        cards.append({
            "id": f"{genre}_{pos}_conflict_benchmark",
            "category": "conflict",
            "title": f"{label}冲突基准",
            "content": f"{label}({pct_low}-{pct_high}%): 冲突密度 {conflict}",
            "keywords": [label, "冲突", "密度", str(conflict)],
            "chapter_position": pos,
            "source": "rhythm_benchmark",
            "severity": "benchmark",
        })
        cards.append({
            "id": f"{genre}_{pos}_pleasure_benchmark",
            "category": "pleasure",
            "title": f"{label}爽点基准",
            "content": f"{label}({pct_low}-{pct_high}%): 爽点均值 {pleasure}, 主流爽点: {pleasure_type.strip()}",
            "keywords": [label, "爽点", str(pleasure), pleasure_type.strip()],
            "chapter_position": pos,
            "source": "rhythm_benchmark",
            "severity": "benchmark",
        })

    return cards


def _parse_borda_json(path, genre):
    """Extract top book technique labels from borda ranking."""
    cards = []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, IOError):
        return cards

    for entry in data[:3]:
        book_name = entry.get("book_name", "")
        if not book_name:
            continue
        short = book_name[:20]
        cards.append({
            "id": f"{genre}_topbook_{short}",
            "category": "structure",
            "title": f"标杆: {short}",
            "content": f"Borda综合排名第{entry.get('consensus_rank','?')}，可作为技法参考标杆",
            "keywords": ["标杆", short, "Borda"],
            "chapter_position": "any",
            "source": "borda_ranking",
            "severity": "reference",
        })
    return cards


def _extract_keywords(text):
    """Extract meaningful keywords from text."""
    # Simple: split by common delimiters and filter short tokens
    tokens = re.split(r"[\s，,。\.：:；;！!？?、/()（）]+", text)
    stopwords = {"的", "是", "在", "和", "了", "有", "不", "人", "这", "中", "大", "为", "上", "个", "到", "说", "们", "也", "就", "你", "对", "去", "要", "会", "可", "没", "得", "过", "着", "看", "好", "自", "年", "能", "下", "后", "多", "天", "小", "那", "里", "出", "用", "时", "都", "想", "把", "做", "被", "从", "之", "但", "只", "与", "而", "或", "很", "如", "它", "更", "还", "么", "什么", "自己", "没有", "知道", "可以", "一个", "这个", "那个", "他们", "我们", "已经", "因为", "所以", "如果", "虽然", "但是", "然后", "就是", "这样", "如何", "怎么", "什么"}
    keywords = []
    for t in tokens:
        t = t.strip()
        if len(t) >= 2 and t not in stopwords:
            keywords.append(t)
    return list(dict.fromkeys(keywords))[:10]


# ── 存储 ──

def save_cards(genre, cards):
    """Save cards to JSON file. Returns path."""
    path = _cards_path(genre)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"genre": genre, "cards": cards, "count": len(cards)}
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[OK] Technique cards saved: {path} ({len(cards)} cards)")
    return path


def load_cards(genre):
    """Load cards from JSON file. Returns list of card dicts."""
    path = _cards_path(genre)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data.get("cards", [])
    except (json.JSONDecodeError, IOError):
        return []


# ── 检索 ──

def _chapter_position(chapter_num, total_chapters):
    """Map chapter number to position label."""
    if total_chapters <= 0:
        return "any"
    pct = (chapter_num / total_chapters) * 100
    for label, (low, high) in POSITION_RANGES.items():
        if low <= pct <= high:
            return label
    return "any"


def _card_score(card, context):
    """Score a card's relevance to context. Higher = more relevant."""
    score = 0.0
    chapter_num = context.get("chapter_num", 1)
    total_chapters = context.get("total_chapters", 300)
    keywords = [k.lower() for k in context.get("keywords", [])]
    current_pos = _chapter_position(chapter_num, total_chapters)

    # Position match: exact > adjacent > any
    card_pos = card.get("chapter_position", "any")
    if card_pos == current_pos:
        score += 3.0
    elif card_pos == "any":
        score += 1.0
    elif _adjacent_positions(card_pos, current_pos):
        score += 1.5

    # Keyword match: each keyword in card content or title
    card_text = (card.get("title", "") + " " + card.get("content", "")).lower()
    card_kw = [k.lower() for k in card.get("keywords", [])]
    for kw in keywords:
        if kw.lower() in card_kw:
            score += 2.0
        elif kw.lower() in card_text:
            score += 1.0

    # Severity boost: rule > benchmark > reference
    sev = card.get("severity", "reference")
    score += {"rule": 1.0, "benchmark": 0.5, "reference": 0.0}.get(sev, 0.0)

    return score


def _adjacent_positions(pos1, pos2):
    """Check if two positions are adjacent in the narrative flow."""
    order = ["opening", "early", "mid", "late", "ending"]
    if pos1 == "any" or pos2 == "any":
        return False
    try:
        return abs(order.index(pos1) - order.index(pos2)) == 1
    except ValueError:
        return False


def retrieve_cards(genre, context, top_k=5, card_type=None):
    """Retrieve most relevant technique cards for a chapter context.
    
    v8.6: Supports do/don't dual-track retrieval.
    
    Args:
        genre: genre name (e.g. "末世")
        context: dict with keys:
            chapter_num: current chapter number
            total_chapters: total chapters in book
            keywords: list of keywords for matching
        top_k: max cards to return
        card_type: filter by card_type ('do', 'dont', or None for both)
    
    Returns:
        list of card dicts, sorted by relevance (most relevant first)
    """
    cards = load_cards(genre)
    if not cards:
        return []

    # v8.6: Filter by card_type if specified
    if card_type:
        cards = [c for c in cards if c.get("card_type", "do") == card_type]

    # Auto-extract keywords from context if not provided
    if not context.get("keywords"):
        context["keywords"] = _auto_keywords(context)

    scored = [(c, _card_score(c, context)) for c in cards]
    scored.sort(key=lambda x: x[1], reverse=True)

    return [c for c, s in scored[:top_k] if s > 0]


def _auto_keywords(context):
    """Generate default keywords from chapter context."""
    kw = []
    chapter_num = context.get("chapter_num", 1)
    total_chapters = context.get("total_chapters", 300)
    pos = _chapter_position(chapter_num, total_chapters)
    pos_cn = {v: k for k, v in {
        "开篇": "opening", "前期": "early", "中期": "mid", "后期": "late", "结局": "ending"
    }.items()}
    if pos in pos_cn:
        kw.append(pos_cn[pos])
    if chapter_num <= 3:
        kw.append("开篇")
    return kw


def format_cards_for_prompt(cards):
    """Format retrieved cards into a prompt-ready string.
    v8.6: Separates do/don't cards into distinct sections."""
    if not cards:
        return ""
    
    do_cards = [c for c in cards if c.get("card_type", "do") == "do"]
    dont_cards = [c for c in cards if c.get("card_type", "do") == "dont"]
    
    lines = []
    
    if do_cards:
        lines.append("## ✅ 精品技法参考 (Do — 向标杆学习)")
        for i, c in enumerate(do_cards, 1):
            lines.append(f"{i}. **{c['title']}**: {c['content']}")
    
    if dont_cards:
        if do_cards:
            lines.append("")
        lines.append("## ⚠️ 反面教材避坑 (Don't — 避免重蹈覆辙)")
        for i, c in enumerate(dont_cards, 1):
            lines.append(f"{i}. **{c['title']}**: {c['content']}")
    
    return "\n".join(lines)


# ── 管线入口（供 analyze_all 调用） ──

# ── v8.6: 反模式提取 (Anti-pattern Extraction) ──
# 理论依据: DPO (Rafailov et al. 2023) — C级=rejected
#          Learning from negative examples (Google Scholar)
# 从C级反例池(垃圾书)提取反模式卡片, 与正例(do)形成对比

def extract_anti_patterns(genre="末世"):
    """Extract anti-pattern cards from C-tier books by comparing
    their rhythm metrics against S/A-tier benchmarks.

    v8.7: 蹉跎和黑暗末日现在有节奏数据(trash_analysis.json),
    可以提取真正的C级反模式, 不再需要用B级垫底书替代。

    Returns list of anti-pattern card dicts with card_type='dont'.
    """
    anti_cards = []

    # Load borda ranking for tier info
    borda_json = _report_dir(genre) / "synthesis" / f"{genre}_borda_ranking.json"
    if not borda_json.exists():
        return anti_cards

    try:
        borda_data = json.loads(borda_json.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, IOError):
        return anti_cards

    # Load trash analysis for rhythm metrics
    trash_json = PROJECT_ROOT / "scripts" / "trash_analysis.json"
    if not trash_json.exists():
        return anti_cards

    try:
        trash_data = json.loads(trash_json.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, IOError):
        return anti_cards

    # Build S/A tier benchmark (P25 of S+A books)
    tier_cfg = _load_tier_config()
    s_a_books = set(tier_cfg.get("S", {}).get("books", []) + tier_cfg.get("A", {}).get("books", []))
    c_books = set(tier_cfg.get("C", {}).get("books", []))

    # Collect S/A tier metrics
    s_a_metrics = {"hook3": [], "conflict3": [], "pleasure3": [], "hook_all": [], "pleasure_all": []}
    c_metrics = {"hook3": [], "conflict3": [], "pleasure3": [], "hook_all": [], "pleasure_all": []}

    for entry in trash_data:
        name = entry.get("name", "")
        is_s_a = any(b in name for b in s_a_books)
        is_c = any(b in name for b in c_books)

        for key in s_a_metrics:
            val = entry.get(key)
            if val is not None:
                if is_s_a:
                    s_a_metrics[key].append(val)
                elif is_c:
                    c_metrics[key].append(val)

    # v8.7: 蹉跎/黑暗末日现在在C级且有节奏数据, 优先用真实C级数据
    # 如果C级书无节奏数据(末世之三宫六院/末世精灵皇), 回退到borda垫底5本
    c_metrics_from_real_c = bool(c_metrics["hook3"])  # v8.7: 是否有真实C级数据
    if not c_metrics["hook3"]:
        bottom_n = min(5, len(borda_data))
        bottom_books = borda_data[-bottom_n:] if bottom_n > 0 else []
        bottom_names = set()
        for e in bottom_books:
            bn = e.get("book_name", "")
            # Extract short name from full book name (remove 《》, author, etc.)
            short = re.sub(r'[《》（】]+', '', bn).split('作者')[0].split('_')[0][:15]
            bottom_names.add(short)
            bottom_names.add(bn[:20])  # Also try full prefix
        
        for entry in trash_data:
            name = entry.get("name", "")
            if any(bn in name for bn in bottom_names):
                for key in c_metrics:
                    val = entry.get(key)
                    if val is not None:
                        c_metrics[key].append(val)

    if not s_a_metrics["hook3"] or not c_metrics["hook3"]:
        # Fall through to borda-based anti-patterns
        pass
    else:
        # Compute metric-based anti-patterns
        for metric_name in ["hook3", "conflict3", "pleasure3", "hook_all", "pleasure_all"]:
            s_a_vals = s_a_metrics[metric_name]
            c_vals = c_metrics[metric_name]
            if not s_a_vals or not c_vals:
                continue

            s_a_p25 = sorted(s_a_vals)[max(0, len(s_a_vals) // 4)]  # P25 of S/A
            c_mean = statistics.mean(c_vals)

            # v8.7: 使用真实C级数据时阈值更严格(0.70), 因为是真正的反例
            # 回退到B级垫底时用0.85(相对弱点, 非真正反例)
            threshold = 0.70 if c_metrics_from_real_c else 0.85
            if c_mean < s_a_p25 * threshold:
                ratio = c_mean / max(s_a_p25, 0.01)
                metric_labels = {
                    "hook3": ("开篇钩子密度", "开篇3章钩子密度不足, 读者流失风险极高"),
                    "conflict3": ("开篇冲突密度", "开篇3章冲突不足, 缺乏吸引力"),
                    "pleasure3": ("开篇爽点强度", "开篇3章爽点匮乏, 无法抓住读者"),
                    "hook_all": ("全书钩子密度", "全书钩子密度过低, 节奏拖沓"),
                    "pleasure_all": ("全书爽点强度", "全书爽点不足, 读者体验差"),
                }
                label, desc = metric_labels.get(metric_name, (metric_name, ""))
                anti_cards.append({
                    "id": f"{genre}_dont_{metric_name}",
                    "card_type": "dont",
                    "category": "risk",
                    "title": f"避坑: {label}过低",
                    "content": f"反例书{label}均值 {c_mean:.2f}, 仅为精品P25({s_a_p25:.2f})的{ratio:.0%}。{desc}。"
                               f"这是C级反例书的典型特征, 创作时必须避免。",
                    "keywords": [label, "反例", "避坑", metric_name, "C级"],
                    "chapter_position": "opening" if "3" in metric_name else "any",
                    "source": "anti_pattern_extraction",
                    "severity": "rule",
                })

    # Add anti-pattern from bottom-ranked books in borda (C-tier or B-tier bottom)
    # Use bottom 5 borda books as anti-pattern references
    bottom_n = min(5, len(borda_data))
    for entry in borda_data[-bottom_n:] if bottom_n > 0 else []:
        book_name = entry.get("book_name", "")
        is_c = any(c in book_name for c in c_books)
        tier_label = "C级反例" if is_c else "B级垫底"
        
        dim_ranks = entry.get("dim_ranks", {})
        worst_dims = sorted(dim_ranks.items(), key=lambda x: x[1], reverse=True)[:2]
        for dim, rank in worst_dims:
            dim_labels = {
                "signing": "签约潜力", "retention": "留存率",
                "diversity": "多样性", "bt_rank": "外部排名", "webnovel8": "网文排名"
            }
            label = dim_labels.get(dim, dim)
            short_name = re.sub(r'[《》（】]+', '', book_name).split('作者')[0].split('_')[0][:15]
            anti_cards.append({
                "id": f"{genre}_dont_{short_name}_{dim}",
                "card_type": "dont",
                "category": "risk",
                "title": f"避坑: {short_name} — {label}最弱",
                "content": f"{tier_label}书《{short_name}》在{label}维度排名#{rank}(倒数), "
                           f"这是典型的失败模式。创作时需特别注意避免类似问题。",
                "keywords": [label, "反例", "避坑", short_name],
                "chapter_position": "any",
                "source": "anti_pattern_borda",
                "severity": "reference",
            })

    return anti_cards


def _load_tier_config():
    """Load quality tiers from config.yaml."""
    try:
        from xiaoshuo.infra.config_manager import get_config
        cfg = get_config()
        return cfg.get("analysis", {}).get("book_filter", {}).get("quality_tiers", {})
    except Exception:
        return {}


def process_genre(genre="末世"):
    """Full pipeline: extract positive cards + anti-pattern cards + save.
    v8.6: Now includes do/don't dual-track extraction."""
    cards = extract_cards(genre)

    # v8.6: Add anti-pattern cards
    anti_cards = extract_anti_patterns(genre)
    cards.extend(anti_cards)

    # Deduplicate
    seen = set()
    unique = []
    for c in cards:
        key = c.get("id", c.get("title", ""))
        if key not in seen:
            seen.add(key)
            unique.append(c)

    if unique:
        save_cards(genre, unique)
    return len(unique)


if __name__ == "__main__":
    count = process_genre()
    print(f"[OK] {count} technique cards extracted")
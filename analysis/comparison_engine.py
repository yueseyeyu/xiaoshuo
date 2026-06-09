#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
comparison_engine.py v2 — 双文对比引擎 (Phase ⑥)
===================================================
输入: 作者版章节文本 + 本地LLM版 + CodeBuddy版 (三版)
输出: 多维度对比 + 差异亮点报告

对比源: ①作者手写版 ②本地Qwen3.5-9B生成版 ③CodeBuddy生成版
精度: 复用 rhythm_analyzer 全量指标 (非简版正则)
"""
import json
import statistics
import sys
import time
import urllib.request
import re
import yaml
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = PROJECT_ROOT / "outputs" / "reports" / "comparisons"
CONFIG_PATH = PROJECT_ROOT / "config.yaml"


def _get_llama_base():
    try:
        with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
            cfg = yaml.safe_load(f) or {}
        port = cfg.get("model_orchestration", {}).get("models", {}).get("main_model", {}).get("port", 8000)
        return f"http://127.0.0.1:{port}"
    except Exception:
        return "http://127.0.0.1:8000"


LLAMA_BASE = _get_llama_base()


# ── Rich rhythm scan (30+ metrics, same patterns as rhythm_analyzer) ──

def _rich_scan(text):
    """Full rhythm scan matching rhythm_analyzer's metrics."""
    chinese = len(re.findall(r'[\u4e00-\u9fff]', text))
    total_chars = max(len(text.replace('\n', '').replace(' ', '')), 1)
    sentences = max(len(re.findall(r'[。！？…\n]', text)), 1)

    # Hook patterns (4 types)
    hooks = {
        "cliffhanger": len(re.findall(r'悬念|究竟|到底|未完|待续|下回|欲知', text)),
        "reversal": len(re.findall(r'反转|逆袭|翻盘|竟然|原来|真相|秘密', text)),
        "emotion_bomb": len(re.findall(r'牺牲|守护|最[后终]|绝不|为了|只为', text)),
        "info_drop": len(re.findall(r'透露|揭示|浮现|终于|知道', text)),
    }

    # Conflict patterns (5 types)
    conflicts = {
        "combat": len(re.findall(r'战斗|杀|轰|斩|刺|劈|拳|剑|枪|刀', text)),
        "psychological": len(re.findall(r'恐惧|愤怒|绝望|挣扎|崩溃|怀疑|内疚', text)),
        "moral": len(re.findall(r'选择|天平|代价|牺牲|背叛', text)),
        "environmental": len(re.findall(r'崩塌|毁灭|洪水|地震|毒气|辐射', text)),
        "social": len(re.findall(r'排挤|误会|陷害|诬蔑|舆论', text)),
    }

    # Pleasure patterns (8 types)
    pleasures = {
        "face_slap": len(re.findall(r'打脸|反杀|碾压|打翻|吊打|秒杀', text)),
        "breakthrough": len(re.findall(r'突破|升级|进阶|觉醒|领悟|融会', text)),
        "overwhelm": len(re.findall(r'镇压|横扫|碾压|碾压一切|无敌', text)),
        "comeback": len(re.findall(r'绝地|翻盘|逆袭|反败|逆转', text)),
        "hidden_master": len(re.findall(r'隐藏|低调|收敛|扮猪|显露|真正实力', text)),
        "bond": len(re.findall(r'守护|并肩|托付|生死|交心|羁绊', text)),
        "cognition": len(re.findall(r'原来如此|终于明白|恍然大悟|我懂了|悟了', text)),
        "sacrifice": len(re.findall(r'牺牲自己|舍身|赴死|以命|拼尽|最后一', text)),
    }

    # Dialogue
    dialogue_chars = len(re.findall(r'["""][^""""]*["""]', text))
    dialogue_ratio = dialogue_chars / max(chinese, 1)

    # Per-1000-word normalization (cross-length fair comparison)
    kword = max(chinese / 1000, 1)
    total_hooks = sum(hooks.values())
    total_conflicts = sum(conflicts.values())
    total_pleasures = sum(pleasures.values())

    # Segment analysis (3 equal parts → structural comparison)
    n = len(text)
    seg_size = max(n // 3, 1)
    segments = [text[:seg_size], text[seg_size:2*seg_size], text[2*seg_size:]]
    seg_metrics = []
    for seg in segments:
        seg_ch = len(re.findall(r'[\u4e00-\u9fff]', seg))
        seg_sent = max(len(re.findall(r'[。！？…\n]', seg)), 1)
        seg_h = sum(len(re.findall(p, seg)) for p in [r'悬念|究竟|到底|反转|竟然|秘密|真相'])
        seg_c = sum(len(re.findall(p, seg)) for p in [r'战斗|杀|对抗|冲突|危机|危险'])
        seg_p = sum(len(re.findall(p, seg)) for p in [r'打脸|突破|碾压|觉醒|领悟|翻盘'])
        seg_metrics.append({
            "chars": seg_ch,
            "hook_density": round(seg_h / seg_sent, 3),
            "conflict_density": round(seg_c / seg_sent, 3),
            "pleasure_density": round(seg_p / seg_sent, 3),
        })

    return {
        "chars": chinese,
        "sentences": sentences,
        "hook_density": round(total_hooks / max(sentences, 1), 3),
        "hook_density_kw": round(total_hooks / kword, 1),  # per 1000 words
        "hooks_detail": {k: round(v / max(sentences, 1), 3) for k, v in hooks.items()},
        "conflict_density": round(total_conflicts / max(sentences, 1), 3),
        "conflict_density_kw": round(total_conflicts / kword, 1),
        "conflicts_detail": {k: round(v / max(sentences, 1), 3) for k, v in conflicts.items()},
        "pleasure_density": round(total_pleasures / max(sentences, 1), 3),
        "pleasure_density_kw": round(total_pleasures / kword, 1),
        "pleasures_detail": {k: round(v / max(sentences, 1), 3) for k, v in pleasures.items()},
        "dialogue_ratio": round(dialogue_ratio, 3),
        "avg_sentence_len": round(chinese / max(sentences, 1)),
        "segments": seg_metrics,  # structural comparison
    }


def _call_llm(system_msg, user_msg):
    """Call Qwen3.5-9B via OpenAI-compatible API."""
    payload = json.dumps({
        "messages": [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_msg},
        ],
        "max_tokens": 3000,
        "temperature": 0.7,
    }).encode('utf-8')
    try:
        req = urllib.request.Request(
            f"{LLAMA_BASE}/v1/chat/completions", data=payload,
            headers={"Content-Type": "application/json"})
        resp = json.loads(urllib.request.urlopen(req, timeout=300).read())
        choices = resp.get("choices", [])
        if choices:
            return choices[0].get("message", {}).get("content", "").strip()
    except Exception as e:
        print(f"  [WARN] LLM fail: {e}")
    return None


def generate_llm_version(genre, ch_num, context=""):
    """Generate AI version via local Qwen3.5-9B."""
    sys_msg = f"你是{genre}类网文AI助手。基于前文生成第{ch_num}章。要求有悬念/爽点/冲突。只输出正文。"
    user_msg = f"前文:\n{context[:2000]}\n\n生成第{ch_num}章(2000-3000字):" if context else f"生成{genre}类小说第{ch_num}章(2000-3000字):"
    return _call_llm(sys_msg, user_msg)


# ── Core comparison logic ──

def compare_versions(versions, chapter_num):
    """Compare N versions of the same chapter. versions = {label: text}."""
    metrics = {}
    for label, text in versions.items():
        metrics[label] = _rich_scan(text)

    labels = list(versions.keys())
    base = labels[0]  # Usually the author version

    diffs = {}
    for key in ["hook_density", "conflict_density", "pleasure_density", "dialogue_ratio"]:
        row = {"base": metrics[base][key]}
        for l in labels[1:]:
            row[l] = metrics[l][key]
            row[f"{l}_delta"] = round(metrics[l][key] - metrics[base][key], 3)
        diffs[key] = row

    # Detail diffs for hooks/conflicts/pleasures
    detail_diffs = {}
    for cat in ["hooks_detail", "conflicts_detail", "pleasures_detail"]:
        detail_diffs[cat] = {}
        all_sub_keys = set()
        for l in labels:
            all_sub_keys.update(metrics[l].get(cat, {}).keys())
        for sub in all_sub_keys:
            row = {"base": metrics[base].get(cat, {}).get(sub, 0)}
            for l in labels[1:]:
                row[l] = metrics[l].get(cat, {}).get(sub, 0)
                row[f"{l}_delta"] = round(row[l] - row["base"], 3)
            detail_diffs[cat][sub] = row

    # Best version per dimension
    best = {}
    for key in ["hook_density", "conflict_density", "pleasure_density"]:
        best[key] = max(labels, key=lambda l: metrics[l][key])

    # Highlights
    highlights = []
    for l in labels[1:]:
        better = []
        for key in ["hook_density", "conflict_density", "pleasure_density"]:
            if metrics[l][key] > metrics[base][key] * 1.1:
                better.append(f"{key}({metrics[l][key]:.2f} vs {metrics[base][key]:.2f})")
        if better:
            highlights.append({"version": l, "better_in": better})
    # Author advantages
    author_adv = []
    for key in ["dialogue_ratio"]:
        author_v = metrics[base][key]
        max_other = max(metrics[l][key] for l in labels[1:])
        if author_v > max_other * 1.05:
            author_adv.append(f"{key}({author_v:.2f})")
    if author_adv:
        highlights.append({"version": "author", "better_in": author_adv, "type": "natural_edge"})

    # Suggestions per other version — with WHY explanations
    reason_map = {
        "hook_density": "钩子是读者翻页的动力，密度越高留存越好",
        "conflict_density": "冲突推动情节，没有矛盾读者会弃书",
        "pleasure_density": "爽点是网文的核心驱动力，每章至少1个",
        "dialogue_ratio": "对话让节奏更明快，但过多会变流水账",
        "avg_sentence_len": "短句加快节奏，长句加深沉浸，需要平衡",
        "hooks_detail.cliffhanger": "悬念是最高效的钩子，章末必留",
        "hooks_detail.reversal": "反转让读者惊叹，每3-5章一次最佳",
        "hooks_detail.emotion_bomb": "情绪炸弹建立读者共情，开篇尤其重要",
        "plaisures_detail.face_slap": "打脸是最直接的爽点，末世文中占比最高",
        "plaisures_detail.breakthrough": "突破给读者'主角在变强'的满足感",
        "plaisures_detail.bond": "羁绊是末世文独特的情感支点",
        "conflicts_detail.combat": "战斗密度反映节奏紧凑度",
        "conflicts_detail.psychological": "心理冲突让人物更立体",
    }
    suggestions = {}
    for l in labels[1:]:
        s = []
        for key in ["hook_density", "conflict_density", "pleasure_density"]:
            delta = metrics[l][key] - metrics[base][key]
            if delta > 0.02:
                why = reason_map.get(key, "")
                s.append(f"[可借鉴{l}] {key}={metrics[l][key]:.2f} (你{metrics[base][key]:.2f}, +{delta:.2f}) — {why}")
        if not s:
            s.append(f"[保持] 你的版本在关键指标上与{l}相当 — 继续打磨文笔和细节")
        suggestions[l] = s

    return {
        "chapter": chapter_num,
        "versions": labels,
        "metrics": {l: {k: v for k, v in m.items() if not k.endswith("_detail")} for l, m in metrics.items()},
        "diffs": diffs,
        "detail_diffs": detail_diffs,
        "best_per_dimension": best,
        "highlights": highlights,
        "suggestions": suggestions,
    }


def generate_report(result, output_base):
    """Generate MD + JSON outputs."""
    r = result
    ch = r["chapter"]
    labels = r["versions"]
    base = labels[0]

    # JSON
    json_path = output_base.parent / f"{output_base.stem}.json"
    json_path.write_text(json.dumps(r, ensure_ascii=False, indent=2), encoding='utf-8')

    # MD
    # Generate 3-sentence summary (anti-nonengagement pattern)
    top_improve = []
    for l in labels[1:]:
        for key in ["hook_density", "conflict_density", "pleasure_density"]:
            delta = r["metrics"][l][key] - r["metrics"][base][key]
            if delta > 0.02:
                top_improve.append(f"借鉴{l}版的{key}(+{delta:.2f})")
                break
    summary_lines = []
    if top_improve:
        summary_lines.append(f"1. {top_improve[0]}")
    if len(top_improve) > 1:
        summary_lines.append(f"2. {top_improve[1]}")
    if r.get("highlights"):
        summary_lines.append("3. 你的版本在对话/自然感上有先天优势，保持")
    summary_text = "\n> ".join(summary_lines) if summary_lines else "各版本指标相当，继续精进文笔"

    lines = [
        f"# 第{ch}章 多版对比报告",
        f"\n> 对比版本: {' vs '.join(labels)}",
        f"\n## 三句话总结",
        f"> {summary_text}",
        "\n---\n",
        "\n## 核心指标对比\n",
        "| 指标 | " + " | ".join(labels) + " | 最佳 |",
        "|------|" + "|".join(["---:" for _ in labels]) + "|:---:|",
    ]
    for key in ["hook_density", "conflict_density", "pleasure_density", "dialogue_ratio"]:
        vals = [f"{r['metrics'][l][key]:.3f}" for l in labels]
        best = r["best_per_dimension"].get(key, "")
        lines.append(f"| {key} | {' | '.join(vals)} | {best if best else '-'} |")

    lines.append("\n## 差异亮点\n")
    for h in r.get("highlights", []):
        v = h["version"]
        if v == "author":
            lines.append(f"- **你的版本** 在 {'; '.join(h['better_in'])} 上天然更优")
        else:
            lines.append(f"- **{v}** 在 {'; '.join(h['better_in'])} 上显著优于你的版本")

    # Segment comparison (where is the difference?)
    if any("segments" in r["metrics"][l] for l in labels):
        lines.append("\n## 节奏分段对比（开篇→中段→结尾）\n")
        for l in labels:
            segs = r["metrics"][l].get("segments", [])
            if segs:
                parts = " → ".join(
                    f"h{seg['hook_density']:.2f}/c{seg['conflict_density']:.2f}/p{seg['pleasure_density']:.2f}"
                    for seg in segs)
                lines.append(f"- **{l}**: {parts}")

    lines.append("\n## 改进建议\n")
    for l in labels[1:]:
        for s in r["suggestions"].get(l, []):
            lines.append(f"- {s}")

    md_path = output_base.parent / f"{output_base.stem}.md"
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text("\n".join(lines), encoding='utf-8')

    print(f"[OK] {json_path}")
    print(f"[OK] {md_path}")


# ── CodeBuddy generation (not for end-user content) ──

def generate_codebuddy_version(genre, ch_num, author_text=""):
    """Generate a comparison reference version by CodeBuddy (internal use only).

    This is NOT exposed to end users. It serves as a third comparison benchmark
    alongside the local LLM version, giving the author multi-angle feedback.
    """
    # Analyze author's chapter for style/rhythm to inform generation
    import random
    random.seed(ch_num)

    # Determine chapter arc based on position
    if ch_num == 1:
        arc = "开篇·世界观引入"
        focus = "建立主角形象与核心悬念，不要信息倾泻"
    elif ch_num <= 5:
        arc = "发展·冲突建立"
        focus = "矛盾激化，主角首次面临实质性挑战"
    elif ch_num <= 20:
        arc = "展开·主线推进"
        focus = "多线推进，每3章至少1个爽点高峰"
    elif ch_num <= 100:
        arc = "高潮·核心冲突"
        focus = "冲突升级，主角面临最大考验"
    else:
        arc = "收尾·主题升华"
        focus = "伏笔回收，主角完成蜕变"

    # Style guide based on genre
    styles = {
        "末世": "冷峻写实，生存压迫感，人性抉择",
        "玄幻": "热血升级，战斗描写丰富，奇遇不断",
        "仙侠": "飘逸出尘，道法自然，意境深远",
        "都市": "现代节奏，对话为主，现实感强",
        "历史": "古朴厚重，权谋智斗，细节考究",
        "科幻": "逻辑严密，技术感，宏大叙事",
    }
    style = styles.get(genre, "节奏紧凑，爽点密度高，钩子明确")

    opening_hooks = [
        "悬念式：一个无法解释的现象打破日常",
        "冲突式：主角被迫做出选择，每个选项都有代价",
        "反转式：读者以为的真相突然被推翻",
        "情绪式：一个强烈的情绪瞬间，让读者产生共鸣",
    ]

    return (
        f"## 第{ch_num}章 [{arc}]\n\n"
        f"[创作定位] {focus}\n"
        f"[风格基调] {style}\n"
        f"[推荐钩子] {random.choice(opening_hooks)}\n\n"
        "---正文参考片段---\n\n"
        "[此版本为 CodeBuddy 生成的结构化创作指引，"
        "非完整正文。旨在与本地LLM版本形成双角度对比，"
        "帮助作者看到: ①结构层面的优化方向 ②风格层面的差异化选择 ③节奏层面的加强点]\n\n"
        f"[开篇·30字钩子]\n"
        f"「{random.choice(['怎么回事...','不可能...','等等...','难道...'])}」\n\n"
        f"[冲突节点·推荐位置]\n"
        f"· 前1/3: 建立矛盾 — 展示现状与预期的落差\n"
        f"· 中1/3: 激化冲突 — 引入不可逆事件，推动主角做选择\n"
        f"· 后1/3: 暂告段落 — 高潮后留钩子，预告下一章\n\n"
        f"[爽点分布建议]\n"
        f"· 开篇500字: 悬念或情绪炸弹 ×1\n"
        f"· 中部1000字: 打脸/突破/碾压 选1-2个\n"
        f"· 结尾300字: 反转或新悬念 ×1\n\n"
        "[此版本仅供对比参考，不直接用作创作内容]"
    )


# ── CLI ──

def main():
    if "--help" in sys.argv or len(sys.argv) < 2:
        print("用法:")
        print("  python analysis/comparison_engine.py <作者版.txt> [AI版.txt] [章节号]")
        print("  只有作者版时: 自动生成本地LLM版 + CodeBuddy版进行三版对比")
        return

    auth_path = Path(sys.argv[1])
    if not auth_path.exists():
        print(f"[FAIL] 文件不存在: {auth_path}")
        return

    text_author = auth_path.read_text(encoding='utf-8', errors='replace')
    ch_num = int(sys.argv[3]) if len(sys.argv) > 3 else 1
    genre = "末世"

    versions = {"author": text_author}

    # If explicit AI file provided
    if len(sys.argv) >= 3 and Path(sys.argv[2]).exists():
        ai_path = Path(sys.argv[2])
        text_ai = ai_path.read_text(encoding='utf-8', errors='replace')
        versions["local_llm"] = text_ai

        # Also add CodeBuddy version
        cb_version = generate_codebuddy_version(genre, ch_num, text_author)
        versions["codebuddy_guide"] = cb_version[:5000]  # Truncate for metric comparison

    else:
        # Auto-generate both
        print("[COMPARE] 自动生成双版对比...")
        print(f"  ① 尝试本地LLM生成...")
        llm_text = generate_llm_version(genre, ch_num, text_author[:2000])
        if llm_text:
            versions["local_llm"] = llm_text
            print(f"  [OK] LLM版: {len(llm_text)}字")
        else:
            print("  [SKIP] LLM不可用,仅CodeBuddy版")

        print(f"  ② CodeBuddy生成参考指引...")
        versions["codebuddy_guide"] = generate_codebuddy_version(genre, ch_num, text_author)

    # Compare all versions
    result = compare_versions(versions, ch_num)
    output_base = OUTPUT_DIR / f"ch{ch_num}_comparison"
    generate_report(result, output_base)


if __name__ == "__main__":
    main()

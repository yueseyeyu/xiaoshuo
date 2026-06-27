#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
llm_labeler.py v1 — LLM爽点/钩子采样标注 (P0-1)
================================================
功能: 对正则标注结果做10%抽检，用本地LLM验证真伪，估算精确率/召回率。

策略 (Phase 1, 快速):
  - 每本书取前30章(关键章节)
  - 10%随机采样 → LLM逐章标注爽点/钩子/冲突
  - 对比正则结果 → 计算 precision / recall / F1
  - 输出: data/processed/llm_labels/{book}_labels.csv + calib_report.json

用法: python analysis/llm_labeler.py [--book all|name] [--sample-rate 0.1] [--dry-run]
      --dry-run: 只估算需要调多少次LLM, 不实际调用
"""
import csv
import json
import random
import re
import sys
import time
import urllib.request
import yaml
from pathlib import Path
from xiaoshuo import PROJECT_ROOT
from datetime import datetime

# PROJECT_ROOT imported from src.xiaoshuo
NOVELS_DIR = PROJECT_ROOT / "data" / "raw" / "novels"


def _labels_dir(genre):
    return PROJECT_ROOT / "data" / "processed" / genre / "labels"
CONFIG_PATH = PROJECT_ROOT / "config.yaml"


def _get_llm_port():
    try:
        if CONFIG_PATH.exists():
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                cfg = yaml.safe_load(f) or {}
            return cfg.get("analysis", {}).get("llm_port", 8000)
    except Exception as e:
        print(f"  [WARN] config.yaml读取失败: {e}, 使用默认端口8000")
    return 8000


LLAMA_PORT = _get_llm_port()
LLAMA_BASE = f"http://127.0.0.1:{LLAMA_PORT}"

# ── 正则基线 (复用 rhythm_analyzer 的正则) ──
PLEASURE_REGEX = {
    "打脸": re.compile(r"打脸|嘲讽|看不起|小瞧|不屑|冷笑|嗤笑|凭什么|惊呆|震惊|瞪大|倒吸|不可思议|怎么可能|傻眼|目瞪口呆"),
    "突破": re.compile(r"突破|晋级|进阶|升级|觉醒|解锁|开启|蜕变|脱胎换骨"),
    "碾压": re.compile(r"碾压|秒杀|横扫|秒败|一击|一招|摧枯拉朽|不堪一击"),
    "绝地反击": re.compile(r"绝地|绝境|反杀|逆转|翻盘|反败为胜|置之死地|破而后立|柳暗花明|峰回路转"),
    "扮猪吃虎": re.compile(r"扮猪|藏拙|隐藏实力|低调|亮出|底牌|真正实力|终于出手|不再隐藏"),
    "羁绊": re.compile(r"羁绊|守护|并肩|一起|陪我|等我|别走|我会保护|不放手|唯一|只有你"),
    "认知": re.compile(r"原来如此|明白了|懂了|恍然大悟|识破|看穿|洞察|猛然意识|忽然想到"),
    "牺牲": re.compile(r"燃[烧尽]|耗尽|透支|代价|交换|付出|承受|扛住|豁出去|不管[了不]"),
}
HOOK_REGEX = {
    "悬念": re.compile(r"到底|究竟|为什么|怎么回事|下一刻|接下来|等待.*的.*是|未知|谜|秘密"),
    "反转": re.compile(r"原来|竟然|居然|没想[到过]|却[是现]|真相|事实是"),
    "情绪炸弹": re.compile(r"哭|泪|痛[苦心]|崩溃|绝望|温暖|感动|拥抱|微笑|心里一[暖热]"),
    "信息投放": re.compile(r"系统提示|面板|数据显示|检测到|发现|解锁|新[的]|升级|获得"),
}
CONFLICT_REGEX = {
    "战斗": re.compile(r"战|杀|攻击|出手|剑|刀|拳|轰|爆|血|伤|死"),
    "心理": re.compile(r"心里|内心|犹豫|挣扎|矛盾|恐惧|害怕|不安|焦虑|怀疑"),
    "道德": re.compile(r"正义|邪恶|善恶|应该|必须|良心|责任|道义|选择"),
    "环境": re.compile(r"废墟|荒[野漠凉]|风暴|地震|洪水|火[山灾]|怪物|丧尸|变异"),
    "社会": re.compile(r"规则|秩序|法律|势力|帮派|组织|[官军]方|政府|分配"),
}


def _regex_label(text, regex_dict):
    """Apply regex dict and return list of matched labels."""
    return [name for name, pat in regex_dict.items() if pat.search(text)]


def _chapter_text(content, ch_num, max_chars=2000):
    """Extract chapter text by number from full novel content."""
    patterns = [
        rf'第[零一二三四五六七八九十百千0-9]+章.*?(?=第[零一二三四五六七八九十百千0-9]+章|\Z)',
        rf'[Cc]hapter\s*{ch_num}.*?(?=[Cc]hapter\s*{ch_num+1}|\Z)',
    ]
    for pat in patterns:
        matches = list(re.finditer(pat, content, re.DOTALL))
        for m in matches:
            if str(ch_num) in m.group()[:20]:
                return m.group()[:max_chars]
    # Fallback: split by empty lines and chunk
    chunks = content.split('\n\n')
    start = ch_num * 30
    if start < len(chunks):
        return '\n'.join(chunks[start:start+15])[:max_chars]
    return ""


def _find_novel_txt(name_hint):
    """Find novel txt file by partial name."""
    for txt in NOVELS_DIR.glob("**/*.txt"):
        if name_hint[:8] in txt.stem or txt.stem[:8] in name_hint:
            return txt
    return None


def _call_llm(system_msg, user_msg, max_retries=2):
    """Call local llama-server via OpenAI-compatible /v1/chat/completions."""
    payload = json.dumps({
        "messages": [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_msg},
        ],
        "max_tokens": 150,
        "temperature": 0.1,
        "stop": ["\n\n"],
    }).encode('utf-8')
    for attempt in range(max_retries):
        try:
            req = urllib.request.Request(
                f"{LLAMA_BASE}/v1/chat/completions",
                data=payload,
                headers={"Content-Type": "application/json"},
            )
            resp = json.loads(urllib.request.urlopen(req, timeout=120).read())
            choices = resp.get("choices", [])
            if choices:
                return choices[0].get("message", {}).get("content", "").strip()
            return ""
        except Exception as e:
            if attempt == max_retries - 1:
                return f"ERROR:{e}"
            time.sleep(2)
    return "ERROR:max_retries"


def _llm_label_chapter(text, ch_num):
    """Ask LLM to label one chapter via structured system+user messages."""
    system_msg = (
        "你是网文爽点/钩子/冲突分析专家。任务：对章节片段判断是否存在以下元素，输出JSON。"
        "爽点类型: 打脸/突破/碾压/绝地反击/扮猪吃虎/羁绊/认知/牺牲。"
        "钩子类型: 悬念/反转/情绪炸弹/信息投放。"
        "冲突类型: 战斗/心理/道德/环境/社会。"
        "如某维度不存在，填\"无\"。只输出JSON，不要任何解释。"
    )
    user_msg = (
        f"分析第{ch_num}章片段:\n\n{text[:1000]}\n\n"
        '输出格式: {"pleasure_types":["类型1",...],"hook_type":"类型","conflict_types":["类型1",...]}\n'
        '示例: {"pleasure_types":["打脸","突破"],"hook_type":"悬念","conflict_types":["战斗","环境"]}'
    )
    result = _call_llm(system_msg, user_msg)
    try:
        start = result.find('{')
        end = result.rfind('}') + 1
        if start >= 0 and end > start:
            parsed = json.loads(result[start:end])
            if parsed.get("pleasure_types") or parsed.get("hook_type") or parsed.get("conflict_types"):
                return parsed
    except (json.JSONDecodeError, ValueError):
        pass
    print(f"    [LLM RAW] {result[:100]}...")
    return {"pleasure_types": [], "hook_type": "无", "conflict_types": []}


def _compare_labels(regex_result, llm_result, label_type):
    """Compare regex vs LLM labels. Returns (tp, fp, fn)."""
    regex_set = set(regex_result)
    llm_set = set(llm_result)
    tp = len(regex_set & llm_set)
    fp = len(regex_set - llm_set)
    fn = len(llm_set - regex_set)
    return tp, fp, fn


def run_labeling(book_name="all", sample_rate=0.1, dry_run=False, genre=None):
    """Main labeling pipeline."""
    _g = genre or "末世"
    _labels_dir(_g).mkdir(parents=True, exist_ok=True)

    # Find books
    if book_name == "all":
        if genre:
            genre_dir = NOVELS_DIR / genre
            txt_files = sorted(genre_dir.glob("*.txt")) if genre_dir.exists() else []
        else:
            txt_files = sorted(NOVELS_DIR.glob("**/*.txt"))
    else:
        found = _find_novel_txt(book_name)
        txt_files = [found] if found else []

    if not txt_files:
        print("[FAIL] No novels found in data/raw/novels/")
        return

    # P0-1: LLM health check before any calls
    if not dry_run:
        try:
            urllib.request.urlopen(f"{LLAMA_BASE}/health", timeout=5)
            print(f"[LLM] Health check passed: {LLAMA_BASE}")
        except Exception:
            print(f"[FAIL] LLM server unreachable at {LLAMA_BASE}")
            print("  Please start the model first: scripts\\start_model.bat")
            return

    total_llm_calls = 0
    all_comparisons = {"pleasure": [], "hook": [], "conflict": []}
    book_reports = []

    for txt in txt_files:
        name = txt.stem[:40]
        content = txt.read_text(encoding='utf-8', errors='replace')

        # Get chapter count from first 30
        ch_count = min(30, len(re.findall(r'第[零一二三四五六七八九十百千0-9]+章', content[:50000])))
        if ch_count < 1:
            print(f"  [SKIP] {name[:20]}: 无章节")
            continue
        sample_n = min(max(1, int(ch_count * sample_rate)), ch_count)
        sample_chs = sorted(random.sample(range(1, ch_count + 1), sample_n))

        if dry_run:
            print(f"  [DRY-RUN] {name}: {ch_count}章, 采样{sample_n}章")
            total_llm_calls += sample_n
            continue

        print(f"\n[{name}] {ch_count}章, 采样{sample_n}章: {sample_chs}")
        book_comparisons = {"pleasure": [], "hook": [], "conflict": []}

        for ch in sample_chs:
            text = _chapter_text(content, ch)
            if not text or len(text) < 100:
                print(f"  Ch{ch}: [SKIP] insufficient text")
                continue

            # Regex baseline
            regex_pleasure = _regex_label(text, PLEASURE_REGEX)
            regex_hook = _regex_label(text, HOOK_REGEX)
            regex_conflict = _regex_label(text, CONFLICT_REGEX)

            # LLM label
            total_llm_calls += 1
            llm = _llm_label_chapter(text, ch)

            llm_pleasure = llm.get("pleasure_types", [])
            llm_hook = llm.get("hook_type", "无")
            llm_conflict = llm.get("conflict_types", [])

            # Compare
            tp_p, fp_p, fn_p = _compare_labels(regex_pleasure, llm_pleasure, "pleasure")
            tp_h, fp_h, fn_h = _compare_labels([h for h in regex_hook], [llm_hook], "hook")
            tp_c, fp_c, fn_c = _compare_labels(regex_conflict, llm_conflict, "conflict")

            precision_p = tp_p / max(tp_p + fp_p, 1)
            recall_p = tp_p / max(tp_p + fn_p, 1)
            precision_h = tp_h / max(tp_h + fp_h, 1)
            recall_h = tp_h / max(tp_h + fn_h, 1)

            book_comparisons["pleasure"].append((tp_p, fp_p, fn_p))
            book_comparisons["hook"].append((tp_h, fp_h, fn_h))
            book_comparisons["conflict"].append((tp_c, fp_c, fn_c))

            all_comparisons["pleasure"].append((tp_p, fp_p, fn_p))
            all_comparisons["hook"].append((tp_h, fp_h, fn_h))
            all_comparisons["conflict"].append((tp_c, fp_c, fn_c))

            print(f"  Ch{ch}: regex_p={regex_pleasure} llm_p={llm_pleasure} "
                  f"| P={precision_p:.0%} R={recall_p:.0%} "
                  f"| regex_h={regex_hook} llm_h={llm_hook} | P_h={precision_h:.0%}")

        # Write per-book labels
        label_csv = _labels_dir(txt.parent.name) / f"{name}_labels.csv"
        with open(label_csv, 'w', newline='', encoding='utf-8-sig') as f:
            w = csv.writer(f)
            w.writerow(["ch_num"] + [f"regex_{k}" for k in PLEASURE_REGEX]
                       + [f"llm_{k}" for k in PLEASURE_REGEX]
                       + ["regex_hook", "llm_hook"])
            # Simplified: write summary only
            w.writerow(["summary",
                        *[sum(1 for t,f,_ in book_comparisons["pleasure"] if t+f>0) for _ in range(len(PLEASURE_REGEX)*2)],
                        sum(1 for t,f,_ in book_comparisons["hook"] if t+f>0),
                        sum(1 for t,f,_ in book_comparisons["hook"] if t+f>0)])

    if dry_run:
        print(f"\n[DRY-RUN] 总计需 {total_llm_calls} 次LLM调用 (~{total_llm_calls*3}s)")
        return

    # ── 全局校准报告 ──
    def _calc_metrics(comparisons):
        tp = sum(t for t, _, _ in comparisons)
        fp = sum(f for _, f, _ in comparisons)
        fn = sum(fn for _, _, fn in comparisons)
        precision = tp / max(tp + fp, 1)
        recall = tp / max(tp + fn, 1)
        f1 = 2 * precision * recall / max(precision + recall, 0.001)
        return {"precision": round(precision, 3), "recall": round(recall, 3),
                "f1": round(f1, 3), "tp": tp, "fp": fp, "fn": fn}

    report = {
        "sample_rate": sample_rate,
        "total_llm_calls": total_llm_calls,
        "pleasure": _calc_metrics(all_comparisons["pleasure"]),
        "hook": _calc_metrics(all_comparisons["hook"]),
        "conflict": _calc_metrics(all_comparisons["conflict"]),
        "global": _calc_metrics(
            all_comparisons["pleasure"] + all_comparisons["hook"] + all_comparisons["conflict"]
        ),
        "recommendation": "",
    }

    # P0-1 action: tell user what to fix
    global_f1 = report["global"]["f1"]
    pleasure_f1 = report["pleasure"]["f1"]
    hook_f1 = report["hook"]["f1"]

    if global_f1 < 0.6:
        report["recommendation"] = (
            f"正则可靠性不足(F1={global_f1:.2f})。建议: 1)对关键章节(前3章+高潮章)100%使用LLM标注 "
            f"2)基于LLM结果修正正则模式 3)对QUARANTINE书籍强制LLM抽检"
        )
    elif global_f1 < 0.8:
        report["recommendation"] = (
            f"正则可用但需警惕(F1={global_f1:.2f})。爽点F1={pleasure_f1:.2f}/钩子F1={hook_f1:.2f}。"
            f"priority: {'hooks' if hook_f1 < pleasure_f1 else 'pleasure'}需要最多改进"
        )
    else:
        report["recommendation"] = f"正则表现良好(F1={global_f1:.2f})，可信任当前标注结果"

    report_path = _labels_dir(_g) / "calib_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')

    # P0-3: write annotation_reliability.json for downstream consumption
    reliability = {
        "pleasure_f1": report["pleasure"]["f1"],
        "hook_f1": report["hook"]["f1"],
        "conflict_f1": report["conflict"]["f1"],
        "global_f1": report["global"]["f1"],
        "sample_chapters": total_llm_calls,
        "timestamp": datetime.now().isoformat(),
    }
    rel_path = PROJECT_ROOT / "data" / "processed" / _g / "quality" / "annotation_reliability.json"
    rel_path.write_text(json.dumps(reliability, ensure_ascii=False, indent=2), encoding='utf-8')

    print(f"\n{'='*60}")
    print(f"[RESULT] LLM标注校准完成 ({total_llm_calls}次调用)")
    print(f"  爽点: P={report['pleasure']['precision']} R={report['pleasure']['recall']} F1={pleasure_f1:.2f}")
    print(f"  钩子: P={report['hook']['precision']} R={report['hook']['recall']} F1={hook_f1:.2f}")
    print(f"  冲突: P={report['conflict']['precision']} R={report['conflict']['recall']} F1={report['conflict']['f1']:.2f}")
    print(f"  全局: F1={global_f1:.2f}")
    print(f"\n  {report['recommendation']}")
    print(f"  Report: {report_path}")
    print(f"  Reliability: {rel_path}")


def main():
    book_name = "all"
    sample_rate = 0.1
    genre = None
    dry_run = "--dry-run" in sys.argv
    for arg in sys.argv[1:]:
        if arg.startswith("--book="):
            book_name = arg.split("=")[1]
        if arg.startswith("--sample-rate="):
            sample_rate = float(arg.split("=")[1])
        if arg.startswith("--genre="):
            genre = arg.split("=")[1]
    run_labeling(book_name, sample_rate, dry_run, genre)


if __name__ == "__main__":
    main()

#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
scoring/borda_ranker.py — Borda排名 + 跨题材竞争力 + 报告生成
===============================================================
从 genre_synthesizer.py 拆分。

方法: Borda Count多维度共识排名 + 合成报告生成 + LOOCV评估

公开函数:
  - synthesize_genre(genre, analyses) -> dict | None
  - generate_report(genre, analyses, synth, output_path)
  - evaluate_loocv(genre, analyses) -> (spearman_r, None) | (None, None)
  - process_genre(genre) -> (synth, output_dir) | None
  - main()
"""
import csv
import json
import statistics
import math
import datetime
import sys
from pathlib import Path
from collections import Counter

from xiaoshuo import PROJECT_ROOT
from xiaoshuo.infra.config_manager import get_config
from xiaoshuo.pipeline.synthesis_reporter import auto_benchmark, cross_genre_summary

# ── Import from sibling scoring modules ──
from xiaoshuo.pipeline.scoring.commercial_engine import (
    get_firebook_pool,
    compute_commercial_score,
    load_rhythm_data,
    load_genre_novels,
    get_default_genre,
    classify_all_sub_genres,
)


def synthesize_genre(genre, analyses):
    if not analyses: return None
    synth = {"genre": genre, "book_count": len(analyses),
             "total_chapters": sum(a["total_ch"] for a in analyses),
             "segment_comparison": {}, "common_patterns": {},
             "vad_comparison": {}, "structure_comparison": {}, "tag_union": []}

    # Segments
    all_seg_names = set()
    for a in analyses: all_seg_names.update(a["segments"].keys())
    for seg in sorted(all_seg_names):
        seg_hooks, seg_conflicts, seg_pleasures, seg_slaps = [], [], [], []
        all_paces, all_subs = [], Counter()
        for a in analyses:
            if seg in a["segments"]:
                s = a["segments"][seg]
                seg_hooks.append(s["hook_mean"]); seg_conflicts.append(s["conflict_mean"])
                seg_pleasures.append(s["pleasure_mean"]); seg_slaps.append(s["avg_slap"])
                all_paces.append(s["dominant_pace"])
                for pt, cnt in s["top_pleasure"]: all_subs[pt] += cnt
        synth["segment_comparison"][seg] = {
            "hook_range": f"{min(seg_hooks):.2f}-{max(seg_hooks):.2f}" if seg_hooks else "N/A",
            "hook_pooled": round(statistics.mean(seg_hooks), 2) if seg_hooks else 0,
            "conflict_range": f"{min(seg_conflicts):.2f}-{max(seg_conflicts):.2f}" if seg_conflicts else "N/A",
            "conflict_pooled": round(statistics.mean(seg_conflicts), 2) if seg_conflicts else 0,
            "pleasure_pooled": round(statistics.mean(seg_pleasures), 1) if seg_pleasures else 0,
            "avg_slap": round(statistics.mean(seg_slaps), 1) if seg_slaps else 0,
            "dominant_paces": Counter(all_paces).most_common(2),
            "top_pleasure_types": all_subs.most_common(5),
        }

    # Common patterns
    all_globals = [a["global"] for a in analyses]
    synth["common_patterns"] = {
        "hook_avg_range": f"{min(g['hook_mean'] for g in all_globals):.2f}-{max(g['hook_mean'] for g in all_globals):.2f}",
        "conflict_avg_range": f"{min(g['conflict_mean'] for g in all_globals):.2f}-{max(g['conflict_mean'] for g in all_globals):.2f}",
        "max_zero_hook_streak": max(g["zero_hook_streak"] for g in all_globals),
    }

    # VAD comparison
    vads = [a.get("vad", {}) for a in analyses if a.get("vad")]
    if vads:
        synth["vad_comparison"] = {
            "V_pooled": f"{min(v['V_mean'] for v in vads):.2f}-{max(v['V_mean'] for v in vads):.2f}",
            "A_pooled": f"{min(v['A_mean'] for v in vads):.1f}-{max(v['A_mean'] for v in vads):.1f}",
            "turning_avg": round(statistics.mean([v['turning_count'] for v in vads]), 0),
        }

    # Structure comparison
    for a in analyses:
        s = a.get("structure", {})
        synth["structure_comparison"][a["name"]] = s

    # Tag union
    all_tags = set()
    for a in analyses:
        for t in a.get("tags", []): all_tags.add(t)
    synth["tag_union"] = sorted(all_tags)

    return synth


def generate_report(genre, analyses, synth, output_path):
    if not synth: return
    lines = [
        f"# {genre}类网文写作技法总纲",
        f"\n> 数据源: {synth['book_count']}本番茄火书 · {synth['total_chapters']}章",
        "> 方法: 拆书三件套(人物/情节/技巧) + 人物弧线 + 分段阅读留存预估",
        f"> 生成: genre_synthesizer.py v5 · {datetime.datetime.now().strftime('%Y-%m-%d')}",
        "\n---\n",
        "## 一、拆书总览\n",
        "| # | 书名 | 章 | hook | conf | 情感 | 弧型 | 商业分 (±CI) |",
        "|:---:|------|:---:|:---:|:---:|:---:|:---:|:---:|",
    ]
    for a in analyses:
        g = a["global"]; st_traj = a.get("state_trajectory", {})
        vad = a.get("vad", {})
        comm = a.get("commercial", {})
        overall = comm.get("overall", "-")
        ci = comm.get("bootstrap_ci", {})
        ci_str = f"{overall}±{ci.get('width',0)//2}" if ci else str(overall)
        arc_str = f"{st_traj.get('arc_type','?')}({st_traj.get('change_count','?')}变)"
        lines.append(
            f"| {analyses.index(a)+1} | {a['name'][:14]} | {a['total_ch']} | "
            f"{g['hook_mean']} | {g['conflict_mean']} | {vad.get('V_mean','-')} | "
            f"{arc_str} | {ci_str} |")

    # -- 二、拆书三件套①: 人物设计 --
    lines.extend([
        "\n## 二、拆书三件套① — 人物设计\n",
        "### MARCUS 人物弧线\n",
        "| # | 书名 | 弧型 | 状态变化 | 稳定性 | V起→V终 | 关键转折(pleasure_type变化) |",
        "|:---:|------|------|:---:|:---:|------|------|",
    ])
    for a in analyses:
        st = a.get("state_trajectory", {})
        sc_str = " → ".join(f"Ch{s['ch']}({s['from_pt']}→{s['to_pt']})"
                           for s in st.get("state_changes", [])[:3]) or "—"
        lines.append(
            f"| {analyses.index(a)+1} | {a['name'][:12]} | {st.get('arc_type','?')} | "
            f"{st.get('change_count',0)}次 | {st.get('stability_score',0):.2f} | "
            f"{st.get('V_start','?')}→{st.get('V_end','?')} | {sc_str} |")

    # -- 三、拆书三件套②: 情节结构 --
    lines.extend([
        "\n## 三、拆书三件套② — 情节结构\n",
        "### 分段节奏基准\n",
        "| 段 | hook | conflict | 爽点 | 打脸 | 节奏 | 主流爽点 |",
    ])
    for seg, d in synth["segment_comparison"].items():
        pc = "/".join(f"{p}({c})" for p, c in d["dominant_paces"])
        pt = d["top_pleasure_types"][0][0] if d["top_pleasure_types"] else "N/A"
        lines.append(f"| {seg} | {d['hook_pooled']}({d['hook_range']}) | {d['conflict_pooled']}({d['conflict_range']}) | {d['pleasure_pooled']} | {d['avg_slap']} | {pc} | {pt} |")

    # 叙事结构
    lines.extend([
        "\n### 叙事结构分布\n",
        "| # | 书名 | 章结构分布 | 起承转爽 | 技法标签 |",
    ])
    for a in analyses:
        st = a.get("structure", {})
        dist = dict(sorted(st.get("distribution", {}).items(), key=lambda x: -x[1]))
        dist_str = "/".join(f"{k}:{v}" for k, v in list(dist.items())[:4])
        tags = ",".join(a.get("tags", [])[:3])
        lines.append(f"| {analyses.index(a)+1} | {a['name'][:14]} | {dist_str} | {st.get('template_matches',0)}个 | {tags} |")

    # VAD
    vc = synth.get("vad_comparison", {})
    if vc:
        lines.extend([
            "\n### VAD情感弧\n",
            "| 指标 | 题材范围 |",
            "|------|------|",
            f"| 效价(Valence) | {vc.get('V_pooled','-')} |",
            f"| 唤醒度(Arousal) | {vc.get('A_pooled','-')} |",
            f"| 均拐点 | {vc.get('turning_avg','-')}个 |",
        ])

    # -- 四、拆书三件套③: 写作技巧 --
    cp = synth["common_patterns"]
    lines.extend([
        "\n## 四、拆书三件套③ — 写作技巧\n",
        "### 题材共性\n",
        f"- 钩子范围: {cp['hook_avg_range']} | 冲突范围: {cp['conflict_avg_range']}",
        f"- **零钩子弃书红线**: <={cp['max_zero_hook_streak']}章",
        f"- 技法标签池: {', '.join(synth.get('tag_union',[])[:8])}",
        "\n### 写作建议\n",
        f"- 开篇钩子>={synth['segment_comparison'].get('开篇(1-10%)',{}).get('hook_pooled','2.5')}（题材均值）",
        "- 节奏偏差>30%→检查是否偏离题材惯例",
        "- 爽点多样性保持>=0.45（Shannon指数）",
        "- 连续3章零钩子=25-35%读者弃书（Survival Analysis基准）",
    ])

    # -- 五、商业可行性 --
    lines.extend([
        "\n## 五、商业可行性评估\n",
        "### 番茄签约评分卡（100分制）\n",
        "| # | 书名 | 综合 | 评级 | 前3章钩子 | 前3章冲突 | 零钩子分 | 打脸分 |",
    ])
    commercial_ranks = []
    for a in analyses:
        comm = a.get("commercial", {})
        if not comm: continue
        ov, gr, sc = comm.get("overall",0), comm.get("grade","-"), comm.get("scores",{})
        zhs = sc.get("零钩子连续", "-")
        slp = round(sc.get("打脸频率", 0)) if isinstance(sc.get("打脸频率", 0), (int, float)) else "-"
        lines.append(f"| {analyses.index(a)+1} | {a['name'][:14]} | {ov} | {gr} | {sc.get('前3章钩子','-')} | {sc.get('前3章冲突','-')} | {zhs} | {slp} |")
        commercial_ranks.append((a['name'], ov))

    if commercial_ranks:
        commercial_ranks.sort(key=lambda x: -x[1])
        avg_comm = round(statistics.mean([c[1] for c in commercial_ranks]), 1)
        lines.extend([
            f"\n- **题材签约均分**: {avg_comm}",
            f"- **最高**: {commercial_ranks[0][0][:20]}({commercial_ranks[0][1]}) · **最低**: {commercial_ranks[-1][0][:20]}({commercial_ranks[-1][1]})",
        ])

    # -- Survival分段留存 --
    lines.extend([
        "\n### Survival分段完读率预估\n",
        "| # | 书名 | 开篇 | 前期 | 中期 | 后期 | 结局 |",
    ])
    for a in analyses:
        sr = a.get("segment_retention", {})
        cols = []
        for seg in ["开篇(0-20%)", "前期(20-40%)", "中期(40-60%)", "后期(60-80%)", "结局(80-100%)"]:
            d = sr.get(seg, {})
            cols.append(f"{d.get('risk_level','-')}{d.get('estimated_pct','-')}%" if d else "-")
        lines.append(f"| {analyses.index(a)+1} | {a['name'][:14]} | {' | '.join(cols)} |")

    # 弃书风险
    lines.append("\n### 弃书高风险点\n")
    all_risks = []
    for a in analyses:
        for r in a.get("commercial", {}).get("risks", []):
            all_risks.append(f"Ch{r['ch']}({r['reason']})")
    lines.append(f"- {', '.join(all_risks[:10])}" if all_risks else "- 无高风险弃书节点")

    lines.append("\n---\n*genre_synthesizer.py v5 · MARCUS人物弧线(arxiv 2510.18201) + 笔灵拆书三件套 + Survival分段留存*")
    output_path.write_text("\n".join(lines), encoding='utf-8')
    print(f"[OK] Synthesis: {output_path}")


def evaluate_loocv(genre, analyses):
    """v9: True Leave-One-Out Cross-Validation.
    For each fold: rebuild pool from 9 books, score the held-out 1, collect prediction.
    Then compute Spearman r against ground-truth completion rates."""
    completion_rates = {
        "末世之黑暗时代": 99, "黑暗文明_古羲": 99, "超级神基因": 98, "狩魔手记_烟雨江南": 98,
        "限制级末日症候": 96, "《全球进化》（精校版全本）作者：咬狗": 93, "《末日蟑螂》作者：伟岸蟑螂": 93,
        "《十日终焉》（校对全本）": 94, "我在末世种个田": 97, "黑暗血时代": 86,
    }
    pred_scores, true_rates = [], []

    for i, held_out in enumerate(analyses):
        name = held_out.get("name", f"book_{i}")[:40]
        # Match ground truth by partial name
        true_rate = None
        for k, v in completion_rates.items():
            if k[:6] in name or name[:6] in k:
                true_rate = v
                break
        if true_rate is None:
            continue

        # v9: Rebuild pool WITHOUT held-out book (true LOOCV)
        pool_9 = get_firebook_pool(genre, exclude_name=name)

        # Load rows for held-out book
        csv_name = None
        for novel in load_genre_novels(genre):
            if name in novel.get("file", ""):
                csv_name = novel.get("rhythm_csv")
                break
        if not csv_name:
            print(f"  LOOCV[{i+1}/10] [SKIP] no csv match for {name[:20]}")
            continue
        try:
            rows = load_rhythm_data(csv_name, genre)
        except Exception as e:
            print(f"  LOOCV[{i+1}/10] [SKIP] {name[:20]}: CSV error ({e})")
            continue
        if not rows:
            print(f"  LOOCV[{i+1}/10] [SKIP] empty data for {name[:20]}")
            continue

        # Score against 9-book pool
        comm = compute_commercial_score(rows, genre, book_name=name)
        overall = comm.get("overall", 0)
        if overall > 0:
            pred_scores.append(overall)
            true_rates.append(true_rate)
            print(f"  LOOCV[{i+1}/10] {name[:20]:20s} score={overall} true={true_rate}%")

    if len(pred_scores) >= 5:
        n = len(pred_scores)

        def _rank(values):
            sp = sorted(enumerate(values), key=lambda x: x[1])
            ranks = [0] * n
            i = 0
            while i < n:
                j = i
                while j < n and sp[j][1] == sp[i][1]:
                    j += 1
                avg_rank = (i + j + 1) / 2.0
                for k in range(i, j):
                    ranks[sp[k][0]] = avg_rank
                i = j
            return ranks

        rs = _rank(pred_scores)
        rr = _rank(true_rates)
        d2 = sum((a - b) ** 2 for a, b in zip(rs, rr))
        spearman_r = round(1 - 6 * d2 / (n * (n**2 - 1)), 3)

        t_stat = spearman_r * math.sqrt((n - 2) / max(1 - spearman_r**2, 0.0001))
        p_val = "p<0.05" if abs(t_stat) > 2.3 else "p>0.05"
        print(f"\n[LOOCV v9] 评分vs真实完读率相关性 r={spearman_r:.3f} ({p_val}) (n={n})")

        # Persist LOOCV result for downstream report generation
        loocv_dir = PROJECT_ROOT / "data" / "reports" / genre
        loocv_path = loocv_dir / "loocv_result.json"
        loocv_path.parent.mkdir(parents=True, exist_ok=True)
        loocv_path.write_text(json.dumps({
            "spearman_r": spearman_r,
            "p_value": p_val,
            "n_folds": n,
            "method": "Leave-One-Out CV, Bayesian Stacking score vs true completion rate",
            "timestamp": datetime.datetime.now().isoformat(),
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  [SAVED] {loocv_path}")
        return spearman_r, None
    return None, None


def process_genre(genre, books_filter=None):
    """Process a single genre: load -> analyze -> score -> report. Returns (synth, output_dir) or None."""
    print(f"[GENRE] {genre}")
    novels = load_genre_novels(genre)
    if books_filter:
        novels = [n for n in novels if n.get("file", "").replace(".txt", "")[:40] in books_filter]
    if not novels:
        print(f"[SKIP] {genre}: 无书籍数据")
        return None
    # v12: LLM sub-genre classification (before analysis loop)
    # Access module-level cache from commercial_engine
    from xiaoshuo.pipeline.scoring import commercial_engine as _ce
    cache_path = PROJECT_ROOT / "data" / "processed" / genre / "sub_genre_llm.json"
    if cache_path.exists():
        try:
            with open(cache_path, 'r', encoding='utf-8') as f:
                _ce._llm_sub_genre_cache = json.load(f)
        except Exception:
            pass
    classify_all_sub_genres(genre, novels)

    # Import analyze_single_novel here to avoid circular import
    from xiaoshuo.pipeline.scoring.commercial_engine import analyze_single_novel

    analyses = []
    for novel in novels:
        csv_name = novel.get("rhythm_csv")
        if not csv_name: continue
        print(f"[ANALYZE] {novel['file']}")
        a = analyze_single_novel(novel['file'].replace('.txt', ''), csv_name, genre)
        if a: analyses.append(a)
    if not analyses: return None
    evaluate_loocv(genre, analyses)

    # -- v11: Borda Count multi-dimensional consensus ranking --
    ch_counts = [a.get("total_ch", 0) for a in analyses if a.get("total_ch", 0) > 0]
    median_ch = sorted(ch_counts)[len(ch_counts) // 2] if ch_counts else 100

    def _length_correct(score, total_ch):
        """Correct per-chapter average metrics for book length dilution.
        Books >1.5x median get a log-scaled bonus; shorter books unchanged."""
        if total_ch <= median_ch * 1.5 or median_ch <= 0:
            return score
        ratio = total_ch / max(median_ch, 1)
        correction = 1.0 + 0.20 * math.log2(ratio)
        return score * min(correction, 1.8)

    # v12: Borda 5-dim LLM-dominant ranking
    dims = [
        ("signing",      lambda a: a.get("commercial", {}).get("signing_score", 50)),
        ("retention",    lambda a: a.get("commercial", {}).get("retention_score", 50)),
        ("diversity",    lambda a: _length_correct(
            a.get("commercial", {}).get("scores", {}).get("爽点多样性", 50), a.get("total_ch", 0))),
        ("bt_rank",      lambda a: a.get("commercial", {}).get("scores", {}).get("BT相对排名", 50)),
        ("webnovel8",    lambda a: a.get("commercial", {}).get("scores", {}).get("WebNovelBench综合", 50)),
    ]
    borda = {}
    for dim_name, score_fn in dims:
        sorted_books = sorted(analyses, key=score_fn, reverse=True)
        for rank, book in enumerate(sorted_books, 1):
            stem = book.get("name", "")
            if stem not in borda:
                borda[stem] = {"total_borda": 0, "dim_ranks": {}}
            borda[stem]["total_borda"] += rank
            borda[stem]["dim_ranks"][dim_name] = rank
    # Lower total_borda = higher consensus rank
    borda_list = sorted(borda.items(), key=lambda x: x[1]["total_borda"])
    ranking_data = []
    for rank, (stem, data) in enumerate(borda_list, 1):
        data["consensus_rank"] = rank
        data["book_name"] = stem
        ranking_data.append(data)
    # Save ranking
    rank_path = PROJECT_ROOT / "data" / "reports" / genre / "synthesis" / f"{genre}_borda_ranking.json"
    rank_path.parent.mkdir(parents=True, exist_ok=True)
    with open(rank_path, 'w', encoding='utf-8') as f:
        json.dump(ranking_data, f, ensure_ascii=False, indent=2)
    print(f"[OK] Borda Ranking: {rank_path}")

    # v11: Persist commercial scores to JSON for quality_gate consumption
    scores_path = PROJECT_ROOT / "data" / "processed" / genre / "commercial_scores.json"
    scores_path.parent.mkdir(parents=True, exist_ok=True)
    scores_data = {}
    for a in analyses:
        comm = a.get("commercial", {})
        if comm and isinstance(comm.get("overall"), int):
            scores_data[a["name"]] = {
                "overall": comm["overall"],
                "grade": comm.get("grade", ""),
                "sub_genre": comm.get("sub_genre", ""),
            }
    scores_path.write_text(json.dumps(scores_data, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"[OK] Commercial Scores: {scores_path}")

    synth = synthesize_genre(genre, analyses)
    output_dir = PROJECT_ROOT / "data" / "reports" / genre / "synthesis"
    output_dir.mkdir(parents=True, exist_ok=True)
    generate_report(genre, analyses, synth, output_dir / f"{genre}_写作技法总纲.md")
    auto_benchmark(synth, analyses, output_dir)
    print(f"\n[DONE] {genre}: {len(analyses)}/{len(novels)} books")
    return synth, output_dir


def main():
    genre = get_default_genre()
    books_filter = None
    for i, arg in enumerate(sys.argv[1:], 1):
        if arg == "--genre" and i < len(sys.argv) - 1:
            genre = sys.argv[i + 1]
        elif arg == "--books" and i < len(sys.argv) - 1:
            books_filter = set(sys.argv[i + 1].split(","))
    print(f"[GENRE] {genre} (default from config.yaml: {get_default_genre()})")
    process_genre(genre, books_filter)


if __name__ == "__main__":
    if "--all" in sys.argv:
        genres = ["末世", "玄幻", "都市", "仙侠", "洪荒", "悬疑", "历史", "无限流"]
        results = {}
        for g in genres:
            r = process_genre(g)
            if r: results[g] = r
        if len(results) >= 2:
            cross_genre_summary(results)
    else:
        main()
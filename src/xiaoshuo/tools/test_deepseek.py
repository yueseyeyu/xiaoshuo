"""Test DeepSeek vs Qwen scoring — 5-book batch (~$0.15).
Results saved to data/deepseek_records.jsonl for persistence.
Usage: python scripts/test_deepseek.py
"""
import sys, csv, json, statistics, io, datetime
from pathlib import Path
from xiaoshuo import PROJECT_ROOT
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
from collections import Counter

from xiaoshuo.pipeline.scoring.commercial_engine import (
    compute_commercial_score, _load_deepseek_config
)

# Check config
ds_config = _load_deepseek_config()
if not ds_config:
    print("[SKIP] DeepSeek not enabled or secrets.yaml missing.")
    print("1. Set config.yaml: external_api.deepseek.enabled = true")
    print("2. Set secrets.yaml: deepseek.api_key = your-key")
    sys.exit(0)

print(f"[OK] DeepSeek: model={ds_config['model']}")

# Output file + skip already-run books
OUTPUT = Path("d:/Code/xiaoshuo/data/deepseek_records.jsonl")
already_done = set()
if OUTPUT.exists():
    for line in open(OUTPUT, encoding="utf-8"):
        try:
            rec = json.loads(line)
            today = datetime.date.today().isoformat()
            if rec.get("timestamp", "").startswith(today):
                already_done.add(rec["book"])
        except (json.JSONDecodeError, KeyError): pass
if already_done:
    print(f"[SKIP] {len(already_done)} books already scored today: {already_done}")

# Batch: 5 baseline + 5 extremes for linearity check (~$0.30 total)
tests = [
    # --- Batch 1: baseline (already run, skip if in JSONL) ---
    ("黑暗文明(神作)", "rhythm_黑暗文明_古羲.csv"),
    ("三宫六院(模板)", "rhythm_末世之三宫六院_牧神空.csv"),
    ("精灵皇(路人)", "rhythm_末世精灵皇_and点.csv"),
    ("地球游戏场(精品)", "rhythm_《地球游戏场》（校对版全本）作者：吉风冰.csv"),
    ("神秘尽头(悬疑)", "rhythm_《神秘尽头》-+黑山老鬼.csv"),
    # --- Batch 2: extremes for linearity calibration ---
    ("狩魔手记(最低78)", "rhythm_狩魔手记_烟雨江南.csv"),
    ("第九特区(低85)", "rhythm_《第九特区》.csv"),
    ("灾厄纪元(低85)", "rhythm_《灾厄纪元》（校对版全本）作者：妖的境界.csv"),
    ("末日拼图游戏(高92)", "rhythm_《末日拼图游戏》（校对版全本）作者：更从心.csv"),
    ("黑暗末日(高92)", "rhythm_《黑暗末日》（校对版全本）作者：我妻虚彩.csv"),
]

records = []
print(f"\n{'Book':<25} {'Qwen':>6} {'DS':>6} {'Gap':>6} {'Level':>10} {'Penalties':>15}")
print("-" * 75)

for name, csv_file in tests:
    if name in already_done:
        print(f"{name:<25} {'(skipped)':>20}")
        continue
    rows = []
    csv_path = PROJECT_ROOT / "data" / "processed" / "末世" / "rhythm" / csv_file
    with open(csv_path, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            for k in r:
                try: r[k] = float(r[k])
                except (ValueError, TypeError): pass
            rows.append(r)

    comm = compute_commercial_score(rows, "末世", name)

    # Anti-template diagnostics
    vds = [r.get("vocab_diversity", 0) for r in rows if r.get("vocab_diversity", 0) > 0]
    avg_vd = statistics.mean(vds) if vds else 0
    sub_counter = Counter(r.get("dominant_sub", "none") for r in rows)
    top2 = sum(v for _, v in sub_counter.most_common(2)) / max(sum(sub_counter.values()), 1)
    hooks = [r.get("hook_density", 0) for r in rows[:30] if r.get("hook_density", 0) > 0]
    avg_hook = statistics.mean(hooks) if hooks else 0

    penalties = []
    if avg_vd < 0.18: penalties.append("VD")
    if top2 > 0.55 and avg_hook < 1.5: penalties.append("TOP2+lowHK")

    qwen_score = comm["overall"]
    qwen_signing = comm.get("signing_score", 0)
    qwen_retention = comm.get("retention_score", 0)

    ds = comm.get("ds_score", {})
    ds_score = ds.get("overall", None) if ds else None
    ds_signing = ds.get("signing", None) if ds else None
    ds_retention = ds.get("retention", None) if ds else None

    bias = comm.get("self_eval_bias")
    gap = bias["gap"] if bias else None
    level = bias["level"] if bias else "no DS"

    print(f"{name:<25} {qwen_score:>6} {str(ds_score):>6} {str(gap):>6} {level:>10} {','.join(penalties) or 'none':>15}")

    # Build record for persistence — DS-only, Qwen comparison by book name match
    record = {
        "timestamp": datetime.datetime.now().isoformat(),
        "book": name,
        "model": ds_config.get("model", "deepseek-chat"),
        "chapters_sampled": len(rows),
        "deepseek": {"overall": ds_score, "signing": ds_signing, "retention": ds_retention},
    }
    records.append(record)

# Persist
if records:
    with open(OUTPUT, 'a', encoding='utf-8') as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + '\n')
    print(f"\n[OK] Saved {len(records)} records to {OUTPUT}")

"""Generate Qwen-vs-DeepSeek comparison table. Run after scoring updates.
Output: data/score_comparison.json
Usage: python scripts/score_compare.py
"""
import sys, json, io, datetime
from pathlib import Path
from xiaoshuo import PROJECT_ROOT
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

DATA = PROJECT_ROOT / "data"

# Load DS
ds = {}
for line in (DATA / "deepseek_records.jsonl").read_text("utf-8").strip().split("\n"):
    if line.strip():
        r = json.loads(line)
        ds[r["book"]] = r["deepseek"]

# Load Qwen (rule + LLM)
qw = {}
for line in (DATA / "qwen_scores.jsonl").read_text("utf-8").strip().split("\n"):
    if line.strip():
        r = json.loads(line)
        qw[r["book"]] = r

# Build table
rows = []
for book_name, q in qw.items():
    if book_name not in ds:
        continue
    d = ds[book_name]
    rule_score = q["qwen"].get("overall", 0)
    llm_data = q.get("qwen_llm", {})
    llm_score = llm_data.get("overall", "TBD") if isinstance(llm_data, dict) else "TBD"
    gap_rule_ds = rule_score - d["overall"]
    gap_llm_ds = (llm_score - d["overall"]) if isinstance(llm_score, (int, float)) else None
    rows.append({
        "book": book_name,
        "qwen_rule": rule_score,
        "qwen_llm": llm_score,
        "deepseek": d["overall"],
        "gap_rule_vs_ds": gap_rule_ds,
        "gap_llm_vs_ds": gap_llm_ds,
    })

table = {
    "generated": datetime.datetime.now().isoformat(),
    "updated_by": "scripts/score_compare.py",
    "rows": rows,
}
(DATA / "score_comparison.json").write_text(json.dumps(table, ensure_ascii=False, indent=2), encoding="utf-8")

print(f"{'Book':<22} {'Rule':>6} {'LLM':>6} {'DS':>6} {'R-DS':>5} {'L-DS':>5}")
print("-" * 58)
for r in rows:
    llm = r["qwen_llm"] if isinstance(r["qwen_llm"], (int, float)) else "?"
    lds = r["gap_llm_vs_ds"] if r["gap_llm_vs_ds"] is not None else "?"
    print(f"{r['book']:<22} {r['qwen_rule']:>6} {str(llm):>6} {r['deepseek']:>6} {r['gap_rule_vs_ds']:>5} {str(lds):>5}")

#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""分析截断影响：哪些已标注章节因截断需要重跑。"""
import json, csv, sys
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')

# 加载stage1数据
data = json.load(open("scripts/stage1_10pct_chapters.json", "r", encoding="utf-8"))
ft = [d for d in data if d["book"] == "废土崛起"]

# 统计字数分布
over3000 = [d for d in ft if d["wc"] > 3000]
over2500 = [d for d in ft if d["wc"] > 2500]
under2500 = [d for d in ft if d["wc"] <= 2500]

print(f"=== 废土崛起 stage1 数据字数分布 ===")
print(f"  总章节: {len(ft)}")
print(f"  wc > 3000 (stage1截断丢失): {len(over3000)}")
print(f"  wc > 2500 (print脚本截断): {len(over2500)}")
print(f"  wc <= 2500 (无截断影响): {len(under2500)}")

# 已标注章节
annotated = set()
ai_csv = Path("data/processed/末世/scores/废土崛起_ai.csv")
if ai_csv.exists():
    with open(ai_csv, "r", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            annotated.add(int(r["ch_num"]))
print(f"\n已AI标注: {len(annotated)}章")

# 分析已标注章节的截断情况
ch_map = {d["ch_num"]: d for d in ft}
need_rerun_trunc = []
ok_keep = []
for ch_num in sorted(annotated):
    d = ch_map.get(ch_num)
    if d is None:
        # golden章节不在stage1中
        need_rerun_trunc.append(ch_num)
        continue
    if d["wc"] > 2500:
        need_rerun_trunc.append(ch_num)
    else:
        ok_keep.append(ch_num)

print(f"\n=== 已标注章节截断分析 ===")
print(f"  wc > 2500 需重跑: {len(need_rerun_trunc)}章 — {need_rerun_trunc}")
print(f"  wc <= 2500 可保留: {len(ok_keep)}章 — {ok_keep}")

# 未标注章节
unannotated = [d["ch_num"] for d in ft if d["ch_num"] not in annotated]
print(f"\n=== 未标注章节 ===")
print(f"  总数: {len(unannotated)}章")
print(f"  需要全新提取(全读): {len(unannotated)}章")

# 总结
print(f"\n=== 总结 ===")
print(f"  重跑(已标注+截断): {len(need_rerun_trunc)}章")
print(f"  保留(已标注+无截断): {len(ok_keep)}章")
print(f"  新标注(未标注): {len(unannotated)}章")
print(f"  废土崛起总计: {len(need_rerun_trunc) + len(ok_keep) + len(unannotated)}章")

# 另外两本书
for book in ["末日蟑螂", "末世大回炉"]:
    bk = [d for d in data if d["book"] == book]
    over = [d for d in bk if d["wc"] > 3000]
    print(f"\n{book}: {len(bk)}章, 其中wc>3000被截断: {len(over)}章")

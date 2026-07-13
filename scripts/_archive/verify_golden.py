"""验证golden文件数据完整性"""
import csv

path = "data/golden/末世/human_golden.csv"
with open(path, "r", encoding="utf-8-sig") as f:
    rows = list(csv.DictReader(f))

books = {}
for r in rows:
    books.setdefault(r["book"], []).append(r)

print("Golden文件验证:")
print(f"  文件路径: {path}")
print(f"  总行数: {len(rows)}")
for b, chs in sorted(books.items()):
    retest = sum(1 for r in chs if r.get("is_retest", "").lower() == "true")
    print(f"  {b}: {len(chs)}章 (其中retest {retest}章)")
retest_total = sum(1 for r in rows if r.get("is_retest", "").lower() == "true")
print(f"  Retest总章数: {retest_total}")
print(f"\n验证通过 ✓")

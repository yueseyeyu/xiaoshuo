"""更新novel_index.json: 新增3本S级末世小说"""
import json
import os

path = "data/raw/novel_index.json"
with open(path, "r", encoding="utf-8") as f:
    idx = json.load(f)

# 末世分类
apocalypse = idx["genres"]["末世"]

# 新书信息
new_books = [
    {
        "file": "《第一序列》（校对版全本）作者：会说话的肘子.txt",
        "author": "会说话的肘子",
        "size_kb": 5962,
        "rhythm_csv": ""
    },
    {
        "file": "《长夜余火》（校对版全本）作者：爱潜水的乌贼.txt",
        "author": "爱潜水的乌贼",
        "size_kb": 5983,
        "rhythm_csv": ""
    },
    {
        "file": "末日乐园.txt",
        "author": "须尾俱全",
        "size_kb": 15663,
        "rhythm_csv": ""
    }
]

# 检查是否已存在（避免重复添加）
existing_files = {n["file"] for n in apocalypse["novels"]}
added = 0
for book in new_books:
    if book["file"] not in existing_files:
        apocalypse["novels"].append(book)
        added += 1
        print(f"  + 新增: {book['file']} ({book['author']}, {book['size_kb']}KB)")
    else:
        print(f"  = 已存在: {book['file']}")

# 更新计数
apocalypse["count"] = len(apocalypse["novels"])
idx["total"] = sum(g["count"] for g in idx["genres"].values())

# 更新时间戳
from datetime import datetime
idx["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M")

with open(path, "w", encoding="utf-8") as f:
    json.dump(idx, f, ensure_ascii=False, indent=2)

print(f"\n新增 {added} 本, 末世总数: {apocalypse['count']}, 全库总数: {idx['total']}")

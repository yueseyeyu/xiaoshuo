"""Add new books to novel_index.json. Run from any directory."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INDEX_PATH = ROOT / "data" / "raw" / "novel_index.json"

idx = json.loads(INDEX_PATH.read_text(encoding='utf-8'))
new = [
    {"file":"《世界末日从考试不及格开始》作者：小猫要成仙.txt","author":"小猫要成仙","word_count":"约250万","status":"完本","sub_genre":"末世轻小说","rhythm_csv":"rhythm_《世界末日从考试不及格开始》作者：小猫要成仙.csv"},
    {"file":"《异兽迷城》（校对版全本）.txt","author":"彭湃","word_count":"约300万","status":"完本","sub_genre":"都市末世","rhythm_csv":"rhythm_《异兽迷城》（校对版全本）.csv"},
    {"file":"《我在末世有套房》（校对版全本）作者：晨星LL.txt","author":"晨星LL","word_count":"约400万","status":"完本","sub_genre":"末世种田","rhythm_csv":"rhythm_《我在末世有套房》（校对版全本）作者：晨星LL.csv"},
    {"file":"《末日拼图游戏》（校对版全本）作者：更从心.txt","author":"更从心","word_count":"288万","status":"完本","sub_genre":"高塔末世","rhythm_csv":"rhythm_《末日拼图游戏》（校对版全本）作者：更从心.csv"},
    {"file":"《第九特区》.txt","author":"未知","word_count":"约200万","status":"完本","sub_genre":"末世种田","rhythm_csv":"rhythm_《第九特区》.csv"},
]
idx["genres"]["末世"]["novels"].extend(new)
idx["genres"]["末世"]["count"] = len(idx["genres"]["末世"]["novels"])
idx["total"] = sum(v["count"] for v in idx["genres"].values())
INDEX_PATH.write_text(json.dumps(idx, ensure_ascii=False, indent=2), encoding='utf-8')
print(f"末世:{idx['genres']['末世']['count']}本 total:{idx['total']}")

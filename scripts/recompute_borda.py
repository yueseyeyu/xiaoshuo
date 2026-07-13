"""用新的加权Borda维度权重，从已有dim_ranks重算排名。

不需要重跑完整管线，只重新计算 total_borda = Σ(rank × dim_weight)。
"""
import json
from pathlib import Path
from xiaoshuo import PROJECT_ROOT
from xiaoshuo.infra.config_manager import get_config

GENRE = "末世"
borda_path = PROJECT_ROOT / "data" / "reports" / GENRE / "synthesis" / f"{GENRE}_borda_ranking.json"
data = json.loads(borda_path.read_text(encoding="utf-8"))

cfg = get_config()
dim_cfg = cfg.get("analysis", {}).get("book_filter", {}).get("borda_dimension_weights", {})
weights = {
    "signing":   dim_cfg.get("signing", 1.0),
    "retention": dim_cfg.get("retention", 1.0),
    "diversity": dim_cfg.get("diversity", 1.0),
    "bt_rank":   dim_cfg.get("bt_rank", 1.0),
    "webnovel8": dim_cfg.get("webnovel8", 1.0),
}
print(f"维度权重: {weights}  (总和={sum(weights.values())})")

for entry in data:
    dim_ranks = entry.get("dim_ranks", {})
    old_total = entry["total_borda"]
    new_total = sum(dim_ranks.get(dim, 0) * w for dim, w in weights.items())
    entry["total_borda"] = round(new_total, 2)
    entry["old_total_borda"] = old_total

data.sort(key=lambda x: x["total_borda"])
for i, entry in enumerate(data, 1):
    entry["consensus_rank"] = i
    name = entry["book_name"][:20]
    old_rank = entry.get("old_total_borda", 0)
    print(f"  #{i:2d} {entry['total_borda']:7.2f} (旧{old_rank:3d}) {name}")

out_path = borda_path
out_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"\n[OK] 已保存加权Borda排名到 {out_path}")

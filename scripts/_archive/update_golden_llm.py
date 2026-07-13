#!/usr/bin/env python
# -*- coding: utf-8 -*-
r"""
update_golden_llm.py — 将 Phase B 新 LLM 分数合并到 golden_set.json
====================================================================
读取 e2e_verify_phaseB.json 中的 new_llm_i / new_llm_r，
注入到 golden_set.json 的每条记录中，作为 llm_intensity / llm_retention 字段。

这样 apply_golden_set_calibration() 可以直接从 golden_set.json 读取
最新的 LLM 分数构建分位数映射，避免使用过时的旧 LLM 分数。

用法:
  D:\miniconda3\envs\llm-shared\python.exe scripts/update_golden_llm.py
"""
import json
import sys
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')

PROJECT_ROOT = Path(__file__).parent.parent
GOLDEN_SET = PROJECT_ROOT / "data" / "processed" / "末世" / "scores" / "golden_set.json"
PHASE_B = PROJECT_ROOT / "data" / "reports" / "末世" / "e2e_verify_phaseB.json"


def main():
    # 1. 读取 golden_set.json
    if not GOLDEN_SET.exists():
        print(f"[ERROR] {GOLDEN_SET} 不存在")
        return
    with open(GOLDEN_SET, encoding="utf-8") as f:
        golden = json.load(f)
    print(f"读取 golden_set.json: {len(golden)} 条")

    # 2. 读取 Phase B 结果
    if not PHASE_B.exists():
        print(f"[ERROR] {PHASE_B} 不存在，请先运行 Phase B 验证")
        return
    with open(PHASE_B, encoding="utf-8") as f:
        pb = json.load(f)
    pb_details = pb.get("details", [])
    print(f"读取 Phase B 结果: {len(pb_details)} 条")

    # 3. 构建 (book, ch_num) → new_llm 查找表
    pb_map = {}
    for r in pb_details:
        key = (r["book"], r["ch_num"])
        pb_map[key] = {
            "llm_intensity": r["new_llm_i"],
            "llm_retention": r["new_llm_r"],
        }

    # 4. 合并到 golden_set
    updated = 0
    for g in golden:
        key = (g.get("book"), g.get("ch_num"))
        if key in pb_map:
            g["llm_intensity"] = pb_map[key]["llm_intensity"]
            g["llm_retention"] = pb_map[key]["llm_retention"]
            updated += 1

    print(f"已更新 {updated}/{len(golden)} 条记录的 llm_intensity/llm_retention")

    # 5. 保存
    with open(GOLDEN_SET, "w", encoding="utf-8") as f:
        json.dump(golden, f, ensure_ascii=False, indent=2)
    print(f"[OK] golden_set.json 已更新: {GOLDEN_SET}")

    # 6. 验证：打印前 3 条
    print("\n前 3 条记录预览:")
    for g in golden[:3]:
        print(f"  {g['book']} ch{g['ch_num']}: "
              f"human_i={g['human_intensity']}, llm_i={g.get('llm_intensity', 'N/A')}, "
              f"human_r={g['human_retention']}, llm_r={g.get('llm_retention', 'N/A')}")


if __name__ == "__main__":
    main()

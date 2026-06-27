"""交叉审查全流程验证：Qwen3.5-9B Phase 1 → swap_to DeepSeek-R1 Phase 2 → 切回主模型"""
import sys
sys.path.insert(0, "src")

from xiaoshuo.agents.cross_review import cross_review

TEST_CHAPTER = """第1章 末日降临

李明睁开眼，发现自己躺在一片废墟中。头顶的天空是暗红色的，空气中弥漫着焦糊的味道。

他记得自己昨晚还在加班，怎么一觉醒来世界就变了？

远处传来一声嘶吼，像是某种野兽，又像是人。李明下意识地握紧了拳头，站起身来环顾四周。

街道上到处都是废弃的车辆，有几辆还在燃烧。他注意到不远处的便利店里似乎有动静。

小心翼翼地靠近，李明透过破碎的玻璃窗看到里面有一个身影正在翻找货架。

那人转过头来，露出一张惨白的脸——不，那不是人，那东西的眼睛是纯黑色的，嘴角还挂着暗红色的液体。

丧尸！

李明的心跳瞬间加速。他下意识地后退了一步，踩到了一块碎玻璃。

咔嚓。

那东西听到了声音，猛地转过头来，发出一声凄厉的嚎叫，朝他冲了过来。"""

print("[TEST] 交叉审查全流程验证")
print("[TEST] Phase 1: Qwen3.5-9B 全面审查...")
print(f"[TEST] 测试文本: {len(TEST_CHAPTER)} 字")
print("=" * 60)

try:
    result = cross_review(TEST_CHAPTER, 1)
    print("[OK] Phase 1+2 完成!")
    print(f"  has_additions: {result.get('has_additions', 'N/A')}")
    print(f"  primary length: {len(result.get('primary', ''))} char")
    print(f"  secondary_patches: {len(result.get('secondary_patches', ''))} char")
    print(f"  primary_usage: {result.get('primary_usage', 'N/A')}")
    print(f"  secondary_usage: {result.get('secondary_usage', 'N/A')}")
    print(f"  findings_summary: {result.get('findings_summary', 'N/A')[:200]}")
    print(f"\n--- 合并报告 (前 600 字) ---")
    print(result.get("merged", "")[:600])
    print("---")
    print("[DONE] 全流程通过")
except Exception as e:
    print(f"[FAIL] {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
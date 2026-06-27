"""验证 swap_to() 模型切换 + DeepSeek-R1 推理 + 切回主模型"""
import sys
sys.path.insert(0, "src")

from xiaoshuo.agents.model_orchestrator import get_orchestrator

orch = get_orchestrator()

# Step 1: 切换到 DeepSeek-R1
print("[TEST] swap_to('logic_cop_candidate') ...")
ok = orch.swap_to("logic_cop_candidate", timeout=120)
print(f"[{'OK' if ok else 'FAIL'}] swap result")

if not ok:
    print("[FAIL] 切换失败，退出")
    sys.exit(1)

# Step 2: 用 DeepSeek-R1 推理
print("[TEST] DeepSeek-R1 chat ...")
r = orch.chat("S3_cross_check", [
    {"role": "user", "content": "说一个字：好"}
], max_tokens=20, temperature=0.6, timeout=60)
content = r.get("content", "")
print(f"result: {content[:80]}")

# Step 3: 切回主模型
print("[TEST] swap_to('main_model') ...")
ok2 = orch.swap_to("main_model", timeout=120)
print(f"[{'OK' if ok2 else 'FAIL'}] swap back")

# Step 4: 验证主模型仍可用
print("[TEST] main_model chat after swap back ...")
r2 = orch.chat("S3_logic_cop", [
    {"role": "user", "content": "说一个字：好"}
], max_tokens=10, temperature=0.0, timeout=60)
print(f"result: {r2.get('content', '')[:50]}")

print("[DONE] swap_to 全流程验证完成")
"""
P0-0: 末日生存压力测试
测试场景: 长System Prompt推理 / 未知task降级 / 状态机熔断 / LLM每日上限
"""
import sys, json, urllib.request

sys.path.insert(0, "d:/Code/xiaoshuo/agents")
from skill_loader import SkillLoader
from model_orchestrator import get_orchestrator
from state_machine import Stage, StateMachine

orch = get_orchestrator()
loader = SkillLoader()
ok = fail = 0

print("=" * 60)
print("  P0-0 末日生存压力测试")
print("=" * 60)

# [A] Long System Prompt inference
print("\n[A] Long System Prompt inference ...")
ctx = {"chapter_num": 1, "chapter_word_count": 5000,
       "characters_section": "Main: Ye Fan\nSupporting: " + ", ".join([f"Char{i}" for i in range(20)])}
prompt = loader.build("S3_logic_cop", ctx)
msg = [{"role": "system", "content": prompt}, {"role": "user", "content": "Short: any logic issues?"}]
r = orch.chat("S3_logic_cop", msg, max_tokens=80, temperature=0.3, timeout=60)
if "error" in r:
    print(f"  [FAIL] {r['error']}"); fail += 1
else:
    print(f"  [OK] prompt={len(prompt)}c, tokens={r['usage']}"); ok += 1

# [B] Unknown task fallback
print("\n[B] Unknown task fallback ...")
r2 = orch.chat("unknown_task", [{"role": "user", "content": "hi"}], max_tokens=10, timeout=10)
if "error" not in r2:
    print(f"  [OK] fallback success"); ok += 1
else:
    print(f"  [FAIL]"); fail += 1

# [C] State machine circuit breaker
print("\n[C] Circuit breaker (3rd retry) ...")
sm = StateMachine(load_persisted=False)
for s in [Stage.S0, Stage.S1, Stage.S2a, Stage.S2c, Stage.S2d, Stage.S3]:
    sm.transition(s)
sm.transition(Stage.S2d); sm.transition(Stage.S3)
sm.transition(Stage.S2d); sm.transition(Stage.S3)
if not sm.transition(Stage.S2d):
    print("  [OK] 3rd retry blocked"); ok += 1
else:
    print("  [FAIL]"); fail += 1

# [D] LLM daily limit
print("\n[D] LLM daily limit (51 calls) ...")
sm2 = StateMachine(load_persisted=False)
for _ in range(51):
    sm2.record_llm_call()
if not sm2.can_call_llm(50):
    print("  [OK] 51st call rejected"); ok += 1
else:
    print("  [FAIL]"); fail += 1

print(f"\n[RESULT] {ok}/4 passed, {fail} failed")
print("[DONE]" if fail == 0 else "[NOTE] failures need fix")

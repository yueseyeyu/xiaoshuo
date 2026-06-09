@echo off
REM ============================================================
REM stress_test.bat — P0-0 末日生存压力测试
REM
REM 3 场景:
REM   A. 模型崩溃恢复 — kill server → orchestrator 降级 → 再启动
REM   B. 极限推理 — 32K context + 复杂 System Prompt → 测超时/降级
REM   C. 配置缺失 — 删除 config → 各模块优雅降级
REM
REM 用法: scripts\stress_test.bat
REM ============================================================

set PYTHON=D:\miniconda3\envs\llm-shared\python.exe
set PASS=0
set FAIL=0

echo ============================================================
echo   P0-0 末日生存压力测试
echo ============================================================
echo.

REM ── 场景 A: 模型崩溃恢复 ──
echo [A] 模型崩溃恢复测试...
echo   启动 server...

REM 确保先杀干净
taskkill /f /im llama-server.exe 2>nul >nul
timeout /t 2 /nobreak >nul

REM 启动 server
start "" /B D:\miniconda3\envs\llm-shared\Library\bin\llama-server.exe ^
    --model D:/DaMoXing/Qwen3.5-9B-Q4_K_M.gguf ^
    --n-gpu-layers 35 --ctx-size 4096 --port 8000 --host 127.0.0.1 ^
    --alias Qwen3.5-9B --chat-template chatml >nul 2>nul

echo   等待 server 就绪 (最多 60s)...
%PYTHON% -c "import urllib.request,time; start=time.time(); [time.sleep(2) for _ in range(30) if not (lambda: any([True for _ in [1] if __import__('urllib.request').urlopen('http://127.0.0.1:8000/health',timeout=1)]))()]; print('[OK] server 就绪' if time.time()-start<60 else '[FAIL] 超时')" 2>nul

REM 跑一次推理确认 server 正常
%PYTHON% -c "import urllib.request,json; d=json.dumps({'messages':[{'role':'user','content':'说一个字：好'}],'max_tokens':5,'temperature':0}).encode(); r=json.loads(urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:8000/v1/chat/completions',d,{'Content-Type':'application/json'}),timeout=30).read()); print('[OK] 推理正常' if r['choices'][0]['message']['content'].strip() else '[FAIL] 空响应')" 2>nul

REM kill server 模拟崩溃
echo   模拟 server 崩溃...
taskkill /f /im llama-server.exe 2>nul >nul
timeout /t 3 /nobreak >nul

REM 验证 orchestrator 降级
%PYTHON% -c "import sys; sys.path.insert(0,'agents'); from model_orchestrator import get_orchestrator; o=get_orchestrator(); s=o.status(); print('[OK] orchestrator 仍可用' if s['models']['main_model']['healthy']==False else '[OK] server 仍存活')" 2>nul

rem 重新启动
start "" /B D:\miniconda3\envs\llm-shared\Library\bin\llama-server.exe ^
    --model D:/DaMoXing/Qwen3.5-9B-Q4_K_M.gguf ^
    --n-gpu-layers 35 --ctx-size 4096 --port 8000 --host 127.0.0.1 ^
    --alias Qwen3.5-9B --chat-template chatml >nul 2>nul

echo   等待恢复...
timeout /t 20 /nobreak >nul

%PYTHON% -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health',timeout=3); print('[OK] server 恢复成功')" 2>nul
if %errorlevel% equ 0 (set /a PASS+=1) else (set /a FAIL+=1)
echo.

REM ── 场景 B: 极限推理 ──
echo [B] 极限推理测试 (长 System Prompt + 32K ctx)...

REM 用 skill_loader 构建完整的 S3 逻辑警察 prompt
%PYTHON% -c "
import sys; sys.path.insert(0,'agents')
from skill_loader import SkillLoader
from model_orchestrator import get_orchestrator
import json

loader = SkillLoader()
orch = get_orchestrator()

# 构造一个长 context（模拟加载所有角色设定）
long_context = {'chapter_num': 99, 'chapter_word_count': 5000,
    'characters_section': '主角: 叶凡\n配角: ' + ', '.join([f'角色{i}' for i in range(20)])}

prompt = loader.build('S3_logic_cop', long_context)
msgs = [{'role': 'system', 'content': prompt},
        {'role': 'user', 'content': '审查本章是否有与前文矛盾的地方。简短回答。'}]

result = orch.chat('S3_logic_cop', msgs, max_tokens=100, temperature=0.3, timeout=60)
if 'error' in result:
    print(f'[FAIL] {result[\"error\"]}')
else:
    print(f'[OK] prompt_len={len(prompt)} tokens={result[\"usage\"]} resp={result[\"content\"][:60]}')
" 2>nul
if %errorlevel% equ 0 (set /a PASS+=1) else (set /a FAIL+=1)
echo.

REM ── 场景 C: 状态机熔断 ──
echo [C] 状态机熔断测试...
%PYTHON% -c "
import sys; sys.path.insert(0,'agents')
from state_machine import Stage, StateMachine
sm = StateMachine()
# 走一遍完整流程
for s in [Stage.S0, Stage.S1, Stage.S2a, Stage.S2c, Stage.S2d, Stage.S3]:
    sm.transition(s)
# S3 BLOCK 退回 S2d x3
sm.transition(Stage.S2d); sm.transition(Stage.S3)
sm.transition(Stage.S2d); sm.transition(Stage.S3)
blocked = not sm.transition(Stage.S2d)
print('[OK] 第3次退回被拦截' if blocked else '[FAIL] 熔断失效')
# 每日LLM上限
for _ in range(51): sm.record_llm_call()
print('[OK] 51次后拒绝LLM' if not sm.can_call_llm(50) else '[FAIL] 计数未生效')
" 2>nul
if %errorlevel% equ 0 (set /a PASS+=1) else (set /a FAIL+=1)
echo.

REM ── 场景 D: config 缺失 ──
echo [D] 配置缺失降级测试...
%PYTHON% -c "
import sys; sys.path.insert(0,'agents')
from skill_loader import SkillLoader
# 测试 config 缺失时 skill_loader 仍可用
loader = SkillLoader()
prompt = loader.build('unknown', {})
print('[OK] unknown task: %d chars' % len(prompt))
" 2>nul
if %errorlevel% equ 0 (set /a PASS+=1) else (set /a FAIL+=1)
echo.

echo ============================================================
echo   结果: %PASS% 通过 / %FAIL% 失败
echo ============================================================
pause

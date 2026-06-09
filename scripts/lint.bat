@echo off
REM ============================================================
REM lint.bat — 代码质量快速检查（仅依赖 Python stdlib）
REM 
REM 检查项:
REM   1. py_compile — 语法错误
REM   2. 模块 import — 能否被 import
REM   3. __main__ 自检 — 运行每个模块的自检代码
REM
REM 用法: 双击运行 或 scripts\lint.bat
REM ============================================================

echo ============================================================
echo   番茄小说 AI 辅助创作系统 — 代码检查
echo ============================================================
echo.

set PYTHON=D:\miniconda3\envs\llm-shared\python.exe
set PASS=0
set FAIL=0

REM ── 检查 1: py_compile（语法错误） ──
echo [1/3] 语法检查 (py_compile)...
for %%f in (novel.py "\agents\\model_orchestrator.py" "\agents\\skill_loader.py") do (
    %PYTHON% -m py_compile "%%~f" 2>nul
    if %errorlevel% equ 0 (
        echo   [OK] %%~nxf
        set /a PASS+=1
    ) else (
        echo   [FAIL] %%~nxf — 语法错误，请检查
        set /a FAIL+=1
    )
)

REM ── 检查 2: import 测试（能否被导入） ──
echo.
echo [2/3] 导入测试...
%PYTHON% -c "import sys; sys.path.insert(0, 'agents'); from model_orchestrator import get_orchestrator; print('  [OK] model_orchestrator')" 2>nul
if %errorlevel% equ 0 (set /a PASS+=1) else (echo   [FAIL] model_orchestrator & set /a FAIL+=1)

%PYTHON% -c "import sys; sys.path.insert(0, 'agents'); from skill_loader import SkillLoader; print('  [OK] skill_loader')" 2>nul
if %errorlevel% equ 0 (set /a PASS+=1) else (echo   [FAIL] skill_loader & set /a FAIL+=1)

REM ── 检查 3: 自检运行 ──
echo.
echo [3/3] 自检运行...
%PYTHON% "agents\\model_orchestrator.py" 2>nul | findstr "DONE" >nul
if %errorlevel% equ 0 (echo   [OK] model_orchestrator 自检 & set /a PASS+=1) else (echo   [FAIL] model_orchestrator 自检 & set /a FAIL+=1)

%PYTHON% "agents\\skill_loader.py" 2>nul | findstr "DONE" >nul
if %errorlevel% equ 0 (echo   [OK] skill_loader 自检 & set /a PASS+=1) else (echo   [FAIL] skill_loader 自检 & set /a FAIL+=1)

echo.
echo ============================================================
echo   结果: %PASS% 通过 / %FAIL% 失败
echo ============================================================
pause

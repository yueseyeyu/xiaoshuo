@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul 2>&1

echo ============================================================
echo   Tomato Novel AI System - Code Lint
echo ============================================================
echo.

set "PYTHON=D:\miniconda3\envs\llm-shared\python.exe"
set PASS=0
set FAIL=0

echo [1/3] Syntax Check (py_compile)...
for %%f in (
    novel.py
    agents\model_orchestrator.py
    agents\skill_loader.py
    agents\outline_builder.py
    agents\character_designer.py
    analysis\book_processor.py
    analysis\quality_gate.py
    analysis\rhythm_analyzer.py
    analysis\genre_synthesizer.py
    analysis\synthesis_reporter.py
    analysis\creative_bridge.py
    analysis\comparison_engine.py
    analysis\structure_comparator.py
) do (
    if exist "%%~f" (
        %PYTHON% -m py_compile "%%~f" 2>&1
        if !errorlevel! equ 0 (
            echo   [OK] %%~nxf
            set /a PASS+=1
        ) else (
            echo   [FAIL] %%~nxf - syntax error
            set /a FAIL+=1
        )
    ) else (
        echo   [SKIP] %%~nxf - file not found
    )
)

echo.
echo [2/3] Import Test...

%PYTHON% -c "import sys; sys.path.insert(0,'agents'); from model_orchestrator import get_orchestrator; print('[OK] model_orchestrator')" 2>&1
if !errorlevel! equ 0 (set /a PASS+=1) else (echo   [FAIL] model_orchestrator import & set /a FAIL+=1)

%PYTHON% -c "import sys; sys.path.insert(0,'agents'); from skill_loader import SkillLoader; print('[OK] skill_loader')" 2>&1
if !errorlevel! equ 0 (set /a PASS+=1) else (echo   [FAIL] skill_loader import & set /a FAIL+=1)

%PYTHON% -c "import sys; sys.path.insert(0,'agents'); from outline_builder import inject_rhythm_targets; print('[OK] outline_builder')" 2>&1
if !errorlevel! equ 0 (set /a PASS+=1) else (echo   [FAIL] outline_builder import & set /a FAIL+=1)

%PYTHON% -c "import sys; sys.path.insert(0,'agents'); from character_designer import CharacterGraph; print('[OK] character_designer')" 2>&1
if !errorlevel! equ 0 (set /a PASS+=1) else (echo   [FAIL] character_designer import & set /a FAIL+=1)

%PYTHON% -c "import sys; sys.path.insert(0,'analysis'); from comparison_engine import generate_report; print('[OK] comparison_engine')" 2>&1
if !errorlevel! equ 0 (set /a PASS+=1) else (echo   [FAIL] comparison_engine import & set /a FAIL+=1)

%PYTHON% -c "import sys; sys.path.insert(0,'analysis'); from structure_comparator import compare_worldbuilding; print('[OK] structure_comparator')" 2>&1
if !errorlevel! equ 0 (set /a PASS+=1) else (echo   [FAIL] structure_comparator import & set /a FAIL+=1)

echo.
echo [3/3] Self-test Run...

%PYTHON% "agents\model_orchestrator.py" 2>&1
if !errorlevel! equ 0 (echo   [OK] model_orchestrator self-test & set /a PASS+=1) else (echo   [FAIL] model_orchestrator self-test & set /a FAIL+=1)

%PYTHON% "agents\skill_loader.py" 2>&1
if !errorlevel! equ 0 (echo   [OK] skill_loader self-test & set /a PASS+=1) else (echo   [FAIL] skill_loader self-test & set /a FAIL+=1)

echo.
echo ============================================================
echo   Result: !PASS! passed / !FAIL! failed
echo ============================================================

timeout /t 5 /nobreak >nul
endlocal
exit /b 0
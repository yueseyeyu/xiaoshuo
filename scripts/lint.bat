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
    src\xiaoshuo\agents\model_orchestrator.py
    src\xiaoshuo\agents\skill_loader.py
    src\xiaoshuo\agents\outline_builder.py
    src\xiaoshuo\agents\character_designer.py
    src\xiaoshuo\agents\state_machine.py
    src\xiaoshuo\agents\world_builder.py
    src\xiaoshuo\agents\session_manager.py
    src\xiaoshuo\agents\cross_review.py
    src\xiaoshuo\agents\chapter_decisions.py
    src\xiaoshuo\pipeline\book_processor.py
    src\xiaoshuo\pipeline\quality_gate.py
    src\xiaoshuo\pipeline\rhythm_analyzer.py
    src\xiaoshuo\pipeline\genre_synthesizer.py
    src\xiaoshuo\pipeline\synthesis_reporter.py
    src\xiaoshuo\pipeline\creative_bridge.py
    src\xiaoshuo\pipeline\comparison_engine.py
    src\xiaoshuo\pipeline\analyze_all.py
    src\xiaoshuo\pipeline\checkpoint.py
    src\xiaoshuo\pipeline\contract_chain.py
    src\xiaoshuo\pipeline\writing_instructions.py
    src\xiaoshuo\pipeline\scoring\__init__.py
    src\xiaoshuo\pipeline\scoring\vad_analyzer.py
    src\xiaoshuo\pipeline\scoring\structure_matcher.py
    src\xiaoshuo\pipeline\scoring\technique_tagger.py
    src\xiaoshuo\pipeline\scoring\commercial_engine.py
    src\xiaoshuo\pipeline\scoring\borda_ranker.py
    src\xiaoshuo\infra\__init__.py
    src\xiaoshuo\infra\logging_config.py
    src\xiaoshuo\infra\config_manager.py
    src\xiaoshuo\infra\performance.py
    src\xiaoshuo\infra\schemas.py
    src\xiaoshuo\tools\structure_comparator.py
    src\xiaoshuo\tools\intent_translator.py
    scripts\progress_server.py
    scripts\smoke_test_frontend.py
    src\xiaoshuo\infra\hardware_guardian.py
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
echo [2/3] Import Test (via src/ path)...

%PYTHON% -c "import sys; sys.path.insert(0,'src'); from xiaoshuo.agents.model_orchestrator import get_orchestrator; print('[OK] model_orchestrator')" 2>&1
if !errorlevel! equ 0 (set /a PASS+=1) else (echo   [FAIL] model_orchestrator import & set /a FAIL+=1)

%PYTHON% -c "import sys; sys.path.insert(0,'src'); from xiaoshuo.agents.skill_loader import SkillLoader; print('[OK] skill_loader')" 2>&1
if !errorlevel! equ 0 (set /a PASS+=1) else (echo   [FAIL] skill_loader import & set /a FAIL+=1)

%PYTHON% -c "import sys; sys.path.insert(0,'src'); from xiaoshuo.agents.outline_builder import inject_rhythm_targets; print('[OK] outline_builder')" 2>&1
if !errorlevel! equ 0 (set /a PASS+=1) else (echo   [FAIL] outline_builder import & set /a FAIL+=1)

%PYTHON% -c "import sys; sys.path.insert(0,'src'); from xiaoshuo.agents.character_designer import CharacterGraph; print('[OK] character_designer')" 2>&1
if !errorlevel! equ 0 (set /a PASS+=1) else (echo   [FAIL] character_designer import & set /a FAIL+=1)

%PYTHON% -c "import sys; sys.path.insert(0,'src'); from xiaoshuo.pipeline.comparison_engine import generate_report; print('[OK] comparison_engine')" 2>&1
if !errorlevel! equ 0 (set /a PASS+=1) else (echo   [FAIL] comparison_engine import & set /a FAIL+=1)

%PYTHON% -c "import sys; sys.path.insert(0,'src'); from xiaoshuo.tools.structure_comparator import compare_worldbuilding; print('[OK] structure_comparator')" 2>&1
if !errorlevel! equ 0 (set /a PASS+=1) else (echo   [FAIL] structure_comparator import & set /a FAIL+=1)

echo.
echo [3/3] Self-test Run...

%PYTHON% "src\xiaoshuo\agents\model_orchestrator.py" 2>&1
if !errorlevel! equ 0 (echo   [OK] model_orchestrator self-test & set /a PASS+=1) else (echo   [FAIL] model_orchestrator self-test & set /a FAIL+=1)

%PYTHON% "src\xiaoshuo\agents\skill_loader.py" 2>&1
if !errorlevel! equ 0 (echo   [OK] skill_loader self-test & set /a PASS+=1) else (echo   [FAIL] skill_loader self-test & set /a FAIL+=1)

echo.
echo ============================================================
echo   Result: !PASS! passed / !FAIL! failed
echo ============================================================

timeout /t 5 /nobreak >nul
endlocal
exit /b 0
@echo off
chcp 65001 >nul 2>&1
cd /d "%~dp0.."
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1

echo ============================================================
echo   番茄拆书舱 - 一键启动
echo ============================================================
echo.
echo [1/2] 启动 Qwen3.5-9B 模型服务 (端口 8000)...
start "Qwen3.5-9B" cmd /c "scripts\start_model.bat"
echo [OK] 模型服务已启动（等待约 10s 加载完成）

echo.
echo [2/2] 启动进度服务 (端口 8090)...
echo 等待模型就绪...
timeout /t 8 /nobreak >nul
start "ProgressServer" cmd /c "D:\miniconda3\envs\llm-shared\python.exe scripts\progress_server.py"
echo [OK] 进度服务已启动

echo.
echo [DONE] 服务启动完成，打开浏览器...
timeout /t 2 /nobreak >nul
start http://localhost:8090

echo.
echo 按任意键关闭此窗口（服务保持运行）...
pause >nul
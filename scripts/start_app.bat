@echo off
chcp 65001 >nul 2>&1
REM ============================================================
REM 番茄小说 AI 辅助创作系统 - 前后端一键启动（不启动大模型）
REM ============================================================

cd /d "%~dp0.."
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1

echo ============================================================
echo   番茄小说 AI 创作系统 - 前后端启动
echo ============================================================
echo.
echo [1/2] 启动 FastAPI 后端服务 (端口 8089)...
start "API Server" cmd /c "scripts\start_api_server.bat"
echo [OK] 后端启动中

echo.
echo [2/2] 启动 Vue 3 前端开发服务 (端口 5173)...
start "Frontend" cmd /c "cd frontend && npm run dev"
echo [OK] 前端启动中

echo.
echo [DONE] 服务已启动，请勿关闭弹出的两个窗口
echo 前端地址: http://localhost:5173/
echo 后端地址: http://localhost:8089/
echo.
echo 按任意键关闭此窗口（服务保持运行）...
pause >nul

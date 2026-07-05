@echo off
chcp 65001 >nul 2>&1
REM ============================================================
REM 番茄小说 AI 辅助创作系统 - API 服务启动脚本
REM
REM 用途: 启动 FastAPI 后端服务 (默认端口 8089)
REM       为前端 Vue 3 应用提供项目/拆书/报告/世界推演等接口
REM ============================================================

cd /d "%~dp0.."
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1

echo [START] 启动 API 服务 (端口 8089)...
echo.

D:\miniconda3\envs\llm-shared\python.exe -m xiaoshuo.api.server --port 8089 --host 0.0.0.0

echo.
echo [STOP] API 服务已关闭
pause

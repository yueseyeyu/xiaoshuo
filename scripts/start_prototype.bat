@echo off
cd /d "%~dp0..\prototype"
echo [OK] 启动番茄小说 AI 辅助创作系统原型...
call conda activate llm-shared
python server.py
pause
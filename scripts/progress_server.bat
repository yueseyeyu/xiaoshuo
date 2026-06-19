@echo off
chcp 65001 >nul 2>&1
cd /d "%~dp0.."
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1
D:\miniconda3\envs\llm-shared\python.exe scripts\progress_server.py

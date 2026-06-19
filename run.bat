@echo off
chcp 65001 >nul
cd /d d:\Code\xiaoshuo

echo ============================================
echo   拆书管线 — 自动进度监控
echo ============================================
echo.
echo 步骤 1/3: 启动进度面板 (端口 8090)

start "ProgressPanel" python scripts\progress_server.py
timeout /t 2 /nobreak >nul

echo 步骤 2/3: 打开浏览器
start http://localhost:8090
timeout /t 1 /nobreak >nul

echo 步骤 3/3: 开始拆书...
echo.
echo 关闭此窗口 = 停止拆书 (面板保留)
echo.
echo ============================================
python analysis\recursive_summarize.py --book all --genre 末世
echo.
echo ============================================
echo   完成！
echo ============================================
pause

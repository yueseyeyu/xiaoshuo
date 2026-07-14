@echo off
REM v17: 添加 --seed 42 修复跨session非确定性 (DeepSeek P0建议)
REM   根因: --seed 默认-1(随机), flash-attn tiling不同导致GPU浮点非确定性
REM   修复: --seed 42 固定种子. 如仍有非确定性, 尝试 --flash-attn off
REM v16: 修复 flash-attn + q4_0 V-cache 不兼容导致的 20x 减速
REM   根因: --flash-attn on + --cache-type-v q4_0 → 每次attention反量化 → 1.4 tok/s
REM   修复: --cache-type-v q8_0 → 恢复 flash-attn 快路径
REM   同时: ctx 8192->4096, parallel 2->1, batch 1024/512->512/256 (适配8GB显存)
REM v8.3: 添加交互确认，防止 AI 未经用户许可自动启动
echo [START] Qwen3.5-9B-IQ4_XS (v16: flash-attn + q8_0 V-cache)
echo.
echo [WARN] 即将启动本地模型，将占用约 6GB 显存。
echo.
set /p CONFIRM="确认启动模型? (输入 Y 继续, 其他键取消): "
if /i not "%CONFIRM%"=="Y" (
    echo [CANCEL] 用户取消启动。
    pause
    exit /b 0
)
echo.
echo [OK] 用户已确认，开始启动模型...
echo.

D:\miniconda3\envs\llm-shared\Library\bin\llama-server.exe ^
    --model D:/DaMoXing/Qwen3.5-9B-IQ4_XS.gguf ^
    --n-gpu-layers 35 ^
    --ctx-size 4096 ^
    --port 8000 ^
    --host 127.0.0.1 ^
    --alias Qwen3.5-9B ^
    --reasoning off ^
    --flash-attn on ^
    --cache-type-k q8_0 --cache-type-v q8_0 ^
    --cache-prompt ^
    --parallel 1 ^
    --ubatch-size 256 --batch-size 512 ^
    --threads 10 ^
    --mlock ^
    --defrag-thold 0.9 ^
    --seed 42

echo.
echo [STOP] server closed
pause

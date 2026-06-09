@echo off
REM ============================================================
REM 番茄小说 AI 辅助创作系统 - 模型启动脚本
REM 
REM 用途: 启动 Qwen3.5-9B (reasoning off, 适合 S3/S4)
REM       S1 创意引导需要 thinking: --reasoning on
REM v3: flash-attn on + KV q8_0 + parallel 4 + cont-batching
REM ============================================================

echo [START] Qwen3.5-9B-Q4_K_M (v3 optimized: flash-attn + KV q8_0 + parallel 4)
echo.

D:\miniconda3\envs\llm-shared\Library\bin\llama-server.exe ^
    --model D:/DaMoXing/Qwen3.5-9B-Q4_K_M.gguf ^
    --n-gpu-layers 99 ^
    --ctx-size 3072 ^
    --port 8000 ^
    --host 127.0.0.1 ^
    --alias Qwen3.5-9B ^
    --reasoning off ^
    --flash-attn on ^
    --cache-type-k q8_0 --cache-type-v q8_0 ^
    --cache-prompt ^
    --parallel 2 ^
    --ubatch-size 512 --batch-size 1024

echo.
echo [STOP] server closed
pause

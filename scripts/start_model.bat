@echo off
REM ============================================================
REM 番茄小说 AI 辅助创作系统 - 模型启动脚本
REM 
REM 用途: 启动 Qwen3.5-9B (reasoning off, 适合 S3/S4)
REM       S1 创意引导需要 thinking: --reasoning on
REM v5: flash-attn on + KV asym q8_0/q4_0 + parallel 2
REM n-gpu-layers: Qwen3.5-9B 共 35 层，全部 GPU offload
REM MTP: Qwen3.5-9B 不含 MTP heads，此项不适用
REM TurboQuant: 未进入 llama.cpp mainline，暂不可用
REM ============================================================

echo [START] Qwen3.5-9B-Q4_K_M (v5: ctx8192 + KV asym q8_0/q4_0 + parallel 2)
echo.

D:\miniconda3\envs\llm-shared\Library\bin\llama-server.exe ^
    --model D:/DaMoXing/Qwen3.5-9B-Q4_K_M.gguf ^
    --n-gpu-layers 35 ^
    --ctx-size 8192 ^
    --port 8000 ^
    --host 127.0.0.1 ^
    --alias Qwen3.5-9B ^
    --reasoning off ^
    --flash-attn on ^
    --cache-type-k q8_0 --cache-type-v q4_0 ^
    --cache-prompt ^
    --parallel 2 ^
    --ubatch-size 512 --batch-size 1024 ^
    --threads 10 ^
    --mlock ^
    --defrag-thold 0.9

echo.
echo [STOP] server closed
pause

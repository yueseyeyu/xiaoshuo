@echo off
REM ============================================================
REM 番茄小说 AI 辅助创作系统 - 模型启动脚本
REM 
REM 用途: 启动 Qwen3.5-9B (reasoning off, 适合 S3/S4)
REM       S1 创意引导需要 thinking: --reasoning on
REM v5: flash-attn on + KV asym q8_0/q4_0 + parallel 2
REM n-gpu-layers: Qwen3.5-9B 共 35 层，全部 GPU offload
REM MTP: Qwen3.5-9B-IQ4_XS 不含 MTP layers，无法启用 draft-mtp
REM 替代方案: ngram-mod 自推测解码（~16MB 内存，零额外模型）
REM 参数说明:
REM   --spec-ngram-mod-n-match 24  : n-gram 匹配长度
REM   --spec-ngram-mod-n-min 48    : 最小草稿 token 数
REM   --spec-ngram-mod-n-max 64    : 最大草稿 token 数
REM ============================================================

echo [START] Qwen3.5-9B-IQ4_XS (v8.3: llama.cpp b9802, IQ4_XS, ngram-mod)
echo.

D:\miniconda3\envs\llm-shared\Library\bin\llama-server.exe ^
    --model D:/DaMoXing/Qwen3.5-9B-IQ4_XS.gguf ^
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
    --defrag-thold 0.9 ^
    --spec-type ngram-mod ^
    --spec-ngram-mod-n-match 24 ^
    --spec-ngram-mod-n-min 48 ^
    --spec-ngram-mod-n-max 64

echo.
echo [STOP] server closed
pause

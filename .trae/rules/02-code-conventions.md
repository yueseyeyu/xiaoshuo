---
alwaysApply: true
description: "代码规范和 SSOT 单一事实源原则"
---

# 代码规范

## SSOT（单一事实源）
- 任何数值/阈值/路径/端口 → 只在 `config.yaml` 定义一次
- 代码必须从 config 读取，禁止硬编码
- 修改 config.yaml 后 → 检查所有读取该 key 的 .py

## 变更后同步
1. 新增目录 → 同步 `novel.py DIRECTORIES` + 注册此文件
2. 新增模块 → 注册此文件"目录速查"段
3. 里程碑完成 → 更新 `status.mdc`（注意：这个在 `.codebuddy/rules/` 下！）
4. 修改 Python 文件或 config.yaml → 运行 `scripts\lint.bat`

## 语法约束
- 使用 subprocess 时，禁止 PIPE 模式用于无消费者的进程，用 DEVNULL 替代
- 函数不要直接修改入参 dict/list → 用 `result = dict(input)` 浅拷贝
- 模式切换函数中，先保存 old_value 再打印（防 print bug）

## 模型相关
- 主模型端口 8000（Qwen3.5-9B）
- WebNovel 专家端口 8001（当前未启用）
- 逻辑警察端口 8002（DeepSeek-R1-Distill，当前未启用）
- 通信方式：llama-server HTTP API（OpenAI 兼容），非 Python in-process

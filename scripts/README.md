# scripts/ — 项目工具脚本

> 所有可执行脚本集中管理，不散落在项目根目录。

## 脚本清单

| 脚本 | 用途 | 使用方式 |
|------|------|---------|
| `start_model.bat` | 启动 Qwen3.5-9B llama.cpp server (OpenAI API :8000) | 双击运行 |
| `lint.bat` | 代码质量快速检查 (py_compile + import + 自检) | 每次改完 .py 后运行 |

## 后续将添加

| 计划脚本 | 用途 |
|---------|------|
| `start_model_webnovel.bat` | 启动 Qwen3-4B-WebNovel server (:8001) |
| `start_model_logicpolice.bat` | 启动 DeepSeek-R1 逻辑警察 server (:8002) |
| `p0_stress_test.bat` | P0-0 末日生存压力测试一键运行 |

## 依赖

所有模型脚本依赖：
- conda 环境: `llm-shared` (Python 3.12, llama-cpp-python 0.3.22, CUDA 13.0)
- 模型文件: `D:\DaMoXing\*.gguf`
- llama-server.exe: `D:\miniconda3\envs\llm-shared\Library\bin\llama-server.exe`

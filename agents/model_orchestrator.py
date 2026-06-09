"""
model_orchestrator.py — 双模型路由、健康检查、降级
============================================================
─ 文件定位 ─
.agents/核心模块之一。管理 llama-server.exe 实例的生命周期，
提供统一的推理 API（OpenAI 兼容格式），自动处理降级。

─ 架构设计 ─
- ModelServer: 封装单个 llama-server.exe 进程管理
- ModelOrchestrator: 编排所有 ModelServer，按 task_type 路由
- 通信方式: HTTP API（非 in-process），模型 server 崩溃不拉垮 orchestrator

─ 对外接口 ─
from model_orchestrator import get_orchestrator
orch = get_orchestrator()              # 单例
orch.start_all()                       # 启动所有配置的模型
response = orch.chat("S1_creative", messages)  # 按任务类型路由
orch.stop_all()                        # 优雅关闭

─ 依赖 ─
- Python stdlib: subprocess, json, urllib, time, threading, pathlib
- pyyaml: 读取 config.yaml
- 外部依赖: D:/miniconda3/envs/llm-shared/Library/bin/llama-server.exe

─ 开发者指引 ─
· 新增模型: 在 config.yaml model_orchestration.models 下添加配置块
· 新增任务路由: 在 routing_table 中添加 task_type → model_key 映射
· 禁用模型: 设置对应模型的 enabled: false
· 手动降级: orch.set_mode("single_model") — 停掉所有非主模型
· <think> 标签: _strip_thinking_tags() 自动清理 Qwen3.5 的 empty thinking 输出
"""

import subprocess
import json
import urllib.request
import urllib.error
import time
import threading
import re
from pathlib import Path

import yaml


# ============================================================
# 常量：文件路径
# ============================================================
PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_ROOT / "config.yaml"
# LLAMA_SERVER 路径从 config.yaml → model_orchestration.llama_server_exe 读取
# 默认值作为 fallback


# ============================================================
# 工具函数：加载配置
# ============================================================
def _load_config() -> dict:
    """加载 config.yaml 中的 model_orchestration 部分。

    调用时机: 每次实例化 ModelOrchestrator 时调用。
    """
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        full_config = yaml.safe_load(f)
    return full_config.get("model_orchestration", {})


# ============================================================
# 工具函数：清理 Qwen3.5 的 empty <think> 标签
# ============================================================
def _strip_thinking_tags(text: str) -> str:
    """移除 Qwen3.5-9B 推理时产生的空 <think>...</think> 标签。

    Qwen3.5-9B-Instruct 即使在 chatml/chating=0 模式下仍会输出
    <think>\\n\\n</think> 前缀。此函数清理这些空标签，不影响正常内容。

    调用时机: 每个 chat() / chat_stream() 返回前自动调用。
    """
    if not text:
        return text
    # 匹配 <think> 标签及其内容（非贪婪）
    # 同时处理截断的 <think>（无关闭标签）
    cleaned = re.sub(r"<think>.*?</think>\s*", "", text, flags=re.DOTALL)
    cleaned = re.sub(r"<think>.*$", "", cleaned, flags=re.DOTALL)  # 截断的 <think>
    return cleaned.strip()


# ============================================================
# ModelServer: 单个 llama-server.exe 实例的进程管理器
# ============================================================
class ModelServer:
    """管理一个 llama-server.exe 进程的生命周期。

    用法:
        server = ModelServer("main_model", config_dict)
        server.start()           # 启动 llama-server.exe
        server.health_check()    # 返回 True/False
        server.chat(messages)    # 发送聊天请求
        server.stop()            # 终止进程

    属性:
        model_key (str): config 中的模型键名（如 "main_model"）
        port (int): HTTP 端口
        process (subprocess.Popen | None): 运行中的 server 进程
        base_url (str): API 基地址
    """

    def __init__(self, model_key: str, model_config: dict):
        """
        Args:
            model_key: config 中 models 的 key，如 "main_model"
            model_config: 对应 key 的完整配置字典
        """
        self.model_key = model_key
        self.config = model_config

        # ── 核心参数 ──
        self.name = model_config.get("name", model_key)
        self.gguf_path = model_config.get("gguf", "")
        self.port = model_config.get("port", 8000)
        self.n_ctx = model_config.get("n_ctx", 4096)
        self.n_gpu_layers = model_config.get("n_gpu_layers", 35)
        self.chat_format = model_config.get("chat_format", "chatml")
        self.enabled = model_config.get("enabled", True)

        # ── 运行时状态 ──
        self.process: subprocess.Popen | None = None
        self.base_url = f"http://127.0.0.1:{self.port}"

    # ── 进程启动 ──

    def start(self) -> bool:
        """启动 llama-server.exe 进程。

        使用 subprocess.Popen 后台启动，不阻塞当前进程。
        server 的 stdout/stderr 输出到 DEVNULL（通过 /health 检查状态）。

        返回: True=启动成功, False=启动失败
        """
        # 前置检查：GGUF 文件是否存在
        if not self.gguf_path or not Path(self.gguf_path).exists():
            print(f"[FAIL] ModelServer({self.model_key}): GGUF 文件不存在: {self.gguf_path}")
            return False

        # 前置检查：llama-server.exe 路径（从 config 或默认值）
        llama_server = Path(self.config.get(
            "llama_server_exe",
            "D:/miniconda3/envs/llm-shared/Library/bin/llama-server.exe"
        ))
        if not llama_server.exists():
            print(f"[FAIL] llama-server.exe 不存在: {llama_server}")
            return False

        # 前置检查：端口是否已被占用（可能是上次未清理的实例）
        if self._is_port_in_use():
            print(f"[WARN] ModelServer({self.model_key}): 端口 {self.port} 已被占用，尝试复用已有 server")
            return True  # 假设已有 server 在运行，返回 True

        # ── 构建命令行参数 ──
        cmd = [
            str(llama_server),
            "--model", self.gguf_path,
            "--n-gpu-layers", str(self.n_gpu_layers),
            "--ctx-size", str(self.n_ctx),
            "--port", str(self.port),
            "--host", "127.0.0.1",
            "--alias", self.name,
            "--chat-template", self.chat_format,
        ]

        print(f"[START] {self.name} → port {self.port}...")

        try:
            # DEVNULL: 丢弃 stdout/stderr，避免 PIPE 缓冲区满导致子进程死锁
            # 健康状态通过 HTTP /health 端点检查，不需要解析控制台输出
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW,  # Windows: 不弹新窗口
            )
            return True
        except Exception as e:
            print(f"[FAIL] ModelServer({self.model_key}) 启动失败: {e}")
            return False

    def wait_until_ready(self, timeout: int = 120) -> bool:
        """轮询健康检查接口，等待 server 完全加载。

        模型加载（从 GGUF 读到 GPU 卸载）需要 5-30 秒，
        此方法阻塞等待直到 /health 返回 200 或超时。

        Args:
            timeout: 最长等待秒数，默认 120 秒

        Returns:
            True=就绪, False=超时
        """
        start_time = time.time()
        while time.time() - start_time < timeout:
            if self.health_check():
                elapsed = time.time() - start_time
                print(f"[OK] {self.name} 就绪 (耗时 {elapsed:.1f}s)")
                return True
            time.sleep(2)

        print(f"[FAIL] {self.name} 启动超时 ({timeout}s)")
        return False

    # ── 健康检查 ──

    def health_check(self) -> bool:
        """HTTP GET /health 检查 server 是否存活。

        llama.cpp server 在模型加载完成后才会开始监听 /health 端点。

        返回: True=存活, False=未响应
        """
        try:
            url = f"{self.base_url}/health"
            with urllib.request.urlopen(url, timeout=3) as resp:
                return resp.status == 200
        except (urllib.error.URLError, OSError, TimeoutError):
            return False

    def is_running(self) -> bool:
        """检查进程是否存活（不看健康检查，只看进程存在性）。

        用途: server 启动后加载模型期间（/health 尚未就绪），
        但进程已存在时，此方法返回 True。
        """
        if self.process is None:
            return False
        return self.process.poll() is None

    # ── 推理接口 ──

    def chat(
        self,
        messages: list[dict],
        max_tokens: int = 2048,
        temperature: float = 0.7,
        timeout: int = 120,
    ) -> dict:
        """发送聊天请求到 llama.cpp 的 /v1/chat/completions 端点。

        llama.cpp server 实现了 OpenAI 兼容的 chat completions API。

        Args:
            messages: [{"role": "user/system/assistant", "content": "..."}]
            max_tokens: 最大生成 token 数
            temperature: 采样温度（0=贪婪, 1=创造）
            timeout: 超时秒数

        Returns:
            {
                "content": str,          # 模型回复文本（已清理 <think> 标签）
                "finish_reason": str,    # stop/length/abort
                "usage": {              # Token 统计
                    "prompt_tokens": int,
                    "completion_tokens": int,
                    "total_tokens": int
                },
                "model": str            # 模型名称
            }
            或 {"error": str} 如果失败

        开发者: 需要流式输出请用 chat_stream()
        """
        if not self.health_check():
            return {"error": f"ModelServer({self.model_key}) 未就绪"}

        # ── 构建请求体 ──
        body = json.dumps({
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": False,
        }).encode("utf-8")

        url = f"{self.base_url}/v1/chat/completions"
        req = urllib.request.Request(
            url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                choice = data["choices"][0]
                raw_content = choice["message"].get("content", "")
                return {
                    "content": _strip_thinking_tags(raw_content),
                    "finish_reason": choice.get("finish_reason", "unknown"),
                    "usage": data.get("usage", {}),
                    "model": data.get("model", self.name),
                }
        except urllib.error.URLError as e:
            return {"error": f"HTTP 请求失败: {e.reason}"}
        except (json.JSONDecodeError, KeyError) as e:
            return {"error": f"响应解析失败: {e}"}
        except TimeoutError:
            return {"error": f"请求超时 ({timeout}s)"}

    # ── 进程停止 ──

    def stop(self, timeout: int = 10):
        """优雅停止 llama-server.exe 进程。

        先发送 SIGTERM（Windows 等效），等待 timeout 秒，
        如果未退出则 SIGKILL（强制终止）。

        Caller: 程序退出时由 orchestrator.stop_all() 统一调用。
        """
        if self.process is None:
            return

        print(f"[STOP] {self.name} (port {self.port})...")

        # 步骤1: 终止进程树（Windows 用 taskkill /t 杀子进程）
        try:
            subprocess.run(
                ["taskkill", "/f", "/t", "/pid", str(self.process.pid)],
                capture_output=True,
                timeout=timeout,
            )
        except (subprocess.TimeoutExpired, OSError):
            pass

        # 步骤2: 清理引用
        self.process = None

    # ── 内部辅助 ──

    def _is_port_in_use(self) -> bool:
        """检查端口是否已被占用（可能是之前未清理的 server）。"""
        try:
            url = f"{self.base_url}/health"
            urllib.request.urlopen(url, timeout=1)
            return True
        except Exception:
            return False


# ============================================================
# ModelOrchestrator: 统一模型管理与路由
# ============================================================
class ModelOrchestrator:
    """管理所有模型 server 的生命周期和请求路由。

    用法:
        orch = get_orchestrator()    # 获取全局单例
        orch.start_all()             # 启动所有 enabled 的模型
        result = orch.chat("S1_creative", messages)  # 按任务类型路由
        orch.stop_all()              # 优雅关闭

    设计决策:
    - 单例模式: 整个系统只需一个 orchestrator 实例
    - 降级逻辑: P0-2已确定single_model, 保留dual_model兼容路径
    - 线程安全: health_check 使用锁保护
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        """单例模式: 确保全局只有一个 orchestrator 实例。

        线程安全的 double-check locking 实现。
        """
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        """初始化 orchestrator。

        仅在首次实例化时执行（单例模式保护）。
        """
        if hasattr(self, "_initialized"):
            return
        self._initialized = True

        # ── 加载配置 ──
        self.config = _load_config()
        self.mode = self.config.get("mode", "single_model")  # 当前运行模式
        self.routing_table = self.config.get("routing_table", {})
        self.fallback_mode = self.config.get("fallback", "single_model")

        # ── 创建 ModelServer 实例 ──
        self.servers: dict[str, ModelServer] = {}
        for key, cfg in self.config.get("models", {}).items():
            self.servers[key] = ModelServer(key, cfg)

    # ── 生命周期管理 ──

    def start_all(self, wait: bool = True) -> bool:
        """启动所有 enabled 的模型 server。

        根据 config 中的 "mode" 决定启动哪些模型:
        - dual_model: 启动 main_model + webnovel_expert（若 enabled）
        - single_model: 仅启动 main_model

        Args:
            wait: True=等待所有 server 就绪后返回; False=启动后立即返回

        Returns:
            True=启动成功（所有模型就绪或跳过）, False=有模型启动失败
        """
        all_ok = True

        # ── 主模型必须启动 ──
        main = self.servers.get("main_model")
        if main is None:
            print("[FAIL] orchestrator: main_model 未在配置中找到")
            return False

        if not main.start():
            return False  # 主模型启动失败 = 系统不可用

        if wait:
            if not main.wait_until_ready():
                return False

        # ── 双模型模式: 启动 WebNovel 专家 ──
        if self.mode == "dual_model":
            for key in self.servers:
                if key == "main_model":
                    continue  # 已处理
                server = self.servers[key]
                if not server.enabled:
                    print(f"  - {server.name}: enabled=false, 跳过")
                    continue
                if not server.gguf_path:
                    print(f"  - {server.name}: gguf 路径未配置, 跳过")
                    continue

                if server.start():
                    if wait:
                        server.wait_until_ready()
                else:
                    print(f"[WARN] {server.name} 启动失败，自动降级至 {self.fallback_mode}")
                    all_ok = False

            # ── 如果有专家模型启动失败，自动降级 ──
            if not all_ok:
                self._fallback()

        return all_ok

    def stop_all(self):
        """停止所有运行中的模型 server。"""
        for server in self.servers.values():
            if server.is_running():
                server.stop()

    # ── 请求路由 ──

    def chat(
        self,
        task_type: str,
        messages: list[dict],
        max_tokens: int = 2048,
        temperature: float = 0.7,
        timeout: int = 120,
    ) -> dict:
        """按 task_type 路由到对应模型 server 进行推理。

        路由逻辑:
        1. 查 routing_table 获取目标模型 key
        2. 如果目标模型不可用 → 降级至 main_model
        3. main_model 也不可用 → 返回 error

        Args:
            task_type: 任务类型，如 "S1_creative", "S3_logic_cop"
            messages: 聊天消息列表（OpenAI 格式）
            max_tokens: 最大生成 token
            temperature: 采样温度
            timeout: 超时秒数

        Returns:
            同 ModelServer.chat() 的返回值格式
        """
        # ── 查路由表 ──
        target_key = self.routing_table.get(task_type, "main_model")
        target = self.servers.get(target_key)

        # ── 目标运行中 → 直接推理 ──
        if target is not None and target.health_check():
            return target.chat(messages, max_tokens, temperature, timeout)

        # ── 目标未运行 → 尝试启动 (不切换, 单模型时代) ──
        if target is not None and not target.is_running():
            if target.start() and target.wait_until_ready(timeout=60):
                return target.chat(messages, max_tokens, temperature, timeout)

        # ── 目标不可用 → 降级至 main_model ──
        main = self.servers.get("main_model")
        if main is not None and target_key != "main_model":
            if not main.health_check() and not main.is_running():
                main.start()
                main.wait_until_ready(timeout=60)
            if main.health_check():
                print(f"[FALLBACK] {task_type}: {target_key} 不可用 -> main_model")
                return main.chat(messages, max_tokens, temperature, timeout)

        # ── 全部不可用 ──
        return {"error": "所有模型均不可用"}

    def get_model_for_task(self, task_type: str) -> ModelServer | None:
        """获取 task_type 对应的 ModelServer 实例（不执行推理）。

        用途: 需要直接访问 server 实例时（如修改参数、手动调用 chat）。
        """
        target_key = self.routing_table.get(task_type, "main_model")
        return self.servers.get(target_key)

    # ── 降级与恢复 ──

    def set_mode(self, mode: str):
        """手动切换运行模式。

        Args:
            mode: "single_model" | "dual_model"

        Caller: 在 P0-1 实验结果出来后手动调用
        """
        if mode not in ("single_model", "dual_model"):
            print(f"[FAIL] 无效模式: {mode}，必须是 single_model 或 dual_model")
            return

        old_mode = self.mode

        # ── 如果从 dual → single, 停掉非主模型 ──
        if mode == "single_model" and old_mode == "dual_model":
            for key, server in self.servers.items():
                if key != "main_model" and server.is_running():
                    server.stop()

        self.mode = mode
        print(f"[OK] orchestrator 模式切换: {old_mode} → {mode}")

    def _fallback(self):
        """内部降级：停掉所有专家模型，回到单模型模式。

        Caller: start_all() 中检测到专家模型启动失败时调用。
        """
        print(f"[FALLBACK] 降级至 {self.fallback_mode}...")
        for key, server in self.servers.items():
            if key != "main_model" and server.is_running():
                server.stop()
        self.mode = self.fallback_mode

    # ── 状态查询 ──

    def status(self) -> dict:
        """返回所有模型的运行状态，供 novel.py status 命令使用。

        返回:
            {
                "mode": "dual_model" | "single_model",
                "models": {
                    "main_model": {"running": bool, "port": int, "healthy": bool},
                    ...
                }
            }
        """
        result = {"mode": self.mode, "models": {}}
        for key, server in self.servers.items():
            result["models"][key] = {
                "name": server.name,
                "running": server.is_running(),
                "port": server.port,
                "healthy": server.health_check(),
                "enabled": server.enabled,
            }
        return result


# ============================================================
# 单例工厂函数
# ============================================================
def get_orchestrator() -> ModelOrchestrator:
    """获取全局唯一的 ModelOrchestrator 实例。

    所有模块通过此函数获取 orchestrator，确保全系统只有一个实例。

    用法:
        from model_orchestrator import get_orchestrator
        orch = get_orchestrator()
    """
    return ModelOrchestrator()


# ============================================================
# 模块自检
# ============================================================
if __name__ == "__main__":
    print("=" * 60)
    print("  model_orchestrator.py — 自检")
    print("=" * 60)

    # 1. 加载配置
    print("\n[TEST] 加载 config.yaml...")
    config = _load_config()
    print(f"  mode: {config.get('mode', 'N/A')}")
    model_keys = list(config.get("models", {}).keys())
    print(f"  models: {model_keys}")

    # 2. 检查 llama-server.exe（从 config 中读取路径）
    llama_exe = config.get("llama_server_exe",
        "D:/miniconda3/envs/llm-shared/Library/bin/llama-server.exe")
    print(f"\n[TEST] llama-server.exe: {'[OK]' if Path(llama_exe).exists() else '[FAIL]'} {llama_exe}")

    # 3. 检查 GGUF 文件
    for key, cfg in config.get("models", {}).items():
        path = cfg.get("gguf", "")
        exists = Path(path).exists() if path else False
        print(f"  {key}: {'[OK]' if exists else '[FAIL] 待下载'} {Path(path).name if path else '(未配置)'}")

    # 4. 创建 orchestrator（不启动 server）
    orch = get_orchestrator()
    print(f"\n[TEST] orchestrator 实例化: [OK]")
    st = orch.status()
    print(f"  mode: {st['mode']}")
    for key, info in st["models"].items():
        status_str = f"port:{info['port']} enabled:{info['enabled']}"
        print(f"  {key}: {status_str}")

    # 5. 测试 <think> 标签清理
    print(f"\n[TEST] _strip_thinking_tags:")
    test_cases = [
        ("<think>\n\n</think>\n\nHello World", "Hello World"),
        ("<think>reasoning...</think>Actual", "Actual"),
        ("No think tags here", "No think tags here"),
        ("", ""),
    ]
    for input_text, expected in test_cases:
        result = _strip_thinking_tags(input_text)
        status = "[OK]" if result == expected else "[FAIL]"
        print(f"  {status} {repr(input_text[:40])}... → {repr(result[:40])}")

    print("\n[DONE] model_orchestrator.py 自检完成")

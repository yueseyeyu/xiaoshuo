#!/usr/bin/env python3
"""
prototype/server.py — 番茄小说 AI 辅助创作系统 前端原型服务器（已弃用）
============================================================================
启动方式: python server.py  (或 scripts/start_prototype.bat)
访问地址: 由 config.yaml 中 prototype.port 决定，默认 http://localhost:8088

注意：v8.0 起静态文件与 API 统一由 src/xiaoshuo/api/server.py (FastAPI) 提供，
      本文件保留作为独立原型服务器的备用方案。
============================================================================
"""

import http.server
import json
import os
import re
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path
from urllib.parse import urlparse, parse_qs

import psutil
import yaml

# 项目根目录
ROOT = Path(__file__).resolve().parent.parent
PROTO_DIR = Path(__file__).resolve().parent

# 动态引入项目内的大纲构建工具（用于真实生成节奏目标）
sys.path.insert(0, str(ROOT / "src"))
try:
    from xiaoshuo.agents.outline_builder import load_guidance_benchmarks, generate_rhythm_plan
except Exception as _e:
    load_guidance_benchmarks = None
    generate_rhythm_plan = None
    print("[WARN] 无法导入 outline_builder:", _e)


def load_config():
    """读取项目根目录 config.yaml，返回 prototype 相关配置"""
    config_path = ROOT / "config.yaml"
    defaults = {
        "port": 8080,
        "genre": "末世",
        "data_dir": "data/reports",
        "auto_open_browser": False,
        "theme_presets": [],
    }
    if not config_path.exists():
        return defaults
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        proto_cfg = cfg.get("prototype", {})
        return {
            "port": int(proto_cfg.get("port", defaults["port"])),
            "genre": proto_cfg.get("genre", defaults["genre"]),
            "data_dir": proto_cfg.get("data_dir", defaults["data_dir"]),
            "auto_open_browser": bool(proto_cfg.get("auto_open_browser", defaults["auto_open_browser"])),
            "theme_presets": proto_cfg.get("theme_presets", defaults["theme_presets"]),
        }
    except Exception:
        return defaults


CONFIG = load_config()
GENRE = CONFIG["genre"]
DATA_DIR = ROOT / CONFIG["data_dir"] / GENRE
MANUALS_DIR = DATA_DIR / "writing_manuals"
DIAGNOSIS_DIR = DATA_DIR / "deep_diagnosis"
SYNTHESIS_DIR = DATA_DIR / "synthesis"

# ── 日志系统 v7.6 ──
LOG_DIR = ROOT / "logs" / "prototype"
ACCESS_LOG_DIR = LOG_DIR / "access"
OP_LOG_DIR = LOG_DIR / "operations"
for d in [LOG_DIR, ACCESS_LOG_DIR, OP_LOG_DIR]:
    d.mkdir(parents=True, exist_ok=True)

_log_lock = threading.Lock()


def _log_append(category: str, entry: dict):
    """以 JSONL 格式追加一条日志记录（线程安全）"""
    entry["timestamp"] = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())
    today = time.strftime("%Y-%m-%d")
    if category == "access":
        log_path = ACCESS_LOG_DIR / f"{today}.jsonl"
    elif category == "operation":
        log_path = OP_LOG_DIR / f"{today}.jsonl"
    else:
        log_path = LOG_DIR / f"{category}_{today}.jsonl"
    with _log_lock:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def log_access(handler, method: str, path: str, params: dict, status: int,
               duration_ms: float, req_body: dict = None, resp_size: int = 0):
    """记录一次 API 请求的完整链路"""
    entry = {
        "method": method,
        "path": path,
        "params": params or {},
        "client_ip": handler.client_address[0] if hasattr(handler, "client_address") else "",
        "status": status,
        "duration_ms": round(duration_ms, 2),
        "resp_size": resp_size,
    }
    if req_body:
        entry["req_body"] = req_body
    _log_append("access", entry)


def log_operation(user_action: str, detail: dict = None):
    """记录前端用户操作（由前端通过 POST /api/logs/operations 上报）"""
    entry = {
        "action": user_action,
        "detail": detail or {},
    }
    _log_append("operation", entry)

# 尝试加载 library_data.json
LIBRARY_DATA_PATH = PROTO_DIR / "library_data.json"
try:
    with open(LIBRARY_DATA_PATH, "r", encoding="utf-8") as f:
        LIBRARY_DATA = json.load(f)
except Exception:
    LIBRARY_DATA = {"books": [], "genres": [], "counts": []}


# ============================================================
# 数据读取辅助函数
# ============================================================

def load_json(path):
    """安全加载 JSON 文件"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def load_md(path):
    """加载 Markdown 文件为纯文本"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""


def parse_instructions(book_name, chapter=None):
    """解析逐章指令文件，按章节分割
    格式: ## 第N章 (...) \n  [!!] ... \n  [!] ... \n  [-] ...
    book_name 支持模糊匹配（如 "全球进化" 匹配 "《全球进化》（精校版全本）作者：咬狗"）
    """
    # 模糊匹配：遍历目录找包含 book_name 的文件
    if not MANUALS_DIR.exists():
        return None
    matched = None
    for f in MANUALS_DIR.glob("*_逐章指令.md"):
        if book_name in f.stem:
            matched = f
            break
    if not matched:
        return None

    text = load_md(matched)
    # 按 ## 分割章节
    sections = re.split(r"\n(?=## 第\d+章)", text)
    chapters = []
    for sec in sections:
        m = re.match(r"## 第(\d+)章.*?\n(.*)", sec, re.DOTALL)
        if m:
            ch_num = int(m.group(1))
            body = m.group(2).strip()
            items = []
            for line in body.split("\n"):
                line = line.strip()
                if line.startswith("[!!]"):
                    items.append({"level": "critical", "text": line[4:].strip()})
                elif line.startswith("[!]"):
                    items.append({"level": "warning", "text": line[3:].strip()})
                elif line.startswith("[~]"):
                    items.append({"level": "info", "text": line[3:].strip()})
                elif line.startswith("[-]"):
                    items.append({"level": "minor", "text": line[3:].strip()})
            if chapter is None or ch_num == chapter:
                chapters.append({"chapter": ch_num, "items": items})

    if chapter is not None:
        return chapters[0] if chapters else None
    return chapters


# ============================================================
# API 端点处理函数
# ============================================================

def api_books():
    """GET /api/books — 书库列表（含拆书统计）"""
    books = LIBRARY_DATA.get("books", [])
    # 用 rhythm_csv 字段匹配拆书数据
    rhythm_map = {}
    for key, info in _list_rhythm_csvs().items():
        # key 示例: "《从红月开始》（校对版全本）作者：黑山老鬼"
        rhythm_map[info["path"].name] = _read_rhythm_summary(info["path"])
    for book in books:
        csv_name = book.get("rhythm_csv", "")
        if csv_name in rhythm_map:
            book["disassembly"] = rhythm_map[csv_name]
        else:
            book["disassembly"] = None
    return LIBRARY_DATA


def api_guidance():
    """GET /api/guidance — 末世题材创作指导"""
    guidance_path = DATA_DIR / f"{GENRE}_创作指导.json"
    data = load_json(guidance_path)
    if not data:
        return {"error": "创作指导数据不可用"}
    # 提取关键部分，减少传输量
    return {
        "genre": data.get("genre"),
        "book_count": data.get("book_count"),
        "total_chapters": data.get("total_chapters"),
        "worldbuilding": data.get("worldbuilding", {}).get("summary"),
        "dominant_conflicts": data.get("worldbuilding", {}).get("dominant_conflict_types"),
        "arc_distribution": data.get("worldbuilding", {}).get("arc_distribution"),
        "opening_hook_benchmark": data.get("worldbuilding", {}).get("opening_hook_benchmark"),
        "hook_rule": data.get("worldbuilding", {}).get("rule"),
        "guidance": data.get("worldbuilding", {}).get("guidance"),
        "chapter_structure": data.get("chapter_outline", {}).get("guidance"),
        "writing_style": data.get("writing_style", {}),
        "character_guidance": data.get("character", {}).get("summary"),
    }


def api_techniques():
    """GET /api/techniques — 写作技法总纲"""
    tech_path = SYNTHESIS_DIR / f"{GENRE}_写作技法总纲.md"
    text = load_md(tech_path)
    if not text:
        return {"error": "写作技法数据不可用"}
    # 提取章节标题作为结构
    sections = []
    for line in text.split("\n"):
        if line.startswith("## "):
            sections.append(line[3:].strip())
    return {
        "title": "末世类网文写作技法总纲",
        "sections": sections,
        "raw": text[:5000],  # 截断，前端按需展开
    }


def api_instructions(params):
    """GET /api/instructions?book=X&ch=N — 逐章写作指令"""
    book = params.get("book", [None])[0]
    ch_str = params.get("ch", [None])[0]
    chapter = int(ch_str) if ch_str else None

    # 列出可用的指令书
    if not book:
        manuals = []
        if MANUALS_DIR.exists():
            for f in MANUALS_DIR.glob("*_逐章指令.md"):
                name = f.stem.replace("_逐章指令", "")
                manuals.append({"name": name, "file": f.name})
        return {"books": manuals}

    result = parse_instructions(book, chapter)
    if result is None:
        return {"error": "未找到该书的逐章指令", "book": book}
    return {"book": book, "instructions": result}


def api_diagnosis():
    """GET /api/diagnosis — 深度诊断对比"""
    diag_path = DIAGNOSIS_DIR / f"{GENRE}_deep_diagnosis.json"
    data = load_json(diag_path)
    if not data:
        return {"error": "诊断数据不可用"}
    return data


def api_stats():
    """GET /api/stats — 仪表盘统计"""
    guidance = load_json(DATA_DIR / f"{GENRE}_创作指导.json") or {}
    return {
        "total_books": len(LIBRARY_DATA.get("books", [])),
        "genres": len(LIBRARY_DATA.get("genres", [])),
        "analyzed_books": guidance.get("book_count", 0),
        "analyzed_chapters": guidance.get("total_chapters", 0),
        "genre_focus": guidance.get("genre", GENRE),
        "hook_benchmark": guidance.get("worldbuilding", {}).get("opening_hook_benchmark"),
    }


def api_skeleton():
    """GET /api/skeleton — 动态生成骨架

    数据来源:
      - outline_builder.py 的 load_guidance_benchmarks / generate_rhythm_plan
      - 创作指导 JSON 提取的题材冲突类型与世界观规则
      - 预置模板填充世界观、角色、势力（因 world_builder/character_designer
        需要交互式 LLM，原型阶段用模板+真实节奏目标组合）
    """
    guidance = load_json(DATA_DIR / f"{GENRE}_创作指导.json") or {}
    wb = guidance.get("worldbuilding", {})

    total_chapters = 300
    chapter_size = 2000

    # 尝试用 outline_builder 生成真实节奏目标
    rhythm_plan = {}
    try:
        if generate_rhythm_plan:
            rhythm_plan = generate_rhythm_plan(total_chapters, GENRE) or {}
    except Exception as e:
        print("[WARN] generate_rhythm_plan failed:", e)

    opening_hook = wb.get("opening_hook_benchmark") or 2.67
    hook_rule = wb.get("rule", "")
    dominant = wb.get("dominant_conflict_types", [])
    main_conflict = dominant[0] if dominant else "生存"

    volumes = [
        {
            "title": "第一卷",
            "range": "1-60章",
            "subtitle": "灾变初临",
            "summary": "主角在高考考场遭遇末日降临，被迫在混乱中保护同学并觉醒模拟器能力。",
            "tags": ["觉醒", "逃亡", "校园"],
            "rhythm_goal": "开篇钩子密度 ≥%.2f/千字，建立世界+引入主角+核心冲突启动" % opening_hook,
        },
        {
            "title": "第二卷",
            "range": "61-120章",
            "subtitle": "废墟秩序",
            "summary": "幸存者小队在废弃商场建立据点，主角通过模拟预判危险，逐步确立领导地位。",
            "tags": ["据点", "团体", "资源"],
            "rhythm_goal": "团体生存+种田组合，每3-5章1个中爽点",
        },
        {
            "title": "第三卷",
            "range": "121-180章",
            "subtitle": "暗流涌动",
            "summary": "外界势力觊觎据点资源，内部出现分歧，主角面临信任与利益的考验。",
            "tags": ["内讧", "权谋", "冲突"],
            "rhythm_goal": "中期转折：一次重大失败加深人物厚度",
        },
        {
            "title": "第四卷",
            "range": "181-240章",
            "subtitle": "进化之路",
            "summary": "病毒二次变异，人类与怪物同步进化，主角团队被迫向更危险的城市核心进发。",
            "tags": ["进化", "副本", "Boss"],
            "rhythm_goal": "换地图/扩大舞台，终极秘密揭露准备",
        },
        {
            "title": "第五卷",
            "range": "241-300章",
            "subtitle": "新纪元",
            "summary": "真相揭露，末日竟是高等文明的筛选试验，主角必须做出拯救还是逃离的抉择。",
            "tags": ["真相", "决战", "终章"],
            "rhythm_goal": "最终决战+各角色结局+收官",
        },
    ]

    # 生成 300 章细纲，每章注入真实节奏目标
    chapter_templates = [
        ("建立末日氛围", "主角与监考老师对峙", "觉醒模拟器，逃离考场", ["考场混乱", "首次模拟", "能力觉醒"]),
        ("展示世界规则", "如何保护同学突围", "组建临时小队", ["丧尸出现", "路线选择", "救人"]),
        ("引入外部压力", "食物与信任危机", "占领小卖部作为据点", ["物资搜寻", "冲突爆发", "决策"]),
        ("模拟能力升级", "如何获取第一波物资", "建立初期资源链", ["情报收集", "模拟验证", "行动"]),
        ("第一次团战", "遭遇变异体围攻", "击退敌人但损失一名同学", ["敌袭", "战斗", "牺牲"]),
    ]
    chapters = []
    for ch in range(1, total_chapters + 1):
        tmpl = chapter_templates[(ch - 1) % len(chapter_templates)]
        targets = rhythm_plan.get(ch, {})
        chapters.append({
            "title": "第%s章" % ch,
            "goal": tmpl[0],
            "conflict": tmpl[1],
            "result": tmpl[2],
            "scenes": list(tmpl[3]),
            "rhythm": {
                "hook_target": targets.get("hook_target", 0),
                "conflict_target": targets.get("conflict_target", 0),
                "pleasure_target": targets.get("pleasure_target", 0),
                "progress_pct": targets.get("progress_pct", round(100 * ch / total_chapters, 1)),
            },
        })

    return {
        "genre": GENRE,
        "template": "三幕式",
        "mainline": "生存 → 建立据点 → 暗流冲突 → 进化探索 → 真相与决战",
        "volumes": volumes,
        "chapters": chapters,
        "world": {
            "core": "末日模拟器：主角在高考考场遭遇末日降临，觉醒能在梦中预演未来4小时的模拟器能力。随着剧情推进，真相揭露——末日是高等文明对人类的筛选试验。",
            "powers": "模拟点、天赋树、死亡惩罚、情报熵。",
            "factions": [
                {"name": "黑塔", "desc": "神秘组织，掌控轮回核心。"},
                {"name": "避难所", "desc": "官方幸存者聚集地。"},
                {"name": "拾荒者", "desc": "游离于秩序之外的幸存者。"},
                {"name": "清理人", "desc": "黑塔下属的执行部队。"},
            ],
        },
        "characters": [
            {"name": "林默", "role": "主角", "desc": "冷静果断，拥有末日模拟器，能在梦中预演未来4小时。"},
            {"name": "苏婉", "role": "女主", "desc": "医学生，擅长急救与毒理分析，团队医疗核心。"},
            {"name": "老K", "role": "导师", "desc": "退役特种兵，传授生存技巧，是主角初期的武力依靠。"},
        ],
        "benchmarks": {
            "hook_per_chars": chapter_size,
            "pleasure_per_chars": 300,
            "opening_hook_benchmark": opening_hook,
            "hook_rule": hook_rule,
            "dominant_conflicts": dominant,
            "main_conflict": main_conflict,
        },
    }


def api_rhythm_plan(params):
    """GET /api/rhythm-plan?chapters=N — 量化节奏计划
    
    基于 outline_builder.py 的 generate_rhythm_plan() 逻辑，
    从创作指导 JSON 的 pct_benchmarks 插值生成逐章节奏目标。
    """
    ch_str = params.get("chapters", ["60"])[0]
    total = int(ch_str) if ch_str else 60

    guidance = load_json(DATA_DIR / "末世_创作指导.json") or {}
    rough = guidance.get("rough_outline", {})
    pct_benchmarks = rough.get("pct_benchmarks", {})

    if not pct_benchmarks:
        # 返回默认节奏计划
        return {
            "chapters": total,
            "plan": [{"chapter": i + 1, "hook_target": 2.5, "conflict_target": 7.0, "pleasure_target": 1.0, "progress_pct": round((i + 1) / total * 100, 1)} for i in range(total)],
            "note": "使用默认基准（无创作指导数据）",
        }

    # 解析基准节点
    nodes = []
    for key, val in pct_benchmarks.items():
        try:
            pct_val = float(key.replace("%", ""))
            nodes.append((pct_val, val))
        except (ValueError, AttributeError):
            continue
    nodes.sort(key=lambda x: x[0])

    if not nodes:
        return {"chapters": total, "plan": [], "note": "无有效基准节点"}

    # 插值生成逐章计划
    plan = []
    for ch in range(1, total + 1):
        progress_pct = (ch / total) * 100
        # 找到前后节点
        prev_node = nodes[0]
        next_node = nodes[-1]
        for i in range(len(nodes)):
            if nodes[i][0] <= progress_pct:
                prev_node = nodes[i]
            if i > 0 and nodes[i - 1][0] <= progress_pct < nodes[i][0]:
                prev_node = nodes[i - 1]
                next_node = nodes[i]
                break

        # 线性插值
        if prev_node[0] == next_node[0]:
            t = 0.5
        else:
            t = (progress_pct - prev_node[0]) / (next_node[0] - prev_node[0])
        t = max(0, min(1, t))

        prev_vals = prev_node[1]
        next_vals = next_node[1]

        def interp(key, default=0):
            pv = prev_vals.get(key, default) if isinstance(prev_vals, dict) else default
            nv = next_vals.get(key, default) if isinstance(next_vals, dict) else default
            return round(pv + (nv - pv) * t, 2)

        plan.append({
            "chapter": ch,
            "hook_target": interp("hook_mean", 2.5),
            "conflict_target": interp("conflict_mean", 7.0),
            "pleasure_target": interp("pleasure_mean", 1.0),
            "progress_pct": round(progress_pct, 1),
        })

    return {"chapters": total, "plan": plan}


# ============================================================
# 任务队列（内存级，原型用）
# ============================================================

task_store = {}
task_counter = 0
task_lock = threading.Lock()


def run_analysis_task(task_id, book_files, task_type):
    """在后台线程中运行拆书分析脚本"""
    global task_store
    if not book_files:
        with task_lock:
            task_store[task_id]["status"] = "failed"
            task_store[task_id]["message"] = "未选择书籍"
        return

    stems = [Path(f).stem[:40] for f in book_files if f]
    if not stems:
        with task_lock:
            task_store[task_id]["status"] = "failed"
            task_store[task_id]["message"] = "书籍文件名无效"
        return

    # 构造命令。优先使用 rhythm_analyzer（纯规则，无需 LLM，出结果快）
    cmd = [
        sys.executable,
        "-m",
        "xiaoshuo.pipeline.rhythm_analyzer",
        "--genre",
        GENRE,
        "--books",
        ",".join(stems),
    ]

    with task_lock:
        task_store[task_id]["status"] = "running"
        task_store[task_id]["message"] = "启动分析进程..."
        task_store[task_id]["command"] = " ".join(cmd)

    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src") + os.pathsep + env.get("PYTHONPATH", "")

    try:
        proc = subprocess.Popen(
            cmd,
            cwd=str(ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
        )
        lines = []
        total = len(stems)
        finished = 0
        for line in proc.stdout:
            line = line.rstrip()
            lines.append(line)
            # 通过 rhythm_analyzer 的输出估算进度
            if "DONE" in line or "[OK]" in line:
                finished += 1
                progress = min(95, int(100 * finished / max(1, total)))
                with task_lock:
                    task_store[task_id]["progress"] = progress
                    task_store[task_id]["message"] = line[:120]
            if len(lines) > 200:
                lines = lines[-100:]

        proc.wait(timeout=600)
        with task_lock:
            if proc.returncode == 0:
                task_store[task_id]["status"] = "completed"
                task_store[task_id]["progress"] = 100
                task_store[task_id]["message"] = "分析完成"
            else:
                task_store[task_id]["status"] = "failed"
                task_store[task_id]["message"] = "分析进程退出码 %d" % proc.returncode
            task_store[task_id]["output"] = "\n".join(lines)
    except subprocess.TimeoutExpired:
        proc.kill()
        with task_lock:
            task_store[task_id]["status"] = "failed"
            task_store[task_id]["message"] = "分析超时（超过 10 分钟）"
    except Exception as e:
        with task_lock:
            task_store[task_id]["status"] = "failed"
            task_store[task_id]["message"] = str(e)


def api_create_task(params):
    global task_counter
    book_files = params.get("books", [])
    task_type = params.get("type", "rhythm")
    with task_lock:
        task_counter += 1
        task_id = task_counter
        task_store[task_id] = {
            "id": task_id,
            "type": task_type,
            "books": book_files,
            "status": "pending",
            "progress": 0,
            "message": "等待启动...",
            "created_at": time.time(),
            "output": "",
        }
    thread = threading.Thread(
        target=run_analysis_task,
        args=(task_id, book_files, task_type),
        daemon=True,
    )
    thread.start()
    return {"id": task_id, "status": "pending"}


def api_list_tasks(params):
    with task_lock:
        return {"tasks": list(task_store.values())}


def api_get_task(params):
    task_id = int(params.get("id", [0])[0])
    with task_lock:
        task = task_store.get(task_id)
    if not task:
        return {"error": "任务不存在"}, 404
    return task


def api_config(params=None):
    """GET /api/config — 返回前端需要的配置子集"""
    cfg = load_config()
    # 读取 config.yaml 中的模型配置
    llm_cfg = {}
    try:
        with open(ROOT / "config.yaml", "r", encoding="utf-8") as f:
            full_cfg = yaml.safe_load(f) or {}
        llm_cfg = full_cfg.get("llm", {})
    except Exception:
        pass
    main_model = llm_cfg.get("models", {}).get("main_model", {})
    providers = llm_cfg.get("providers", {})
    active_cloud = None
    for name, p in providers.items():
        if p.get("enabled"):
            active_cloud = {"provider": name, "model": p.get("model"), "base_url": p.get("base_url")}
            break
    return {
        "port": cfg.get("port"),
        "genre": cfg.get("genre"),
        "data_dir": cfg.get("data_dir"),
        "local_model": main_model.get("name", "Qwen3.5-9B-Instruct"),
        "cloud_model": active_cloud["model"] if active_cloud else "未启用",
        "cloud_provider": active_cloud["provider"] if active_cloud else None,
        "theme_presets": cfg.get("theme_presets", []),
    }


# ============================================================
# 硬件监控 API
# ============================================================

def _read_gpu_smi():
    """通过 nvidia-smi 读取 GPU 温度和显存 (pynvml 降级方案)。"""
    try:
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=temperature.gpu,memory.used,memory.total,utilization.gpu",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5,
        )
        if r.returncode == 0 and r.stdout.strip():
            parts = [p.strip() for p in r.stdout.strip().split(",")]
            return {
                "temp": int(parts[0]) if len(parts) > 0 else None,
                "vram_used_mb": int(parts[1]) if len(parts) > 1 else None,
                "vram_total_mb": int(parts[2]) if len(parts) > 2 else None,
                "gpu_util": int(parts[3]) if len(parts) > 3 else None,
            }
    except Exception:
        pass
    return None


def api_hardware(params=None):
    """GET /api/hardware — 实时硬件状态"""
    result = {
        "gpu": {"available": False, "temp": None, "vram_used": None, "vram_total": None, "vram_pct": None, "util": None},
        "cpu": {"pct": None},
        "ram": {"used": None, "total": None, "pct": None},
    }

    # GPU
    gpu = _read_gpu_smi()
    if gpu and gpu.get("temp") is not None:
        result["gpu"] = {
            "available": True,
            "temp": gpu["temp"],
            "vram_used": gpu.get("vram_used_mb"),
            "vram_total": gpu.get("vram_total_mb"),
            "vram_pct": round(gpu["vram_used_mb"] / gpu["vram_total_mb"] * 100, 1) if gpu.get("vram_used_mb") and gpu.get("vram_total_mb") else None,
            "util": gpu.get("gpu_util"),
        }

    # CPU
    result["cpu"]["pct"] = round(psutil.cpu_percent(interval=0.1), 1)

    # RAM
    mem = psutil.virtual_memory()
    result["ram"] = {
        "used": round(mem.used / (1024**3), 1),
        "total": round(mem.total / (1024**3), 1),
        "pct": mem.percent,
    }

    return result


# ============================================================
# 拆书数据 API
# ============================================================

def _list_rhythm_csvs():
    """扫描所有题材的 rhythm CSV 文件，返回 {book_key: csv_path}。"""
    rhythm_dir = ROOT / "data" / "processed"
    books = {}
    if not rhythm_dir.exists():
        return books
    for csv_path in rhythm_dir.rglob("rhythm_*.csv"):
        genre = csv_path.parent.parent.name if csv_path.parent.parent.parent == rhythm_dir else "unknown"
        key = csv_path.stem.replace("rhythm_", "")
        books[key] = {"path": csv_path, "genre": genre}
    return books


def _read_rhythm_summary(csv_path):
    """读取 rhythm CSV 的摘要统计。"""
    import csv as csv_mod
    try:
        with open(csv_path, "r", encoding="utf-8-sig") as f:
            reader = csv_mod.DictReader(f)
            rows = list(reader)
    except Exception:
        return None

    if not rows:
        return None

    ch_count = len(rows)
    total_wc = sum(int(r.get("wc", 0) or 0) for r in rows)
    emotions = {}
    paces = {}
    conflict_levels = {}
    pleasure_types = {}

    for r in rows:
        e = r.get("emotion", "")
        if e: emotions[e] = emotions.get(e, 0) + 1
        p = r.get("pace", "")
        if p: paces[p] = paces.get(p, 0) + 1
        c = r.get("conflict_level", "")
        if c: conflict_levels[c] = conflict_levels.get(c, 0) + 1
        pt = r.get("pleasure_type", "none")
        if pt: pleasure_types[pt] = pleasure_types.get(pt, 0) + 1

    return {
        "chapters": ch_count,
        "total_words": total_wc,
        "avg_words": round(total_wc / ch_count) if ch_count else 0,
        "emotion_dist": emotions,
        "pace_dist": paces,
        "conflict_dist": conflict_levels,
        "pleasure_dist": pleasure_types,
    }


def api_disassembly_books(params=None):
    """GET /api/disassembly/books — 列出所有有拆书数据的书"""
    books = _list_rhythm_csvs()
    result = []
    for key, info in sorted(books.items()):
        summary = _read_rhythm_summary(info["path"])
        entry = {
            "key": key,
            "genre": info["genre"],
            "file": info["path"].name,
        }
        if summary:
            entry["summary"] = summary
        result.append(entry)
    return {"total": len(result), "books": result}


def api_disassembly_book(params):
    """GET /api/disassembly/book?name=X — 获取某本书的逐章拆书数据"""
    import csv as csv_mod
    name = (params or {}).get("name", [None])[0]
    if not name:
        return {"error": "Missing name parameter"}

    books = _list_rhythm_csvs()
    if name not in books:
        return {"error": "Book not found", "name": name}

    csv_path = books[name]["path"]
    try:
        with open(csv_path, "r", encoding="utf-8-sig") as f:
            reader = csv_mod.DictReader(f)
            chapters = []
            for row in reader:
                chapters.append({
                    "ch": int(row.get("ch_num", 0)),
                    "wc": int(row.get("wc", 0) or 0),
                    "emotion": row.get("emotion", ""),
                    "pace": row.get("pace", ""),
                    "conflict": row.get("conflict", ""),
                    "conflict_level": row.get("conflict_level", ""),
                    "pleasure_type": row.get("pleasure_type", "none"),
                    "pleasure_intensity": float(row.get("pleasure_intensity", 0) or 0),
                    "dominant_sub": row.get("dominant_sub", ""),
                    "dialogue_ratio": float(row.get("dialogue_ratio", 0) or 0),
                    "pos_density": float(row.get("pos_density", 0) or 0),
                    "hook_density": float(row.get("hook_density", 0) or 0),
                    "readability": float(row.get("readability", 0) or 0),
                })
            summary = _read_rhythm_summary(csv_path)
            return {"name": name, "genre": books[name]["genre"], "total_chapters": len(chapters), "summary": summary, "chapters": chapters}
    except Exception as e:
        return {"error": str(e), "name": name}


# ── 日志查询 API ──

def _list_log_files(category: str):
    """列出指定类别下所有日志文件，返回 [(date_str, path), ...] 按日期倒序"""
    dir_map = {
        "access": ACCESS_LOG_DIR,
        "operation": OP_LOG_DIR,
    }
    log_dir = dir_map.get(category, LOG_DIR)
    if not log_dir.exists():
        return []
    files = []
    for f in sorted(log_dir.glob("*.jsonl"), reverse=True):
        date_str = f.stem  # "2026-06-27"
        files.append((date_str, f))
    return files


def _read_log_entries(category: str, date_str: str = None,
                      search: str = None, level: str = None,
                      offset: int = 0, limit: int = 50):
    """读取日志条目，支持筛选和分页"""
    entries = []
    if date_str:
        dir_map = {"access": ACCESS_LOG_DIR, "operation": OP_LOG_DIR}
        log_dir = dir_map.get(category, LOG_DIR)
        log_path = log_dir / f"{date_str}.jsonl"
        paths = [log_path] if log_path.exists() else []
    else:
        # 默认读取最近 7 天
        paths = []
        for date_s, path in _list_log_files(category)[:7]:
            paths.append(path)

    for path in paths:
        if not path.exists():
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    entries.append(entry)
        except Exception:
            continue

    # 排序（时间倒序）
    entries.sort(key=lambda e: e.get("timestamp", ""), reverse=True)

    # 搜索过滤
    if search:
        search_lower = search.lower()
        entries = [
            e for e in entries
            if search_lower in json.dumps(e, ensure_ascii=False).lower()
        ]

    # 等级过滤（access 日志中 status>=400 为 ERROR）
    if level:
        if level == "ERROR":
            entries = [e for e in entries if e.get("status", 200) >= 400]
        elif level == "WARNING":
            entries = [e for e in entries if 300 <= e.get("status", 200) < 400]

    total = len(entries)
    page = entries[offset:offset + limit]
    return {"total": total, "offset": offset, "limit": limit, "entries": page}


def api_logs(params):
    """GET /api/logs — 查询日志"""
    category = (params or {}).get("category", ["access"])[0]
    date_str = (params or {}).get("date", [None])[0]
    search = (params or {}).get("search", [None])[0]
    level = (params or {}).get("level", [None])[0]
    try:
        offset = int((params or {}).get("offset", ["0"])[0])
    except ValueError:
        offset = 0
    try:
        limit = int((params or {}).get("limit", ["50"])[0])
    except ValueError:
        limit = 50

    return _read_log_entries(category, date_str, search, level, offset, limit)


def api_log_dates(params=None):
    """GET /api/logs/dates — 列出有日志的日期"""
    result = {"access": [], "operation": []}
    for cat in ["access", "operation"]:
        result[cat] = [d for d, _ in _list_log_files(cat)]
    return result


def api_logs_operation(body):
    """POST /api/logs/operations — 前端上报用户操作"""
    action = body.get("action", "")
    detail = body.get("detail", {})
    log_operation(action, detail)
    return {"status": "ok"}


# ============================================================
# HTTP 请求处理器
# ============================================================

API_ROUTES = {
    "/api/books": api_books,
    "/api/config": api_config,
    "/api/guidance": api_guidance,
    "/api/techniques": api_techniques,
    "/api/instructions": api_instructions,
    "/api/diagnosis": api_diagnosis,
    "/api/stats": api_stats,
    "/api/skeleton": api_skeleton,
    "/api/rhythm-plan": api_rhythm_plan,
    "/api/tasks": api_list_tasks,
    "/api/task": api_get_task,
    "/api/hardware": api_hardware,
    "/api/disassembly/books": api_disassembly_books,
    "/api/disassembly/book": api_disassembly_book,
    "/api/logs": api_logs,
    "/api/logs/dates": api_log_dates,
}

API_POST_ROUTES = {
    "/api/tasks": api_create_task,
    "/api/logs/operations": api_logs_operation,
}

MIME_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
}


class APIHandler(http.server.SimpleHTTPRequestHandler):
    """自定义请求处理器：API 路由 + 静态文件"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(PROTO_DIR), **kwargs)

    def log_message(self, format, *args):
        """简化日志输出"""
        sys.stdout.write("[%s] %s\n" % (self.address_string(), format % args))

    def send_json(self, data, status=200):
        """发送 JSON 响应（客户端断开时静默忽略）"""
        body = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", len(body))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(body)
        except (ConnectionAbortedError, BrokenPipeError, ConnectionResetError):
            pass  # 客户端已断开，无法发送响应，静默忽略

    def do_GET(self):
        t0 = time.perf_counter()
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        params = parse_qs(parsed.query)

        # ── 静态文件：不记录日志 ──
        if path not in API_ROUTES:
            super().do_GET()
            return

        # API 路由
        handler = API_ROUTES[path]
        status = 200
        try:
            if handler in (api_instructions, api_rhythm_plan, api_get_task, api_disassembly_book, api_hardware, api_logs):
                result = handler(params)
            else:
                result = handler()
            self.send_json(result)
        except (ConnectionAbortedError, BrokenPipeError, ConnectionResetError):
            status = 499  # client closed request
            pass
        except Exception as e:
            status = 500
            self.send_json({"error": str(e)}, 500)
        finally:
            duration = (time.perf_counter() - t0) * 1000
            log_access(self, "GET", path, params, status, duration)

    def do_POST(self):
        t0 = time.perf_counter()
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"

        # 读取请求体
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length).decode("utf-8") if content_length else "{}"
        try:
            json_body = json.loads(body) if body else {}
        except Exception:
            json_body = {}

        status = 200
        if path in API_POST_ROUTES:
            try:
                result = API_POST_ROUTES[path](json_body)
                if isinstance(result, tuple):
                    self.send_json(result[0], result[1])
                else:
                    self.send_json(result)
            except (ConnectionAbortedError, BrokenPipeError, ConnectionResetError):
                status = 499
                pass
            except Exception as e:
                status = 500
                self.send_json({"error": str(e)}, 500)
            finally:
                duration = (time.perf_counter() - t0) * 1000
                log_access(self, "POST", path, {}, status, duration, req_body=json_body)
            return

        self.send_json({"error": "Method not allowed"}, 405)

    def do_OPTIONS(self):
        """CORS 预检"""
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def end_headers(self):
        """静态文件禁用缓存，避免前端样式/脚本更新后浏览器仍使用旧版本"""
        parsed = urlparse(self.path)
        if not parsed.path.startswith("/api/"):
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        super().end_headers()


def main():
    port = CONFIG["port"]
    server = http.server.HTTPServer(("127.0.0.1", port), APIHandler)
    url = "http://localhost:%d" % port
    print("[OK] 原型服务器启动: %s" % url)
    print("[OK] 按 Ctrl+C 停止")
    if CONFIG.get("auto_open_browser"):
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[OK] 服务器已停止")
        server.shutdown()


if __name__ == "__main__":
    main()
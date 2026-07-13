#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""cleanup_project.py — 项目清理脚本

将过时的脚本和文件归档到 _archive/ 目录，不直接删除。
"""
import sys, os, shutil
from pathlib import Path
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')

PROJECT_ROOT = Path(__file__).parent.parent
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
ARCHIVE_DIR = SCRIPTS_DIR / "_archive"

# ============================================================
# 1. scripts/ 目录清理
# ============================================================

# 核心脚本 — 保留在 scripts/ 根目录
KEEP_SCRIPTS = {
    # Tier1/Tier2 核心管线
    "ai_annotate.py",           # Tier1 标注核心
    "gen_tier2_sampling.py",    # Tier2 采样
    "gen_trae_tier2_prompt.py", # Tier2 Trae指令生成
    "quality_check.py",         # Tier1 质检
    "quality_check_tier2.py",   # Tier2 质检
    "merge_all_books.py",       # 合并评分
    "convert_ai_to_llm.py",     # 转换格式
    "recompute_borda.py",       # Borda排名
    "save_borda_snapshot.py",   # Borda快照
    "three_tier_eval.py",       # 三层评估
    "tier1_progress.py",        # 进度跟踪
    "fix_novel_index.py",       # 修复索引
    "check_novel_index.py",     # 检查索引
    "loocv_calibrate.py",       # LOOCV校准
    "gen_final_report.py",      # 生成报告
    "dump_commercial.py",       # 商业评分dump
    # 工具脚本
    "start_model_safe.bat",     # LLM启动
    "start_api_server.bat",     # API服务启动
    "start_app.bat",            # 应用启动
    "lint.bat",                 # 代码检查
    "progress_server.py",       # 进度服务器
    "progress_server.bat",      # 进度服务器启动
    "smoke_test_frontend.py",   # 前端冒烟测试
    "cleanup_project.py",       # 本清理脚本
    "verify_tier2_prompt.py",   # Tier2指令验证
}

# 归档目录和文件
ARCHIVE_DIRS = {
    "adhoc": "早期adhoc脚本(已过时)",
    "novel-ranking": "旧排名HTML(已被data/reports取代)",
    "quality-tier-review": "旧质量分级审查HTML(v8.7已过时)",
    "ranking-validation-review": "旧排名验证HTML(已被v8.8取代)",
    "scoring-system-review": "旧评分系统审查HTML(已过时)",
    "v22-sampling-review": "v22采样审查(已被v8.8取代)",
}

# 根目录归档文件
ARCHIVE_ROOT_FILES = {
    "apocalypse_books_ranking_validation.md": "旧排名验证文档(已被v8.8取代)",
    "NEW_SESSION_HANDOFF.md": "旧交接文档(已完成交接)",
    "novel.py": "根目录遗留脚本",
    "建议": "模糊命名文件",
}

def main():
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    
    moved_count = 0
    skipped_count = 0
    
    print("=" * 80)
    print("项目清理 — 归档过时文件")
    print("=" * 80)
    
    # ── 1. scripts/ 目录清理 ──
    print("\n--- scripts/ 目录清理 ---")
    
    for item in sorted(SCRIPTS_DIR.iterdir()):
        if item.name.startswith("_") or item.name.startswith("."):
            continue
        if item.name in KEEP_SCRIPTS:
            continue
        if item.is_dir():
            # __pycache__ 直接删除
            if item.name == "__pycache__":
                shutil.rmtree(item)
                print(f"  🗑️ 删除: {item.name}/")
                continue
            # 其他目录保留
            continue
        
        # 归档文件
        dest = ARCHIVE_DIR / item.name
        if dest.exists():
            skipped_count += 1
            continue
        shutil.move(str(item), str(dest))
        moved_count += 1
        print(f"  📦 归档: {item.name}")
    
    # ── 2. 根目录审查目录归档 ──
    print("\n--- 根目录审查目录归档 ---")
    root_archive = PROJECT_ROOT / "_archive"
    root_archive.mkdir(parents=True, exist_ok=True)
    
    for dirname, reason in ARCHIVE_DIRS.items():
        src = PROJECT_ROOT / dirname
        if not src.exists():
            continue
        dest = root_archive / dirname
        if dest.exists():
            print(f"  ⏭️ 已存在: {dirname}/")
            skipped_count += 1
            continue
        shutil.move(str(src), str(dest))
        moved_count += 1
        print(f"  📦 归档: {dirname}/ ({reason})")
    
    # ── 3. 根目录文件归档 ──
    print("\n--- 根目录文件归档 ---")
    for filename, reason in ARCHIVE_ROOT_FILES.items():
        src = PROJECT_ROOT / filename
        if not src.exists():
            continue
        dest = root_archive / filename
        if dest.exists():
            print(f"  ⏭️ 已存在: {filename}")
            skipped_count += 1
            continue
        shutil.move(str(src), str(dest))
        moved_count += 1
        print(f"  📦 归档: {filename} ({reason})")
    
    # ── 4. trae_tier1/ 旧指令归档 ──
    print("\n--- trae_tier1/ 旧指令归档 ---")
    trae_archive = PROJECT_ROOT / "trae_tier1" / "_archive"
    trae_archive.mkdir(parents=True, exist_ok=True)
    
    OLD_PROMPTS = {
        "PROMPT_GLM_UNFINISHED.md": "旧GLM指令(Tier1已完成)",
        "PROMPT_1_DeepSeek.md": "旧三方AI审视指令(已完成)",
        "PROMPT_2_Kimi.md": "旧三方AI审视指令(已完成)",
        "PROMPT_3_GLM.md": "旧三方AI审视指令(已完成)",
        "PROMPT_4_Doubao.md": "旧三方AI审视指令(已完成)",
        "PROGRESS_OVERVIEW.md": "旧进度概览(已过时)",
    }
    
    for filename, reason in OLD_PROMPTS.items():
        src = PROJECT_ROOT / "trae_tier1" / filename
        if not src.exists():
            continue
        dest = trae_archive / filename
        if dest.exists():
            print(f"  ⏭️ 已存在: {filename}")
            skipped_count += 1
            continue
        shutil.move(str(src), str(dest))
        moved_count += 1
        print(f"  📦 归档: trae_tier1/{filename} ({reason})")
    
    # ── 5. 清理 __pycache__ ──
    print("\n--- 清理 __pycache__ ---")
    pycache_count = 0
    for p in PROJECT_ROOT.rglob("__pycache__"):
        if "_archive" in str(p) or ".git" in str(p):
            continue
        shutil.rmtree(p, ignore_errors=True)
        pycache_count += 1
    if pycache_count:
        print(f"  🗑️ 删除 {pycache_count} 个 __pycache__ 目录")
    
    # ── 6. 清理 prototype/screenshots ──
    print("\n--- prototype/screenshots 清理 ---")
    screenshots_dir = PROJECT_ROOT / "prototype" / "screenshots"
    if screenshots_dir.exists():
        review_tmp = screenshots_dir / "review_tmp"
        if review_tmp.exists():
            shutil.rmtree(review_tmp)
            print(f"  🗑️ 删除: prototype/screenshots/review_tmp/")
    
    # ── 汇总 ──
    print(f"\n{'='*80}")
    print(f"清理完成: 归档 {moved_count} 项, 跳过 {skipped_count} 项")
    print(f"归档目录: scripts/_archive/, _archive/, trae_tier1/_archive/")
    
    # ── 列出保留的核心脚本 ──
    print(f"\n保留的核心脚本 ({len(KEEP_SCRIPTS)}个):")
    for s in sorted(KEEP_SCRIPTS):
        p = SCRIPTS_DIR / s
        if p.exists():
            print(f"  ✅ {s}")

if __name__ == "__main__":
    main()

#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""tier1_batch_run.py — Tier 1 全自动批量评分 (DeepSeek API)

解决方案: 不依赖CatPaw对话, 在终端后台独立运行, 逐本逐批调用DeepSeek API评分。
- 自动读取 secrets.yaml 中的 DeepSeek API key
- 按剩余章节数升序处理 (最短的书先跑完, 快速积累完成数)
- 内置断点续传 (ai_annotate.py 已有跳过已评分批次的机制)
- 全程日志记录到 logs/tier1_batch_run.log
- 可随时 Ctrl+C 中断, 重新运行即续传

用法:
  # 后台运行 (推荐)
  D:\\miniconda3\\envs\\llm-shared\\python.exe scripts/tier1_batch_run.py

  # 指定只跑某本书
  D:\\miniconda3\\envs\\llm-shared\\python.exe scripts/tier1_batch_run.py --book 废土崛起

  # 指定每次最多跑N批 (调试用)
  D:\\miniconda3\\envs\\llm-shared\\python.exe scripts/tier1_batch_run.py --max-batches 5

  # 查看进度 (不执行评分)
  D:\\miniconda3\\envs\\llm-shared\\python.exe scripts/tier1_batch_run.py --dry-run
"""
import sys
import os
import json
import time
import argparse
import traceback
from pathlib import Path
from datetime import datetime

# 项目路径
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')

# 导入 ai_annotate 模块
import ai_annotate as aa

# ============================================================
# 日志
# ============================================================
LOG_DIR = PROJECT_ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True)
LOG_FILE = LOG_DIR / "tier1_batch_run.log"

def log(msg: str, level: str = "INFO"):
    """同时输出到控制台和日志文件。"""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] [{level}] {msg}"
    print(line, flush=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")

# ============================================================
# 读取 DeepSeek API key
# ============================================================
def load_api_key() -> str:
    """从 secrets.yaml 读取 DeepSeek API key。"""
    import yaml
    secrets_path = PROJECT_ROOT / "secrets.yaml"
    if not secrets_path.exists():
        log("secrets.yaml 不存在!", "ERROR")
        sys.exit(1)
    with open(secrets_path, "r", encoding="utf-8") as f:
        secrets = yaml.safe_load(f)
    key = secrets.get("deepseek", {}).get("api_key", "")
    if not key or key == "sk-PLACEHOLDER":
        log("DeepSeek API key 未配置!", "ERROR")
        sys.exit(1)
    return key

# ============================================================
# 获取书籍剩余工作量
# ============================================================
def get_book_progress(book_name: str) -> dict:
    """获取单本书的评分进度。"""
    chapters = aa.extract_chapters(str(aa.RAW_DIR / aa.BOOKS[book_name]))
    sampled = aa.stratified_sample(chapters, sample_rate=aa.SAMPLE_RATE)
    total_sampled = len(sampled)

    batch_dir = aa.get_book_batch_dir(book_name)
    score_files = list(batch_dir.glob("scores_*.json")) if batch_dir.exists() else []
    scored_count = 0
    for sf in score_files:
        try:
            with open(sf, "r", encoding="utf-8") as f:
                scored_count += len(json.load(f))
        except (json.JSONDecodeError, IOError):
            pass

    return {
        "book": book_name,
        "total_chapters": len(chapters),
        "sampled": total_sampled,
        "scored": scored_count,
        "remaining": total_sampled - scored_count,
        "progress": scored_count / total_sampled * 100 if total_sampled > 0 else 0,
    }

def get_all_books_progress() -> list:
    """获取所有书籍的进度, 按剩余章节数升序排列。"""
    results = []
    for book_name in aa.BOOKS:
        txt_path = aa.RAW_DIR / aa.BOOKS[book_name]
        if not txt_path.exists():
            continue
        try:
            info = get_book_progress(book_name)
            results.append(info)
        except Exception as e:
            log(f"获取 {book_name} 进度失败: {e}", "WARN")
    # 按剩余章节数升序 (最少的先跑完)
    results.sort(key=lambda x: x["remaining"])
    return results

# ============================================================
# 主流程
# ============================================================
def run_tier1_batch(api_key: str, book_filter: str = "", 
                    max_batches_per_book: int = 0, dry_run: bool = False,
                    batch_size: int = 2, delay_seconds: float = 0.5):
    """逐本调用 DeepSeek API 进行 Tier 1 评分。"""
    
    API_BASE = "https://api.deepseek.com/v1"
    API_MODEL = "deepseek-chat"
    
    log("=" * 60)
    log("Tier 1 全自动批量评分 (DeepSeek API)")
    log("=" * 60)
    log(f"API: {API_BASE} | model: {API_MODEL}")
    log(f"batch_size: {batch_size} | delay: {delay_seconds}s")
    if max_batches_per_book > 0:
        log(f"每本书最多跑 {max_batches_per_book} 批 (调试模式)")
    log("")
    
    # 获取进度
    all_progress = get_all_books_progress()
    
    total_remaining = sum(p["remaining"] for p in all_progress)
    total_scored = sum(p["scored"] for p in all_progress)
    total_sampled = sum(p["sampled"] for p in all_progress)
    
    log(f"总进度: {total_scored}/{total_sampled} 章 ({total_scored/total_sampled*100:.1f}%)")
    log(f"剩余: {total_remaining} 章")
    log("")
    
    if dry_run:
        log("[DRY RUN] 只展示进度, 不执行评分:")
        for p in all_progress:
            status = "✓完成" if p["remaining"] == 0 else f"待评分 {p['remaining']}章"
            log(f"  {p['book']}: {p['scored']}/{p['sampled']} ({p['progress']:.0f}%) {status}")
        return
    
    # 过滤书籍
    books_to_run = []
    for p in all_progress:
        if p["remaining"] == 0:
            log(f"  {p['book']}: ✓已完成, 跳过")
            continue
        if book_filter and p["book"] != book_filter:
            continue
        books_to_run.append(p)
    
    if not books_to_run:
        log("所有书籍评分已完成!")
        return
    
    log(f"待处理书籍: {len(books_to_run)} 本")
    log("")
    
    # 逐本评分
    overall_start = time.time()
    book_count = 0
    total_new_scored = 0
    
    for p in books_to_run:
        book_name = p["book"]
        book_count += 1
        
        log("-" * 60)
        log(f"[{book_count}/{len(books_to_run)}] {book_name}")
        log(f"  进度: {p['scored']}/{p['sampled']} ({p['progress']:.0f}%), 剩余 {p['remaining']} 章")
        log("-" * 60)
        
        book_start = time.time()
        try:
            new_scored = aa.score_book(
                book_name=book_name,
                api_base=API_BASE,
                api_key=api_key,
                api_model=API_MODEL,
                batch_size=batch_size,
                max_chapters=0,
                dry_run=False,
                max_batches=max_batches_per_book,
                chapter_list_csv="",
                tier2_mode=False,
            )
            total_new_scored += new_scored
            book_elapsed = time.time() - book_start
            log(f"  {book_name} 完成: 新评分 {new_scored} 章, 耗时 {book_elapsed:.0f}s")
        except Exception as e:
            log(f"  {book_name} 评分失败: {e}", "ERROR")
            log(traceback.format_exc(), "ERROR")
        
        # 书间延迟
        if book_count < len(books_to_run):
            time.sleep(delay_seconds)
    
    # 汇总
    overall_elapsed = time.time() - overall_start
    log("")
    log("=" * 60)
    log(f"批量评分完成!")
    log(f"  处理书籍: {book_count} 本")
    log(f"  新评分: {total_new_scored} 章")
    log(f"  总耗时: {overall_elapsed:.0f}s ({overall_elapsed/60:.1f}min)")
    log("=" * 60)
    
    # 最终进度
    final_progress = get_all_books_progress()
    final_scored = sum(p["scored"] for p in final_progress)
    final_sampled = sum(p["sampled"] for p in final_progress)
    log(f"最终进度: {final_scored}/{final_sampled} ({final_scored/final_sampled*100:.1f}%)")
    
    remaining_books = [p for p in final_progress if p["remaining"] > 0]
    if remaining_books:
        log(f"仍有 {len(remaining_books)} 本书未完成, 重新运行此脚本继续:")
        log(f"  D:\\miniconda3\\envs\\llm-shared\\python.exe scripts/tier1_batch_run.py")
    else:
        log("所有书籍 Tier 1 评分全部完成! 下一步: --merge 合并CSV")


def main():
    parser = argparse.ArgumentParser(description="Tier 1 全自动批量评分 (DeepSeek API)")
    parser.add_argument("--book", type=str, default="", help="只评分指定书籍")
    parser.add_argument("--max-batches", type=int, default=0, 
                        help="每本书最多跑N批 (0=不限制)")
    parser.add_argument("--batch-size", type=int, default=2,
                        help="每批章节数 (默认2, 防上下文过载)")
    parser.add_argument("--delay", type=float, default=0.5,
                        help="API调用间隔秒数 (默认0.5)")
    parser.add_argument("--dry-run", action="store_true", help="只查看进度不执行")
    args = parser.parse_args()
    
    api_key = load_api_key()
    run_tier1_batch(
        api_key=api_key,
        book_filter=args.book,
        max_batches_per_book=args.max_batches,
        dry_run=args.dry_run,
        batch_size=args.batch_size,
        delay_seconds=args.delay,
    )


if __name__ == "__main__":
    main()

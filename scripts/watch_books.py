#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
watch_books.py — 书籍入口自动监测 v1
=====================================
监测 books/in/ 目录，发现新 .txt 文件时自动触分析管线。

用法: python scripts/watch_books.py [--once] [--interval 30]
      --once: 只检查一次就退出
      --interval N: 每N秒检查一次 (默认30)
"""
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BOOKS_IN = ROOT / "books" / "in"
ANALYSIS_DIR = ROOT / "analysis"
PROCESSED_FILE = ROOT / "data" / "processed" / "watched_files.txt"


def load_processed():
    if not PROCESSED_FILE.exists():
        return set()
    return set(PROCESSED_FILE.read_text(encoding='utf-8').strip().split('\n'))


def save_processed(names):
    PROCESSED_FILE.parent.mkdir(parents=True, exist_ok=True)
    PROCESSED_FILE.write_text('\n'.join(sorted(names)), encoding='utf-8')


def run_pipeline(genre="末世"):
    print(f"\n[WATCH] Running analyze_all.py --genre {genre}")
    result = subprocess.run(
        [sys.executable, str(ANALYSIS_DIR / "analyze_all.py"), "--genre", genre],
        cwd=str(ROOT), timeout=3600
    )
    return result.returncode == 0


def main():
    once = "--once" in sys.argv
    interval = 30
    genre = "末世"
    for arg in sys.argv[1:]:
        if arg.startswith("--interval="):
            interval = int(arg.split("=")[1])
        elif arg.startswith("--genre="):
            genre = arg.split("=")[1]

    print(f"[WATCH] Monitoring {BOOKS_IN} every {interval}s (genre={genre})")
    print(f"[WATCH] Processed files tracked in {PROCESSED_FILE}")
    print(f"[WATCH] Press Ctrl+C to stop\n")

    while True:
        processed = load_processed()
        txt_files = set(f.name for f in BOOKS_IN.glob("*.txt"))

        if not txt_files:
            if once:
                print("[WATCH] No files found.")
                return
        else:
            new_files = txt_files - processed
            if new_files:
                print(f"\n[WATCH] New files detected: {', '.join(new_files)[:80]}")
                if run_pipeline(genre=genre):
                    save_processed(processed | txt_files)
                    print(f"[WATCH] Pipeline complete. Tracking {len(processed | txt_files)} files.")
                else:
                    print("[WATCH] Pipeline failed — will retry next check.")
            elif not once:
                pass  # silent check

        if once:
            break
        time.sleep(interval)


if __name__ == "__main__":
    main()

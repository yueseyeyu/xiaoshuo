# -*- coding: utf-8 -*-
"""routes/books.py — 书库/拆书/分析启停 路由。"""

from __future__ import annotations

import csv
import logging
import os
import subprocess
import sys
import time

from fastapi import APIRouter, HTTPException, Query

from xiaoshuo import PROJECT_ROOT
from xiaoshuo.infra.pipeline_state import clear_stage
from xiaoshuo.api.app_state import app_state
from xiaoshuo.api.utils import get_available_books, get_genre_counts
from xiaoshuo.api.shared import safe_write_json

router = APIRouter()


@router.get("/api/books")
async def get_books(genre: str = Query("")):
    genres, counts = get_genre_counts(PROJECT_ROOT)
    if genre and genre != "全部":
        books = get_available_books(PROJECT_ROOT, genre)
    else:
        books = []
        for g in genres:
            books.extend(get_available_books(PROJECT_ROOT, g))
    return {
        "books": books,
        "count": len(books),
        "genre": genre or "全部",
        "genres": genres,
        "counts": counts,
    }


@router.get("/api/disassembly/books")
async def disassembly_books(genre: str = Query("")):
    genres, _ = get_genre_counts(PROJECT_ROOT)
    if genre and genre != "全部":
        target_genres = [genre]
    else:
        target_genres = genres
    result = []
    for g in target_genres:
        books = get_available_books(PROJECT_ROOT, g)
        for b in books:
            if b.get("status") != "analyzed":
                continue
            stem = b.get("stem", b["file"].replace("rhythm_", "").replace(".csv", ""))
            csv_path = PROJECT_ROOT / "data" / "processed" / g / "rhythm" / b["file"]
            chapters = 0
            total_words = 0
            pace_dist = {}
            emotion_dist = {}
            conflict_dist = {}
            pleasure_dist = {}
            if csv_path.exists():
                try:
                    with open(csv_path, encoding="utf-8-sig") as f:
                        for r in csv.DictReader(f):
                            chapters += 1
                            wc = r.get("wc") or r.get("word_count") or "0"
                            try:
                                total_words += int(wc)
                            except ValueError:
                                pass
                            pace = (r.get("pace") or "").strip()
                            if pace:
                                pace_dist[pace] = pace_dist.get(pace, 0) + 1
                            emotion = (r.get("emotion") or "").strip()
                            if emotion:
                                emotion_dist[emotion] = emotion_dist.get(emotion, 0) + 1
                            conflict = (r.get("conflict") or "").strip().lower()
                            ck = "conflict" if conflict in ("true", "1") else "none"
                            conflict_dist[ck] = conflict_dist.get(ck, 0) + 1
                            pleasure = (r.get("pleasure_type") or "none").strip()
                            pleasure_dist[pleasure] = pleasure_dist.get(pleasure, 0) + 1
                except Exception:
                    pass
            result.append({
                "key": stem,
                "title": b["title"],
                "genre": b["genre"],
                "author": b.get("author", ""),
                "tags": b.get("tags", []),
                "summary": {
                    "chapters": chapters,
                    "total_words": total_words,
                    "pace_dist": pace_dist,
                    "emotion_dist": emotion_dist,
                    "conflict_dist": conflict_dist,
                    "pleasure_dist": pleasure_dist,
                },
            })
    return {"books": result, "genre": genre or "全部"}


@router.get("/api/disassembly/book")
async def disassembly_book(name: str = Query(...), genre: str = Query("")):
    rhythm_base = PROJECT_ROOT / "data" / "processed"
    if genre and genre != "全部":
        search_dirs = [rhythm_base / genre / "rhythm"]
    else:
        search_dirs = []
        if rhythm_base.exists():
            for g_dir in sorted(d for d in rhythm_base.iterdir() if d.is_dir()):
                if (g_dir / "rhythm").exists():
                    search_dirs.append(g_dir / "rhythm")
    clean_name = name
    if clean_name.startswith("rhythm_"):
        clean_name = clean_name[len("rhythm_"):]
    if clean_name.endswith(".csv"):
        clean_name = clean_name[:-4]

    csv_path = None
    book_genre = genre or "末世"
    for d in search_dirs:
        if not d.exists():
            continue
        candidate = d / f"rhythm_{clean_name}.csv"
        if candidate.exists():
            csv_path = candidate
            book_genre = d.parent.name
            break
        for f in d.glob("rhythm_*.csv"):
            stem = f.stem.replace("rhythm_", "")
            if stem == clean_name or stem.replace(" ", "_") == clean_name.replace(" ", "_"):
                csv_path = f
                book_genre = d.parent.name
                break
        if csv_path:
            break
    if not csv_path or not csv_path.exists():
        raise HTTPException(404, f"Book not found: {name}")
    try:
        rows = []
        pace_dist = {}
        emotion_dist = {}
        conflict_dist = {}
        pleasure_dist = {}
        total_words = 0
        with open(csv_path, encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                wc = 0
                try:
                    wc = int(r.get("wc") or "0")
                except ValueError:
                    pass
                total_words += wc
                pace = (r.get("pace") or "").strip()
                if pace:
                    pace_dist[pace] = pace_dist.get(pace, 0) + 1
                emotion = (r.get("emotion") or "").strip()
                if emotion:
                    emotion_dist[emotion] = emotion_dist.get(emotion, 0) + 1
                conflict = (r.get("conflict") or "").strip().lower()
                ck = "conflict" if conflict in ("true", "1") else "none"
                conflict_dist[ck] = conflict_dist.get(ck, 0) + 1
                pleasure = (r.get("pleasure_type") or "none").strip()
                pleasure_dist[pleasure] = pleasure_dist.get(pleasure, 0) + 1
                rows.append({
                    "ch": r.get("ch_num", ""),
                    "wc": wc,
                    "pace": pace,
                    "emotion": emotion,
                    "conflict": conflict in ("true", "1"),
                    "pleasure_type": pleasure,
                    "pleasure_level": (r.get("pleasure_level") or "").strip(),
                    "conflict_level": (r.get("conflict_level") or "").strip(),
                })
        total = len(rows)
        summary = {
            "chapters": total,
            "total_words": total_words,
            "pace_dist": pace_dist,
            "emotion_dist": emotion_dist,
            "conflict_dist": conflict_dist,
            "pleasure_dist": pleasure_dist,
        }
        return {
            "book": name,
            "genre": book_genre,
            "summary": summary,
            "chapters": rows[:50],
            "total": total,
        }
    except HTTPException:
        raise
    except Exception as e:
        logging.error("disassembly_book error: %s", e, exc_info=True)
        raise HTTPException(500, f"Failed to read book data: {e}")


@router.post("/api/start")
async def start_analysis(genre: str = "末世", books: str = ""):
    if app_state.analyze_process is not None and app_state.analyze_process.poll() is None:
        return {"ok": False, "message": "拆书流程已在运行中"}
    script = PROJECT_ROOT / "src" / "xiaoshuo" / "pipeline" / "analyze_all.py"
    cmd = [sys.executable, str(script), "--genre", genre]
    if books:
        cmd.extend(["--books", books])
    app_state.set_startup_state(status="running", message="启动中...", progress=0)
    try:
        proc = subprocess.Popen(
            cmd, cwd=str(PROJECT_ROOT),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            env={**os.environ, "PYTHONPATH": str(PROJECT_ROOT / "src")},
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        app_state.analyze_process = proc
        return {"ok": True, "message": f"已启动 (PID {proc.pid})"}
    except Exception as e:
        app_state.set_startup_state(status="error", message=str(e), error=str(e))
        return {"ok": False, "message": str(e)}


@router.post("/api/stop")
async def stop_analysis():
    proc = app_state.analyze_process
    if proc is None or proc.poll() is not None:
        app_state.analyze_process = None
        clear_stage()
        app_state.set_startup_state(status="idle")
        return {"ok": False, "message": "没有运行中的拆书流程"}
    pid = proc.pid
    try:
        proc.terminate()
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        try:
            proc.kill()
        except Exception:
            pass
    except Exception:
        pass
    app_state.analyze_process = None
    clear_stage()
    app_state.set_startup_state(status="idle")
    return {"ok": True, "message": f"已停止拆书流程 (PID {pid})"}

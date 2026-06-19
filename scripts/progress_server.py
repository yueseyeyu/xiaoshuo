#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
progress_server.py — 拆书进度监控面板 (零依赖, stdlib only)
=============================================================
启动: python scripts/progress_server.py
访问: http://localhost:8090
自动扫描 data/processed/{genre}/summaries/ 下的 checkpoint 文件
每 2 秒刷新，显示每本书的 L1/L2/L3 进度 + ETA
"""
import csv
import json
import sys
import time
import threading
import traceback
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
PORT = 8090

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta http-equiv="refresh" content="3">
<title>拆书进度监控</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{background:linear-gradient(135deg,#1a1a2e 0%,#16213e 100%);color:#e0e0e0;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"Microsoft YaHei",sans-serif;padding:20px;min-height:100vh}
.container{max-width:1200px;margin:0 auto}
h1{color:#00d4ff;margin-bottom:8px;font-size:24px;font-weight:600;text-align:center}
.subtitle{color:#888;text-align:center;margin-bottom:25px;font-size:13px}
.summary{display:flex;justify-content:center;gap:30px;margin-bottom:25px;font-size:14px;background:rgba(0,212,255,0.1);padding:12px 25px;border-radius:25px}
.summary-item{display:flex;align-items:center;gap:8px}
.summary-item .num{font-weight:bold;font-size:16px}
.summary-item.done{color:#00ff88}
.summary-item.running{color:#00d4ff}
.summary-item.pending{color:#888}
.books{display:grid;grid-template-columns:repeat(auto-fill,minmax(380px,1fr));gap:15px}
.book{padding:16px;background:rgba(22,33,62,0.8);border-radius:12px;border-left:4px solid #0f3460;transition:all 0.3s;backdrop-filter:blur(10px)}
.book:hover{transform:translateY(-2px);box-shadow:0 8px 25px rgba(0,0,0,0.3)}
.book.active{border-left-color:#00d4ff;background:rgba(0,212,255,0.1)}
.book.done{border-left-color:#00ff88;background:rgba(0,255,136,0.1)}
.book.failed{border-left-color:#ff4444}
.book-name{font-size:15px;margin-bottom:10px;color:#fff;font-weight:500;display:flex;align-items:center;gap:10px}
.book-name .status{font-size:12px;padding:3px 10px;border-radius:12px;background:rgba(255,255,255,0.1)}
.status.running{color:#00d4ff;background:rgba(0,212,255,0.2)}
.status.done{color:#00ff88;background:rgba(0,255,136,0.2)}
.status.pending{color:#888;background:rgba(136,136,136,0.2)}
.bar-row{display:flex;align-items:center;margin:6px 0;font-size:13px}
.bar-label{width:35px;color:#aaa;font-weight:500}
.bar-wrap{flex:1;height:20px;background:rgba(15,52,96,0.5);border-radius:10px;overflow:hidden;margin:0 12px;position:relative}
.bar-fill{height:100%;border-radius:10px;transition:width 0.5s ease;position:relative}
.bar-fill::after{content:"";position:absolute;top:0;left:0;right:0;bottom:0;background:linear-gradient(90deg,transparent,rgba(255,255,255,0.3),transparent);animation:shimmer 2s infinite}
@keyframes shimmer{0%{transform:translateX(-100%)}100%{transform:translateX(100%)}}
.bar-fill.l1{background:linear-gradient(90deg,#e94560,#ff6b6b)}
.bar-fill.l2{background:linear-gradient(90deg,#00d4ff,#00a8ff)}
.bar-fill.l3{background:linear-gradient(90deg,#00ff88,#00cc6a)}
.bar-info{width:100px;color:#aaa;flex-shrink:0;text-align:right;font-size:12px;font-variant-numeric:tabular-nums}
.empty{color:#666;font-style:italic;padding:8px 0}
.timestamp{color:#555;text-align:center;margin-top:30px;font-size:12px;padding-top:20px;border-top:1px solid rgba(255,255,255,0.1)}
</style>
</head>
<body>
<div class="container">
<h1>拆书进度监控面板</h1>
<div class="subtitle">Recursive Summarization Progress · 每3秒自动刷新</div>
<div class="summary">{summary}</div>
<div class="books">{books_html}</div>
<div class="timestamp">最后更新: {timestamp}</div>
</div>
</body>
</html>"""

BOOK_ROW = """<div class="book {cls}">
<div class="book-name">{name} <span class="status {st_cls}">{st_text}</span></div>
{l1_bar}{l2_bar}{l3_bar}
</div>"""

BAR_HTML = """<div class="bar-row">
<span class="bar-label">{label}</span>
<div class="bar-wrap"><div class="bar-fill {cls}" style="width:{pct}%"></div></div>
<span class="bar-info">{done}/{total} ({pct}%) {eta}</span>
</div>"""


def _chapter_count_from_rhythm(book_name, genre="末世"):
    """Read actual chapter count from pre-computed rhythm CSV."""
    rhythm_dir = PROJECT_ROOT / "data" / "processed" / genre / "rhythm"
    for csv_path in sorted(rhythm_dir.glob("rhythm_*.csv")):
        stem = csv_path.stem.replace("rhythm_", "")
        if book_name[:15] in stem or stem[:15] in book_name:
            try:
                reader = csv.DictReader(open(csv_path, 'r', encoding='utf-8-sig'))
                return sum(1 for _ in reader)
            except Exception:
                pass
            break
    return None


def scan_progress(genre="末世"):
    """Scan all books' checkpoint files and return progress data."""
    summaries_dir = PROJECT_ROOT / "data" / "processed" / genre / "summaries"
    books = []

    # Find all checkpoint files
    for cp_path in sorted(summaries_dir.glob("*_checkpoint.json")):
        book_name = cp_path.stem.replace("_checkpoint", "")
        try:
            cp = json.loads(cp_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, IOError):
            continue

        l1_done = len(cp.get("l1_data", {}))
        l2_done = len(cp.get("l2_done", []))
        l3_done = cp.get("l3_done", False)

        # Total from checkpoint (set by _run_l1_if_needed); fallback to rhythm CSV
        l1_total = cp.get("l1_total", 0)
        if not l1_total:
            ch_count = _chapter_count_from_rhythm(book_name, genre)
            l1_total = max(1, (ch_count + 7) // 8) if ch_count else "?"

        # Check if output JSON exists and is valid
        json_path = summaries_dir / f"{book_name}_recursive.json"
        is_complete = False
        if json_path.exists():
            try:
                data = json.loads(json_path.read_text(encoding="utf-8"))
                if data.get("l3_analysis", {}).get("book_summary"):
                    is_complete = True
            except (json.JSONDecodeError, IOError):
                pass

        # Determine status
        if is_complete:
            status = "done"
            status_text = "已完成"
        elif l1_done > 0:
            status = "running"
            status_text = f"进行中 L1 {l1_done}/{l1_total}"
        else:
            status = "pending"
            status_text = "等待"

        books.append({
            "name": book_name[:40],
            "status": status,
            "status_text": status_text,
            "l1_done": l1_done,
            "l1_total": l1_total,
            "l2_done": l2_done,
            "l3_done": l3_done,
            "is_complete": is_complete,
        })

    # Also include books without checkpoint yet (pending)
    seen_names = {b["name"] for b in books}
    txt_dir = PROJECT_ROOT / "data" / "raw" / "novels" / genre
    for txt in sorted(txt_dir.glob("*.txt")):
        name = txt.stem[:40]
        if name not in seen_names:
            books.append({
                "name": name,
                "status": "pending",
                "status_text": "等待",
                "l1_done": 0,
                "l1_total": "?",
                "l2_done": 0,
                "l3_done": False,
                "is_complete": False,
            })

    return books


def render_html(genre="末世"):
    books = scan_progress(genre)
    done_count = sum(1 for b in books if b["is_complete"])
    running_count = sum(1 for b in books if b["status"] == "running")
    total = len(books)

    summary = (
        f'<div class="summary-item done"><span class="num">{done_count}</span> <span>已完成</span></div>'
        f'<div class="summary-item running"><span class="num">{running_count}</span> <span>进行中</span></div>'
        f'<div class="summary-item pending"><span class="num">{total - done_count - running_count}</span> <span>等待中</span></div>'
    )

    rows = []
    for b in books:
        cls_map = {"done": "done", "running": "active", "pending": ""}
        st_cls_map = {"done": "done", "running": "running", "pending": "skip"}

        # L1 bar
        l1_pct = (b["l1_done"] / b["l1_total"] * 100) if isinstance(b["l1_total"], int) and b["l1_total"] > 0 else 0
        l1_eta = ""
        l1_bar = BAR_HTML.format(label="L1", cls="l1", pct=min(int(l1_pct), 100),
                                  done=b["l1_done"], total=b["l1_total"],
                                  eta=l1_eta) if b["l1_total"] != "?" else ""

        # L2 bar (estimate from L1 groups / 5)
        l2_expected = max(1, b["l1_done"] // 5) if isinstance(b["l1_done"], int) else 0
        l2_pct = (b["l2_done"] / l2_expected * 100) if l2_expected > 0 else 0
        l2_bar = BAR_HTML.format(label="L2", cls="l2", pct=min(int(l2_pct), 100),
                                  done=b["l2_done"], total=l2_expected, eta="")

        # L3 bar
        l3_pct = 100 if b["l3_done"] else 0
        l3_bar = BAR_HTML.format(label="L3", cls="l3", pct=l3_pct,
                                  done="1" if b["l3_done"] else "0",
                                  total="1", eta="")

        rows.append(BOOK_ROW.format(
            cls=cls_map.get(b["status"], ""),
            name=b["name"],
            st_cls=st_cls_map.get(b["status"], ""),
            st_text=b["status_text"],
            l1_bar=l1_bar if l1_bar else f'<div class="bar-row"><span class="bar-label">L1</span><span class="empty">等待中...</span></div>',
            l2_bar=l2_bar,
            l3_bar=l3_bar,
        ))

    html = HTML_TEMPLATE.replace("{summary}", summary)
    html = html.replace("{books_html}", "\n".join(rows))
    html = html.replace("{timestamp}", time.strftime("%H:%M:%S"))
    return html


class ProgressHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/api/progress":
            try:
                books = scan_progress()
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps(books, ensure_ascii=False).encode("utf-8"))
            except Exception as e:
                self.send_error(500, str(e))
        else:
            try:
                html = render_html()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(html.encode("utf-8"))
            except Exception as e:
                traceback.print_exc()
                self.send_error(500, str(e))

    def log_message(self, format, *args):
        pass  # suppress request logging


def main():
    print(f"[Progress Server] http://localhost:{PORT}")
    print(f"  Open browser → auto-refresh every 3s")
    print(f"  Press Ctrl+C to stop")
    server = HTTPServer(("127.0.0.1", PORT), ProgressHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[STOP] Server closed")
        server.server_close()


if __name__ == "__main__":
    main()

#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
v815_gen_iaa_materials.py — 生成朋友标注材料
================================================
从47章golden中选20-25章, 提取章节文本, 生成标注HTML工具。

用法:
  $env:PYTHONUTF8=1
  D:\miniconda3\envs\llm-shared\python.exe scripts/v815_gen_iaa_materials.py
"""
import sys, os
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')
os.environ["PYTHONUTF8"] = "1"

import csv, json, re, random
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

GENRE = "末世"

def main():
    from xiaoshuo.pipeline.llm_batch_score import extract_chapters, INDEX_PATH, NOVELS_DIR

    # Load golden
    golden_csv = PROJECT_ROOT / "data" / "golden" / GENRE / "tier3" / "human_golden_merged.csv"
    with open(golden_csv, "r", encoding="utf-8-sig") as f:
        golden_rows = list(csv.DictReader(f))

    # Load v8.15 fresh scores for selection
    v815_path = PROJECT_ROOT / "data" / "reports" / GENRE / "v8.15_verify_full_47.json"
    with open(v815_path, "r", encoding="utf-8") as f:
        v815 = json.load(f)
    v815_lookup = {(r["book"], r["ch_num"]): r for r in v815["results"]}

    # Build book -> txt mapping
    with open(INDEX_PATH, "r", encoding="utf-8") as f:
        index = json.load(f)
    novels = index.get("genres", {}).get(GENRE, {}).get("novels", [])
    book_to_txt = {}
    for novel in novels:
        txt_file = novel.get("file", "")
        for fp in NOVELS_DIR.glob(f"{GENRE}/*.txt"):
            if fp.name == txt_file:
                short_name = txt_file.replace(".txt", "").replace("《", "").replace("》", "")
                m = re.match(r"([^（(]+)", short_name)
                if m:
                    short_name = m.group(1).strip()
                book_to_txt[short_name] = fp
                break

    # Selection: cover 5+ books, include low/mid/high scores
    # Group by score range
    by_range = {"low": [], "mid": [], "high": []}
    for row in golden_rows:
        book = row.get("book", "").strip()
        ch_num = int(row.get("ch_num", 0))
        human_i = float(row.get("human_intensity", 5))
        key = (book, ch_num)
        v = v815_lookup.get(key)
        if not v:
            continue
        llm_i = v["new_i"]
        diff = abs(llm_i - human_i)  # LLM-human disagreement
        entry = {"book": book, "ch_num": ch_num, "human_i": human_i, "llm_i": llm_i, "diff": diff, "row": row}
        if human_i <= 3.5:
            by_range["low"].append(entry)
        elif human_i <= 6.5:
            by_range["mid"].append(entry)
        else:
            by_range["high"].append(entry)

    # Select: 6 low + 8 mid + 6 high = 20, prioritizing high diff (interesting cases)
    selected = []
    for cat, count in [("low", 6), ("mid", 8), ("high", 6)]:
        pool = sorted(by_range[cat], key=lambda x: -x["diff"])  # high diff first
        selected.extend(pool[:count])

    # Ensure book diversity: if one book has >5, replace with others
    from collections import Counter
    book_counts = Counter(s["book"] for s in selected)
    over = {b: c for b, c in book_counts.items() if c > 5}
    for book, extra in over.items():
        # Find replacements from other books in same category
        for cat in ["low", "mid", "high"]:
            pool = [e for e in by_range[cat] if e not in selected and e["book"] != book]
            to_replace = [s for s in selected if s["book"] == book and selected.index(s) >= 5]
            for r in to_replace[:extra - 5]:
                if pool:
                    selected[selected.index(r)] = pool.pop(0)

    selected.sort(key=lambda x: (x["book"], x["ch_num"]))
    print(f"Selected {len(selected)} chapters from {len(set(s['book'] for s in selected))} books", flush=True)

    # Extract chapter texts
    _cache = {}
    chapters_data = []
    for s in selected:
        book = s["book"]
        ch_num = s["ch_num"]
        txt_path = None
        for sn, fp in book_to_txt.items():
            if sn in book or book in sn:
                txt_path = fp
                break
        if not txt_path:
            print(f"  SKIP: {book} ch{ch_num} (txt not found)", flush=True)
            continue

        if str(txt_path) not in _cache:
            _cache[str(txt_path)] = extract_chapters(txt_path)
        chapters = _cache[str(txt_path)]

        chapter = None
        for ch in chapters:
            if ch.get("num") == ch_num:
                chapter = ch
                break
        if not chapter:
            print(f"  SKIP: {book} ch{ch_num} (chapter not found)", flush=True)
            continue

        text = chapter.get("raw_body", "")[:2000]  # limit to 2000 chars for readability
        chapters_data.append({
            "book": book,
            "ch_num": ch_num,
            "text": text,
            "wc": len(text),
        })
        print(f"  {book} ch{ch_num} ({len(text)}字)", flush=True)

    # Generate HTML annotation tool
    html = generate_html(chapters_data)
    out_path = PROJECT_ROOT / "data" / "golden" / GENRE / "tier3" / "iaa_annotation_tool.html"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"\nHTML tool: {out_path}", flush=True)

    # Also generate plain text version
    txt_out = generate_txt(chapters_data)
    txt_path = PROJECT_ROOT / "data" / "golden" / GENRE / "tier3" / "iaa_chapters.txt"
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(txt_out)
    print(f"Text version: {txt_path}", flush=True)

def generate_html(chapters_data):
    chapters_js = json.dumps(chapters_data, ensure_ascii=False)
    n = len(chapters_data)
    # Build option list for 1.0 to 10.0 in 0.5 steps
    options_html = ""
    for v in [1 + i * 0.5 for i in range(19)]:
        vs = str(v)
        options_html += '<option value="' + vs + '">' + vs + '</option>\n'
    
    html = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>网文章节评分 — 朋友标注工具</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: -apple-system, "Microsoft YaHei", sans-serif; background: #f5f5f5; color: #333; }
  .container { max-width: 800px; margin: 0 auto; padding: 20px; }
  .header { background: #4a90d9; color: white; padding: 20px; border-radius: 8px; margin-bottom: 20px; }
  .header h1 { font-size: 1.4em; margin-bottom: 8px; }
  .header p { font-size: 0.85em; opacity: 0.9; line-height: 1.6; }
  .progress { background: #e0e0e0; height: 6px; border-radius: 3px; margin: 10px 0; }
  .progress-bar { background: #4a90d9; height: 100%; border-radius: 3px; transition: width 0.3s; }
  .chapter { background: white; border-radius: 8px; padding: 20px; margin-bottom: 20px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
  .ch-title { font-size: 1.1em; font-weight: bold; margin-bottom: 12px; color: #4a90d9; }
  .ch-text { font-size: 0.95em; line-height: 1.8; max-height: 400px; overflow-y: auto; background: #fafafa; padding: 12px; border-radius: 4px; border: 1px solid #eee; margin-bottom: 16px; white-space: pre-wrap; }
  .rating { display: flex; gap: 20px; margin-bottom: 12px; align-items: center; }
  .rating label { font-weight: bold; min-width: 100px; font-size: 0.9em; }
  .rating select { padding: 6px 10px; font-size: 1em; border: 2px solid #ddd; border-radius: 4px; width: 80px; }
  .rating select:focus { border-color: #4a90d9; outline: none; }
  .nav { display: flex; justify-content: space-between; margin-top: 16px; }
  .nav button { padding: 8px 16px; background: #4a90d9; color: white; border: none; border-radius: 4px; cursor: pointer; font-size: 0.9em; }
  .nav button:hover { background: #357abd; }
  .nav button:disabled { background: #ccc; cursor: not-allowed; }
  .actions { margin-top: 20px; text-align: center; }
  .actions button { padding: 10px 30px; background: #27ae60; color: white; border: none; border-radius: 4px; cursor: pointer; font-size: 1em; }
  .actions button:hover { background: #229954; }
  .hidden { display: none; }
  .result { margin-top: 20px; background: #fff3cd; border: 1px solid #ffeaa7; padding: 16px; border-radius: 4px; font-family: monospace; font-size: 0.85em; white-space: pre-wrap; max-height: 300px; overflow-y: auto; }
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <h1>网文章节评分</h1>
    <p>
      请阅读每章文本，然后为以下两个维度打分（1-10分整数或半整数，如7.5）：<br>
      <b>① 爽点强度</b>：这章的爽感有多强？1=无聊透顶，10=爽到飞起<br>
      <b>② 留存力</b>：读完这章你还想看下一章吗？1=果断弃书，10=欲罢不能
    </p>
    <div class="progress"><div class="progress-bar" id="progressBar" style="width:0%"></div></div>
    <span id="progressText">0 / N_TOTAL</span>
  </div>
  <div id="chapterArea"></div>
  <div class="actions">
    <button onclick="exportData()" id="exportBtn">生成评分结果(CSV)</button>
    <div id="result" class="result hidden"></div>
  </div>
</div>
<script>
const chapters = CHAPTERS_JSON;
let currentIdx = 0;
const ratings = {};

function renderChapter(idx) {
  if (idx >= chapters.length) { showExport(); return; }
  const ch = chapters[idx];
  const key = ch.book + "_ch" + ch.ch_num;
  const existing = ratings[key] || {};
  
  const opts = '<option value="">请选择</option>' + OPTIONS_HTML;
  const intOpts = opts.replace('<option value="' + (existing.intensity||'') + '">', '<option value="' + (existing.intensity||'') + '" selected>');
  const retOpts = opts.replace('<option value="' + (existing.retention||'') + '">', '<option value="' + (existing.retention||'') + '" selected>');
  
  document.getElementById("chapterArea").innerHTML = 
    '<div class="chapter">' +
      '<div class="ch-title">第' + (idx+1) + '章 / 共' + chapters.length + '章 — ' + ch.book + ' 第' + ch.ch_num + '章 (' + ch.wc + '字)</div>' +
      '<div class="ch-text">' + ch.text + '</div>' +
      '<div class="rating"><label>爽点强度 (1-10):</label><select id="intensity" onchange="updateScore()">' + intOpts + '</select></div>' +
      '<div class="rating"><label>留存力 (1-10):</label><select id="retention" onchange="updateScore()">' + retOpts + '</select></div>' +
      '<div class="nav">' +
        '<button onclick="prevChapter()" id="prevBtn"' + (idx==0?' disabled':'') + '>上一章</button>' +
        '<button onclick="nextChapter()" id="nextBtn">下一章</button>' +
      '</div>' +
    '</div>';
  
  const filled = Object.keys(ratings).filter(k => ratings[k].intensity && ratings[k].retention).length;
  document.getElementById("progressBar").style.width = (filled/chapters.length*100) + "%";
  document.getElementById("progressText").textContent = filled + " / " + chapters.length;
}

function updateScore() {
  const ch = chapters[currentIdx];
  const key = ch.book + "_ch" + ch.ch_num;
  ratings[key] = {
    intensity: document.getElementById("intensity").value,
    retention: document.getElementById("retention").value,
  };
  const filled = Object.keys(ratings).filter(k => ratings[k].intensity && ratings[k].retention).length;
  document.getElementById("progressBar").style.width = (filled/chapters.length*100) + "%";
  document.getElementById("progressText").textContent = filled + " / " + chapters.length;
}

function nextChapter() {
  if (currentIdx < chapters.length - 1) { currentIdx++; renderChapter(currentIdx); }
  else { showExport(); }
}
function prevChapter() {
  if (currentIdx > 0) { currentIdx--; renderChapter(currentIdx); }
}
function showExport() {
  document.getElementById("chapterArea").innerHTML = '<div style="text-align:center;padding:40px;color:#27ae60;font-size:1.2em;">全部完成！请点击下方按钮生成结果</div>';
}
function exportData() {
  let lines = ["book,ch_num,friend_intensity,friend_retention"];
  for (const ch of chapters) {
    const key = ch.book + "_ch" + ch.ch_num;
    const r = ratings[key] || {};
    lines.push(ch.book + "," + ch.ch_num + "," + (r.intensity||"") + "," + (r.retention||""));
  }
  const csv = lines.join("\\n");
  document.getElementById("result").textContent = csv;
  document.getElementById("result").classList.remove("hidden");
  const blob = new Blob([csv], {type:"text/csv;charset=utf-8"});
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = "friend_annotations.csv";
  a.click();
}

renderChapter(0);
</script>
</body>
</html>"""
    
    html = html.replace("CHAPTERS_JSON", chapters_js)
    html = html.replace("OPTIONS_HTML", json.dumps(options_html))
    html = html.replace("N_TOTAL", str(n))
    return html

def generate_txt(chapters_data):
    lines = []
    lines.append("=" * 60)
    lines.append("网文章节评分 — 朋友标注材料")
    lines.append("=" * 60)
    lines.append("")
    lines.append("说明：请阅读每章文本，为以下两个维度打分(1-10分，可用0.5)：")
    lines.append("  ① 爽点强度：这章的爽感有多强？1=无聊透顶，10=爽到飞起")
    lines.append("  ② 留存力：读完想看下一章吗？1=果断弃书，10=欲罢不能")
    lines.append("")
    for i, ch in enumerate(chapters_data):
        lines.append("-" * 60)
        lines.append(f"第{i+1}章/共{len(chapters_data)}章 — {ch['book']} 第{ch['ch_num']}章 ({ch['wc']}字)")
        lines.append(f"爽点强度: [    ]")
        lines.append(f"留存力:   [    ]")
        lines.append("-" * 60)
        lines.append(ch["text"])
        lines.append("")
    lines.append("=" * 60)
    lines.append("完成！请将每章的分数填入上方的[ ]中，然后发回。")
    return "\n".join(lines)

if __name__ == "__main__":
    main()

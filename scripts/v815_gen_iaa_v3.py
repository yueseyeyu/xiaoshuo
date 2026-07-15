#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
v815_gen_iaa_v3.py — 基于已有annotate_tool.html生成IAA版本
============================================================
4处关键修改:
1. localStorage key改为annotations_iaa (不冲突)
2. 导出文件名改为friend_annotations.csv (不覆盖)
3. 章节数据去除human/llm/glm分数 (防锚定偏差)
4. CSV添加annotator列 (标识标注者)

用法:
  $env:PYTHONUTF8=1
  D:\miniconda3\envs\llm-shared\python.exe scripts/v815_gen_iaa_v3.py
"""
import sys, os
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')
os.environ["PYTHONUTF8"] = "1"

import csv, json, re
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))
GENRE = "末世"

def main():
    from xiaoshuo.pipeline.llm_batch_score import extract_chapters, INDEX_PATH, NOVELS_DIR

    # === 1. 选章 (S10+A7+B3=20) ===
    tier_map = {
        "地球游戏场": "S", "末世大回炉": "S", "异兽迷城": "S",
        "黑暗血时代": "S", "第一序列": "S", "长夜余火": "S", "末日乐园": "S",
        "废土崛起": "A",
        "末日蟑螂": "B",
    }

    golden_csv = PROJECT_ROOT / "data" / "golden" / GENRE / "tier3" / "human_golden_merged.csv"
    with open(golden_csv, "r", encoding="utf-8-sig") as f:
        golden_rows = list(csv.DictReader(f))

    v815_path = PROJECT_ROOT / "data" / "reports" / GENRE / "v8.15_verify_full_47.json"
    with open(v815_path, "r", encoding="utf-8") as f:
        v815 = json.load(f)
    v815_lookup = {(r["book"], r["ch_num"]): r for r in v815["results"]}

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

    by_tier = {"S": [], "A": [], "B": []}
    for row in golden_rows:
        book = row.get("book", "").strip()
        ch_num = int(row.get("ch_num", 0))
        human_i = float(row.get("human_intensity", 5))
        tier = tier_map.get(book, "?")
        if tier not in by_tier:
            continue
        key = (book, ch_num)
        v = v815_lookup.get(key)
        llm_i = v["new_i"] if v else 0
        by_tier[tier].append({
            "book": book, "ch_num": ch_num,
            "human_i": human_i,
            "llm_i": llm_i,
            "diff": abs(llm_i - human_i) if v else 0,
        })

    selected = []
    # S=10, max 3 per book, high diff first
    s_books = {}
    for e in sorted(by_tier["S"], key=lambda x: -x["diff"]):
        b = e["book"]
        if b not in s_books: s_books[b] = 0
        if s_books[b] < 3:
            selected.append(e)
            s_books[b] += 1
        if len(selected) >= 10: break
    # A=7, spread across score range
    a_pool = sorted(by_tier["A"], key=lambda x: x["human_i"])
    a_low = [e for e in a_pool if e["human_i"] <= 3.5][:2]
    a_mid = [e for e in a_pool if 3.5 < e["human_i"] <= 6.5][:3]
    a_high = [e for e in a_pool if e["human_i"] > 6.5][:2]
    selected.extend(a_low + a_mid + a_high)
    # B=3, low scores
    b_low = sorted([e for e in by_tier["B"] if e["human_i"] <= 4], key=lambda x: x["human_i"])
    selected.extend(b_low[:3])

    selected.sort(key=lambda x: (x["book"], x["ch_num"]))
    print(f"Selected {len(selected)} chapters", flush=True)

    # === 2. 提取章节文本 (去除所有分数信息!) ===
    _cache = {}
    chapters_clean = []  # 只有book, ch_num, wc, body — 没有任何分数
    for s in selected:
        book = s["book"]
        ch_num = s["ch_num"]
        txt_path = None
        for sn, fp in book_to_txt.items():
            if sn in book or book in sn:
                txt_path = fp
                break
        if not txt_path: continue
        if str(txt_path) not in _cache:
            _cache[str(txt_path)] = extract_chapters(txt_path)
        chapters = _cache[str(txt_path)]
        chapter = None
        for ch in chapters:
            if ch.get("num") == ch_num:
                chapter = ch
                break
        if not chapter: continue
        text = chapter.get("raw_body", "")[:2000]
        # 关键: 只保留 book, ch_num, wc, body — 不含任何分数!
        chapters_clean.append({
            "book": book,
            "ch_num": ch_num,
            "wc": len(text),
            "body": text,
        })
        print(f"  {tier_map.get(book,'?')} {book} ch{ch_num} ({len(text)}字)", flush=True)

    # === 3. 读取已有模板并修改 ===
    template_path = PROJECT_ROOT / "data" / "golden" / GENRE / "tier3" / "annotate_tool.html"
    with open(template_path, "r", encoding="utf-8") as f:
        html = f.read()

    # 修改1: 替换标题
    html = html.replace(
        "网文评分标注工具 — 54章Tier3校准",
        "网文评分标注工具 — 20章IAA(朋友独立标注)"
    )
    html = html.replace("54章Tier3校准", "20章IAA朋友标注")

    # 修改2: 替换chapters JSON (去除所有分数)
    pattern = r'const chapters = \[.*?\];\s*\n'
    match = re.search(pattern, html, re.DOTALL)
    if match:
        new_json = "const chapters = " + json.dumps(chapters_clean, ensure_ascii=False) + ";\n"
        html = html[:match.start()] + new_json + html[match.end():]
        print("  [OK] chapters replaced (scores stripped)", flush=True)
    else:
        print("  [WARN] chapters not found", flush=True)

    # 修改3: localStorage key改为不冲突的
    html = html.replace("annotations_v3", "annotations_iaa_friend")
    html = html.replace("retest_v2", "retest_iaa_friend")
    print("  [OK] localStorage keys changed (annotations_iaa_friend)", flush=True)

    # 修改4: 替换exportCSV函数
    old_export_start = "function exportCSV() {"
    old_export_end = "function escapeCSV() {"
    idx_start = html.find(old_export_start)
    idx_end = html.find(old_export_end)
    if idx_start >= 0 and idx_end > idx_start:
        new_export = """function exportCSV() {
  const annotator = document.getElementById('annotatorName') ? document.getElementById('annotatorName').value.trim() : 'friend';
  if (!annotator) { alert('请先填写标注者姓名！'); return; }
  let csv = 'annotator,book,ch_num,wc,intensity,retention,pacing,immersion,emotion,tags,pros,cons,gap_reasons,confidence,timestamp\\n';
  let count = 0;
  chapters.forEach(ch => {
    const key = ch.book + '_' + ch.ch_num;
    const a = annotations[key];
    if (a && a.intensity) {
      csv += annotator + ',' + ch.book + ',' + ch.ch_num + ',' + ch.wc + ',' + a.intensity + ',' + a.retention + ',' + (a.pacing||'') + ',' + (a.immersion||'') + ',' + (a.emotion||'') + ',' + escapeCSV((a.tags||[]).join(';')) + ',' + escapeCSV(a.pros||'') + ',' + escapeCSV(a.cons||'') + ',' + escapeCSV((a.gap_reasons||[]).join(';')) + ',' + (a.confidence||'medium') + ',' + (a.timestamp||'') + '\\n';
      count++;
    }
  });
  if (count === 0) { alert('还没有标注任何章节！'); return; }
  const blob = new Blob(['\\ufeff' + csv], { type: 'text/csv;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url; a.download = 'friend_annotations.csv'; a.click();
  URL.revokeObjectURL(url);
  alert('已导出 ' + count + ' 章标注到 friend_annotations.csv\\n请将文件发给项目方');
}

"""
        html = html[:idx_start] + new_export + html[idx_end:]
        print("  [OK] exportCSV replaced (friend_annotations.csv + annotator column)", flush=True)
    else:
        print("  [WARN] exportCSV not found", flush=True)

    # 修改5: 在topbar添加标注者姓名输入框
    # 找到export按钮所在位置, 在它前面加输入框
    export_btn = '<button class="export-btn" onclick="exportCSV">'
    idx_btn = html.find(export_btn)
    if idx_btn >= 0:
        annotator_input = '<label style="color:var(--text-dim);font-size:12px;margin-right:4px;">标注者:</label><input id="annotatorName" type="text" placeholder="你的名字" value="" style="background:var(--bg-input);border:1px solid var(--border);border-radius:3px;padding:4px 8px;font-size:13px;width:100px;color:var(--text);" />'
        html = html[:idx_btn] + annotator_input + html[idx_btn:]
        print("  [OK] annotator name input added", flush=True)

    # 修改6: 禁用compare box (不显示LLM/GLM分数)
    html = html.replace("function updateCompareBox(", "function updateCompareBox_DISABLED(")
    print("  [OK] compare box disabled (no score leaking)", flush=True)

    # 保存
    out_path = PROJECT_ROOT / "data" / "golden" / GENRE / "tier3" / "iaa_annotation_tool.html"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"\nDone: {out_path}", flush=True)
    print(f"  - localStorage: annotations_iaa_friend (不冲突)", flush=True)
    print(f"  - 导出文件: friend_annotations.csv (不覆盖)", flush=True)
    print(f"  - 章节数据: 无任何分数 (防锚定)", flush=True)
    print(f"  - CSV含annotator列 (标识标注者)", flush=True)
    print(f"  - compare box已禁用 (不泄露分数)", flush=True)

if __name__ == "__main__":
    main()

"""
P0-2 Bugcheck v2: Known contradiction detection with precision/recall
2 test types: single-chapter (6 bugs) + cross-chapter (6 bugs)
Tests BOTH models. Uses keyword-based TP counting with manual verification.
"""
import subprocess, time, json, urllib.request, re
from pathlib import Path

LLAMA = r"D:\miniconda3\envs\llm-shared\Library\bin\llama-server.exe"
PORT = 8000

MODELS = [
    {"key":"Qwen3.5","gguf":r"D:\DaMoXing\Qwen3.5-9B-Q4_K_M.gguf",
     "n_gpu":35,"chatml":False,"kwargs":'{"enable_thinking": false}'},
    {"key":"R1","gguf":r"D:\DaMoXing\DeepSeek-R1-Distill-Qwen-7B-Q4_K_M.gguf",
     "n_gpu":35,"chatml":True,"kwargs":None},
]

# ===== Test Suite =====
# Test 1: Single-chapter (intra-chapter contradictions)
# Test 2: Cross-chapter (inter-chapter memory)

TEST_SUITE = [
    {
        "name": "Clean-Baseline (0 bugs, measures FP rate)",
        "chapter_path": Path(r"d:\Code\xiaoshuo\chapters\chapter_clean.md"),
        "system_prompt": "你是网文逻辑审查专家。找出以下章节中所有的逻辑矛盾。若无矛盾请明确说明。",
        "bug_defs": [],
    },
    {
        "name": "Single-Chapter (6 intra-chapter bugs)",
        "chapter_path": Path(r"d:\Code\xiaoshuo\chapters\chapter_bugtest.md"),
        "system_prompt": "你是网文逻辑审查专家。找出以下章节中所有的逻辑矛盾。",
        "bug_defs": [
            ("Bug1:Appearance","老赵眼睛深棕色→浅灰色",["深棕","浅灰","眼睛","矛盾"]),
            ("Bug2:Timeline","林默五天前→上周",["五天","上周","矛盾"]),
            ("Bug3:SelfContra","缺懂技术+经验为零",["缺","技术","经验","零"]),
            ("Bug4:CharKnow","林默知道叶凡隐私",["林默","知道","告诉","叶凡"]),
            ("Bug5:Timeline2","追出去三秒→后文独自离开",["追","三秒","离开"]),
            ("Bug6:Environment","潮湿+干燥",["潮湿","干燥","尘土"]),
        ],
    },
    {
        "name": "Cross-Chapter (6 inter-chapter bugs)",
        "chapter_path": Path(r"d:\Code\xiaoshuo\chapters\chapter_cross.md"),
        "system_prompt": "你是网文逻辑审查专家。以下包含两个章节的片段。找出片段A和片段B之间的所有跨章节逻辑矛盾。",
        "bug_defs": [
            ("Bug1:Quantity","16人→18人",["16","18","人","矛盾"]),
            ("Bug2:Timeline","三天前→一周前",["三天","一周","前","矛盾"]),
            ("Bug3:Timeline","练五年→两年前",["五年","两年","练枪","矛盾"]),
            ("Bug4:CharKnow","苏雨知道李家兄弟",["苏雨","李家","兄弟","知道"]),
            ("Bug5:Quantity","每隔三天→每天",["三天","每天","变异","来"]),
            ("Bug6:Factual","没有窗户→有窗户",["窗户","没有","洒","月光"]),
        ],
    },
]

def kill():
    subprocess.run(["taskkill","/f","/im","llama-server.exe"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL); time.sleep(2)

def start(m):
    kill()
    cmd = [LLAMA, "--model", m["gguf"], "--n-gpu-layers", str(m["n_gpu"]),
           "--ctx-size", "4096", "--port", str(PORT), "--host", "127.0.0.1"]
    if m["chatml"]: cmd += ["--chat-template", "chatml"]
    if m["kwargs"]: cmd += ["--chat-template-kwargs", m["kwargs"]]
    subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     creationflags=0x08000000)
    for _ in range(60):
        try:
            if urllib.request.urlopen(f"http://127.0.0.1:{PORT}/health", timeout=2).status == 200:
                return True
        except: time.sleep(1)
    return False

def run_test(chapter_path, sysp, bug_defs, m):
    """Run one test and return precision/recall stats."""
    chap = chapter_path.read_text(encoding="utf-8")
    wc = len(chap.replace("\n","").replace(" ",""))
    user = f"## 章节 ({wc}字):\n{chap}\n\n请找出所有逻辑矛盾，逐条列出。"

    data = json.dumps({
        "messages": [{"role":"system","content":sysp},{"role":"user","content":user}],
        "max_tokens": 4096, "temperature": 0.3,
    }).encode("utf-8")
    req = urllib.request.Request(f"http://127.0.0.1:{PORT}/v1/chat/completions",
                                 data, {"Content-Type":"application/json"})
    resp = json.loads(urllib.request.urlopen(req, timeout=300).read())
    raw = resp["choices"][0]["message"].get("content","")
    cleaned = re.sub(r"<think>.*?</think>\s*","", raw, flags=re.DOTALL)
    cleaned = re.sub(r"<think>.*$","", cleaned, flags=re.DOTALL)
    cleaned = cleaned.strip()
    tok = resp["usage"]["completion_tokens"]

    # Count TPs (keyword-based, 3+ keyword matches = detected)
    tp = 0
    details = []
    for name, desc, keywords in bug_defs:
        score = sum(1 for kw in keywords if kw.lower() in cleaned.lower())
        d = "Y" if score >= 3 else "N"
        if score >= 3: tp += 1
        details.append((name, d, score))
    total = len(bug_defs)
    # For clean baseline (0 bugs): measure FP directly
    if total == 0:
        fp = cleaned.lower().count("矛盾") + cleaned.lower().count("问题")
        return {
            "tp": 0, "total": 0, "precision": 1.0 if fp == 0 else 0.0,
            "recall": 1.0, "f1": 1.0 if fp == 0 else 0.0, "tokens": tok,
            "output": cleaned, "details": [("Clean-Baseline", "PASS" if fp == 0 else f"FAIL({fp} FPs)", fp)],
        }
    recall = tp / total if total > 0 else 0
    # FP estimate: count review items, subtract TP. Uses both formats.
    markers = cleaned.lower().count("矛盾") + cleaned.lower().count("问题") + cleaned.lower().count("不一致")
    fp = max(0, markers//2 - tp)  # each bug typically uses ~2 keywords
    precision = tp / max(tp + fp, 1)
    f1 = 2 * precision * recall / max(precision + recall, 0.01)

    return {
        "tp": tp, "total": total, "precision": precision, "recall": recall,
        "f1": f1, "tokens": tok, "output": cleaned, "details": details,
    }

def print_results(label, r, bug_defs):
    if r["total"] == 0:
        fp_count = r["details"][0][2] if r["details"] else 0
        print(f"  {label}: FP={fp_count}  P={r['precision']:.2f}  ({r['tokens']}t)")
        return
    print(f"  {label}: TP={r['tp']}/{r['total']}  P={r['precision']:.2f}  R={r['recall']:.2f}  F1={r['f1']:.2f}  ({r['tokens']}t)")
    for name, det, score in r["details"]:
        print(f"    [{det}] {name} ({score}/4 kw)")

# ===== MAIN =====
kill()
all_results = []

for m in MODELS:
    if not start(m): continue
    print(f"\n{'='*60}")
    print(f"  [{m['key']}] Bugcheck v2")
    print(f"{'='*60}")
    model_results = []
    for test in TEST_SUITE:
        print(f"\n  --- {test['name']} ---")
        r = run_test(test["chapter_path"], test["system_prompt"], test["bug_defs"], m)
        print_results("  Result", r, test["bug_defs"])
        model_results.append({"test": test["name"], "result": r})
    all_results.append({"model": m["key"], "tests": model_results})
    kill()

# Summary
print(f"\n{'='*60}")
print("  BUGCHECK v2 SUMMARY")
print(f"{'='*60}")

for ar in all_results:
    print(f"\n  [{ar['model']}]")
    for t in ar["tests"]:
        r = t["result"]
        print(f"    {t['test']}: F1={r['f1']:.2f}  TP={r['tp']}/{r['total']}  ({r['tokens']}t)")

if len(all_results) == 2:
    for i, test_name in enumerate([t["name"] for t in TEST_SUITE]):
        ar0 = all_results[0]["tests"][i]["result"]
        ar1 = all_results[1]["tests"][i]["result"]
        w = all_results[0]["model"] if ar0["f1"] > ar1["f1"] else all_results[1]["model"]
        print(f"    {test_name}: winner={w} (F1: {ar0['f1']:.2f} vs {ar1['f1']:.2f})")

print(f"\n[DONE]")

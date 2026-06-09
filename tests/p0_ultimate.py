"""
P0-2 ULTIMATE v2: S1(创意)+S3(逻辑)+S4(风格) 三维匿名交叉对比
方法: arxiv 2410.21819 (position-swap) + GER-Eval (task-specific rubrics) + Ideation Diversity
"""
import subprocess, time, json, urllib.request, re
from pathlib import Path

LLAMA = r"D:\miniconda3\envs\llm-shared\Library\bin\llama-server.exe"
CHAPTER = Path(r"d:\Code\xiaoshuo\chapters\chapter_bugtest.md")  # 2000字+6个不可争议章节内矛盾
PORT = 8000

# ===== Models =====
QWEN_C  = {"key":"Qwen3.5","gguf":r"D:\DaMoXing\Qwen3.5-9B-Q4_K_M.gguf",
           "n_gpu":35,"chatml":False,"kwargs":'{"enable_thinking": true}'}   # S1 creative
QWEN_R  = {"key":"Qwen3.5","gguf":r"D:\DaMoXing\Qwen3.5-9B-Q4_K_M.gguf",
           "n_gpu":35,"chatml":False,"kwargs":'{"enable_thinking": false}'}  # S3/S4 review
R1      = {"key":"R1","gguf":r"D:\DaMoXing\DeepSeek-R1-Distill-Qwen-7B-Q4_K_M.gguf",
           "n_gpu":35,"chatml":True,"kwargs":None}

# ===== S1: 创意引导 (CreativityPrism + Ideation Diversity) =====
S1_DIMS = [
    ("Novelty","新颖性：方向是否出乎意料、打破常见网文模板？"),
    ("Writeability","可写性：方向是否具体可操作？作者能否立刻展开？"),
    ("Diversity","多样性：3个方向之间是否差异足够大(语义不重叠)？"),
    ("PleasurePotential","爽点潜力：是否蕴含至少一种爽点模式(打脸/逆袭)？"),
]
S1_SYSP = (
    "你是网文创意引导师。为下章提供3个不同的剧情方向(每个1句话,标1/2/3)。"
    "覆盖不同认知距离(近/中/远)。标注爽点模式。"
)
S1_JUDGE = (
    "你是创意评审专家。有两份匿名AI创意方向(各含3个方向),独立评分(1-5):\n"
    "1=无创意/模板化/空输出  2=有方向但套路化  3=有1个新颖方向+可操作\n"
    "4=多个有新意的方向,含爽点设计  5=3个方向各具特色,差异化明确,可直接采用\n"
    "只输出JSON: {\"A\":整数,\"B\":整数}"
)

# ===== S3: 逻辑审查 (ConStory-Bench 11dim) =====
S3_DIMS = [
    ("Timeline","时间矛盾：绝对时间、持续时间、同时性错误。"),
    ("Causal","因果断裂：无因之果、因果链缺失、伏笔无下文。"),
    ("CharMemory","记忆矛盾：角色对过去的记忆前后不一致。"),
    ("CharKnowledge","知识矛盾：角色知道不该知道的信息。"),
    ("CharAbility","能力波动：技能无故变化、已展现能力消失。"),
    ("WorldRule","规则违反：违反世界法则、社会规范、地理矛盾。"),
    ("Appearance","外貌不匹配：同一人物/物体描述前后矛盾。"),
    ("Naming","命名混淆：名称、称谓不一致。"),
    ("Quantity","数量不匹配：年龄、尺寸、数量矛盾。"),
    ("Perspective","视角混乱：叙述视点(人称/全知vs限知)跳跃。"),
    ("Tone","语气不一致：情绪基调或语言风格突变。"),
]
S3_SYSP = "你是网文逻辑审查专家。逐条分析章节问题。直接输出中文分析。"
S3_JUDGE = (
    "你是逻辑评审专家。有两份匿名AI审查报告,独立评分(1-5):\n"
    "1=大量捏造矛盾/输出为空  2=存在明显遗漏或较多误报\n"
    "3=找出部分真实矛盾,有遗漏或少量误报  4=多数指出的矛盾真实存在,有原文引用\n"
    "5=全面审查,所有指出的矛盾均真实+有依据;若无矛盾则明确指出并给出置信度\n"
    "关键奖励: 正确判断'无明显矛盾'也得5分。捏造矛盾扣分。\n"
    "只输出JSON: {\"A\":整数,\"B\":整数}"
)

# ===== S4: 风格检测 (Narrative Shift + PEARL) =====
# NOTE: Perspective/Tone already in S3. S4 focuses on pacing/register/dialogue/style.
S4_DIMS = [
    ("PaceConsistency","节奏一致性：叙事快慢是否合理？有无突兀的节奏变化？"),
    ("RegisterConsistency","语域一致性：用词风格是否统一？有无跳出现代/古文词汇？"),
    ("DialogueStyle","对话一致性：角色说话方式是否符合人设？有无OOC？"),
    ("DescriptionDensity","描写密度：环境/心理描写分布是否均匀？有无某段过度堆砌？"),
    ("EmotionalArc","情绪曲线：章节的情绪起伏是否连贯？有无断崖式变化？"),
]
S4_SYSP = "你是网文风格审查专家。检测章节的叙事风格是否一致。逐条分析。"
S4_JUDGE = (
    "你是风格评审专家。有两份匿名AI审查报告,独立评分(1-5):\n"
    "1=大量误报/输出为空  2=明显遗漏或误报较多\n"
    "3=发现1-2个真实风格问题,有示例  4=发现3+个真实风格问题,有原文引用\n"
    "5=系统性分析,所有指出的问题均真实+有建议;若无风格问题则明确指出\n"
    "关键: 正确判断'风格一致'也得5分。捏造问题扣分。\n"
    "只输出JSON: {\"A\":整数,\"B\":整数}"
)

# ===== Shared infrastructure =====
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

def chat(sysp, user, max_tok=4096, temp=0.3):
    data = json.dumps({
        "messages": [{"role":"system","content":sysp},{"role":"user","content":user}],
        "max_tokens": max_tok, "temperature": temp,
    }).encode("utf-8")
    req = urllib.request.Request(f"http://127.0.0.1:{PORT}/v1/chat/completions",
                                 data, {"Content-Type":"application/json"})
    resp = json.loads(urllib.request.urlopen(req, timeout=300).read())
    raw = resp["choices"][0]["message"].get("content","")
    cleaned = re.sub(r"<think>.*?</think>\s*","", raw, flags=re.DOTALL)
    cleaned = re.sub(r"<think>.*$","", cleaned, flags=re.DOTALL)
    return cleaned.strip(), resp["usage"]

def pairwise_judge(review_a, review_b, dim_name, dim_desc, judge_sys):
    """Anonymous pairwise with position swap. Uses task-specific judge prompt."""
    ra = review_a[:2000] if review_a else "(empty)"
    rb = review_b[:2000] if review_b else "(empty)"
    s1 = _j(judge_sys, f"维度:{dim_name}({dim_desc})\n\n报告A:\n{ra}\n\n报告B:\n{rb}")
    s2 = _j(judge_sys, f"维度:{dim_name}({dim_desc})\n\n报告B:\n{rb}\n\n报告A:\n{ra}")
    return (s1.get("A",1)+s2.get("A",1))/2, (s1.get("B",1)+s2.get("B",1))/2

def _j(sysp, user):
    data = json.dumps({
        "messages": [{"role":"system","content":sysp},{"role":"user","content":user}],
        "max_tokens": 80, "temperature": 0.1,
    }).encode("utf-8")
    req = urllib.request.Request(f"http://127.0.0.1:{PORT}/v1/chat/completions",
                                 data, {"Content-Type":"application/json"})
    try:
        resp = json.loads(urllib.request.urlopen(req, timeout=60).read())
        raw = resp["choices"][0]["message"].get("content","")
        m = re.search(r'\{[^{}]*"A"\s*:\s*\d+[^{}]*"B"\s*:\s*\d+[^{}]*\}', raw)
        if m: return json.loads(m.group())
    except: pass
    return {"A":1,"B":1}

def _pointwise_judge(review, dim_name, dim_desc, judge_sys):
    """Score a single review (when the other is empty). Returns float 1-5."""
    r = review[:2000] if review else "(empty)"
    # Convert pairwise prompt to single: replace A/B scoring with single score
    single_sys = judge_sys.replace(
        "下面有两份匿名AI输出(A和B),按以下标准独立评分(1-5):",
        "下面有一份AI审查报告,按以下标准独立评分(1-5):"
    ).replace(
        '{"A":整数,"B":整数}',
        '{"score":整数}'
    )
    user = f"维度:{dim_name}({dim_desc})\n\n报告:\n{r}\n\n请评分。"
    data = json.dumps({
        "messages": [{"role":"system","content":single_sys},{"role":"user","content":user}],
        "max_tokens": 50, "temperature": 0.1,
    }).encode("utf-8")
    req = urllib.request.Request(f"http://127.0.0.1:{PORT}/v1/chat/completions",
                                 data, {"Content-Type":"application/json"})
    try:
        resp = json.loads(urllib.request.urlopen(req, timeout=60).read())
        raw = resp["choices"][0]["message"].get("content","")
        m = re.search(r'"score"\s*:\s*(\d+)', raw)
        if m: return float(m.group(1))
    except: pass
    return 3.0  # fallback

def run_phase(phase_name, models_list, dims, sys_prompt, user_prompt_template,
              judge_sys, chapter_text, wc, temp=0.3):
    """Execute one phase: generate + cross-evaluate. Returns (scores_dict, empty_counts)."""
    print(f"\n{'='*70}")
    print(f"  {phase_name}: {len(dims)}d x 2m")
    print(f"{'='*70}")
    t0 = time.time()

    # --- Generate ---
    all_outputs = {}
    empty_counts = {}  # {model_key: int}
    for m in models_list:
        mk = m["key"]
        print(f"\n  [{mk}] gen...")
        if not start(m): print("  [FAIL]"); continue
        print("  [OK]")
        try: chat("hi","OK",5)
        except: pass
        outputs = {}
        empty_n = 0
        for dim_name, dim_desc in dims:
            user = user_prompt_template(chapter_text, wc, dim_name, dim_desc)
            print(f"    [{dim_name:20s}] ", end="", flush=True)
            t1 = time.time()
            try:
                ct, usage = chat(sys_prompt, user, 4096, temp)
                dt = time.time() - t1
                ok = "E" if len(ct) < 20 else ""
                print(f"{usage['completion_tokens']}t {dt:.0f}s {len(ct)}c {ok}")
                outputs[dim_name] = ct
                if len(ct) < 20: empty_n += 1
            except Exception as e:
                print(f"[FAIL] {e}")
                outputs[dim_name] = ""
                empty_n += 1
        all_outputs[mk] = outputs
        empty_counts[mk] = empty_n

    # --- Cross-evaluate ---
    print(f"\n  Cross-eval...")
    scores = {mk: {"total":0.0,"count":0,"dims":{}} for mk in [m["key"] for m in models_list]}
    for judge_m in [QWEN_R, R1]:
        jk = judge_m["key"]
        print(f"    [{jk}] judging...")
        if not start(judge_m): print("    [FAIL]"); continue
        try: chat("hi","OK",5)
        except: pass
        for dim_name, dim_desc in dims:
            ra = all_outputs.get(models_list[0]["key"],{}).get(dim_name,"")
            rb = all_outputs.get(models_list[1]["key"],{}).get(dim_name,"")
            ra_ok = ra and len(ra) >= 20
            rb_ok = rb and len(rb) >= 20

            if not ra_ok and not rb_ok:
                sa, sb = 1.0, 1.0  # both empty → both 1
            elif not ra_ok:
                # only B has content: judge B individually, A gets 1
                sa = 1.0
                sb = _pointwise_judge(rb, dim_name, dim_desc, judge_sys)
            elif not rb_ok:
                sa = _pointwise_judge(ra, dim_name, dim_desc, judge_sys)
                sb = 1.0
            else:
                sa, sb = pairwise_judge(ra, rb, dim_name, dim_desc, judge_sys)

            mk_a, mk_b = models_list[0]["key"], models_list[1]["key"]
            scores[mk_a]["total"] += sa; scores[mk_a]["count"] += 1
            scores[mk_a]["dims"][dim_name] = scores[mk_a]["dims"].get(dim_name,0) + sa
            scores[mk_b]["total"] += sb; scores[mk_b]["count"] += 1
            scores[mk_b]["dims"][dim_name] = scores[mk_b]["dims"].get(dim_name,0) + sb

    print(f"    Phase time: {time.time()-t0:.0f}s")
    kill()
    return scores, empty_counts


# ===== MAIN =====
kill()
chap = CHAPTER.read_text(encoding="utf-8") if CHAPTER.exists() else "(none)"
wc = len(chap.replace("\n","").replace(" ",""))
if len(chap) > 3000: chap = chap[:3000] + "\n[...]"

t_start = time.time()
print("=" * 70)
print("  P0-2 FULL RETEST: S1+S3+S4 (new rubric, 2k chapter, Qwen3.5 think=OFF)")
print("=" * 70)

# S1: Qwen3.5 think=OFF vs R1
s1_sc, s1_skip = run_phase("S1:Creative", [QWEN_R, R1], S1_DIMS, S1_SYSP,
    lambda t,w,d,dd: f"## {d}\n{dd}\n\n## 当前章节({w}字):\n{t}\n\n请为下一章提供3个创意方向。",
    S1_JUDGE, chap, wc, temp=0.7)

# S3: Qwen3.5 think=OFF vs R1
s3_sc, s3_skip = run_phase("S3:Logic", [QWEN_R, R1], S3_DIMS, S3_SYSP,
    lambda t,w,d,dd: f"## {d}\n{dd}\n\n## 章节({w}字):\n{t}",
    S3_JUDGE, chap, wc, temp=0.3)

# S4: Qwen3.5 think=OFF vs R1
s4_sc, s4_skip = run_phase("S4:Style", [QWEN_R, R1], S4_DIMS, S4_SYSP,
    lambda t,w,d,dd: f"## {d}\n{dd}\n\n## 章节({w}字):\n{t}",
    S4_JUDGE, chap, wc, temp=0.3)

# ===== REPORT =====
elapsed = time.time() - t_start
print(f"\n{'='*70}")
print(f"  P0-2 FULL RETEST ({elapsed:.0f}s)  [new rubric + 2k chapter + think=OFF]")
print(f"{'='*70}")

def show(name, scores, empties, dims, models):
    print(f"\n  [{name}]  empty={empties}")
    for mk in [m["key"] for m in models]:
        c = max(scores.get(mk,{}).get("count",0), 1)
        a = scores.get(mk,{}).get("total",0)/c
        print(f"    {mk}: avg={a:.2f}/5")
        for dn,_ in dims:
            s = round(scores.get(mk,{}).get("dims",{}).get(dn,0)/max(c/len(dims),1),1) if c else 0
            bar = "#"*int(s)+"-"*(5-int(s))
            print(f"      {dn:20s} {s}/5 {bar}")
    w = max([m["key"] for m in models], key=lambda k: scores.get(k,{}).get("total",0)/max(scores.get(k,{}).get("count",1),1))
    print(f"    => {w}")

show("S1 Creative", s1_sc, s1_skip, S1_DIMS, [QWEN_R, R1])
show("S3 Logic", s3_sc, s3_skip, S3_DIMS, [QWEN_R, R1])
show("S4 Style", s4_sc, s4_skip, S4_DIMS, [QWEN_R, R1])

print(f"\n  [OVERALL] ({elapsed:.0f}s)")
for mk in ["Qwen3.5","R1"]:
    t=0.0; c=0; e=0
    for sc,sk in [(s1_sc,s1_skip),(s3_sc,s3_skip),(s4_sc,s4_skip)]:
        if mk in sc: t+=sc[mk]["total"]; c+=sc[mk]["count"]
        e+=sk.get(mk,0)
    a=t/max(c,1)
    print(f"    {mk:10s} {a:.2f}/5 {'='*int(a*4)+'-'*(20-int(a*4))} ({t:.0f}/{c}) e={e}")

print(f"\n[DONE]")

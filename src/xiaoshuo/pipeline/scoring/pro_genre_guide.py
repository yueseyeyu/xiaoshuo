#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
pro_genre_guide.py — Pro API 类型指导生成 (v11)
===============================================
功能: 聚合题材级分析数据 → 调用 DeepSeek Pro/Flash API → 生成综合类型写作指导。

设计原则:
  1. 单次 API 调用（~0.5 元/题材），避免迭代成本
  2. 输入 = 题材内所有书籍的 rhythm CSV 聚合统计
  3. 输出 = Markdown 写作指导报告，含类型定位/读者预期/爽点模式/避坑清单

用法:
  python -m xiaoshuo.pipeline.scoring.pro_genre_guide --genre 末世
  python -m xiaoshuo.pipeline.scoring.pro_genre_guide --all          # 全题材

依赖:
  - config.yaml: model_orchestration.models.external_api.deepseek
  - secrets.yaml: deepseek.api_key (不存在时跳过，不阻塞管线)
"""

import json
import sys
import time
import urllib.request
import csv
from datetime import datetime
from pathlib import Path
from xiaoshuo import PROJECT_ROOT
from xiaoshuo.infra.config_manager import get_deepseek_config
from xiaoshuo.pipeline.paths import rhythm_dir as _rhythm_dir


# ── 路径 ──
_REPORTS_DIR = PROJECT_ROOT / "data" / "reports"
_PROMPT_PATH = PROJECT_ROOT / "assets" / "prompts" / "pro_genre_guide.txt"




def _load_deepseek_config():
    """Normalize DeepSeek API config from SSOT (config_manager).
    Returns dict with keys: base_url, model, api_key, max_tokens, temperature, timeout
    or None if disabled or key missing."""
    ds = get_deepseek_config()
    if ds is None:
        return None
    return {
        "base_url": ds.get("base_url", "https://api.deepseek.com"),
        "model": ds.get("model", "deepseek-chat"),
        "api_key": ds["api_key"],
        "max_tokens": ds.get("max_tokens", 2048),
        "temperature": ds.get("temperature", 0.3),
        "timeout": ds.get("timeout", 60),
    }


def _load_guide_prompt() -> str | None:
    """Load custom prompt from assets/prompts/pro_genre_guide.txt.
    Returns None if the prompt file doesn't exist (fatal — no built-in fallback)."""
    if _PROMPT_PATH.exists():
        return _PROMPT_PATH.read_text(encoding="utf-8").strip()
    print(f"  [FAIL] Prompt template not found: {_PROMPT_PATH}")
    print(f"          请创建该文件，参考内置默认模板。")
    return None


# ── Quality validation thresholds ──
_MIN_GUIDE_CHARS = 500       # Minimum content length (too short = likely API error)
_REQUIRED_SECTIONS = ["## 1.", "## 2.", "## 3.", "## 4.", "## 5.", "## 6."]
_MIN_REQUIRED_SECTIONS = 4   # At least 4 of 6 required sections must be present


def _validate_guide(content: str) -> bool:
    """Validate guide quality: minimum length + required sections coverage."""
    if len(content) < _MIN_GUIDE_CHARS:
        print(f"  [FAIL] Guide too short ({len(content)} chars, min {_MIN_GUIDE_CHARS})")
        return False
    found = sum(1 for s in _REQUIRED_SECTIONS if s in content)
    if found < _MIN_REQUIRED_SECTIONS:
        print(f"  [FAIL] Only {found}/{len(_REQUIRED_SECTIONS)} required sections found (min {_MIN_REQUIRED_SECTIONS})")
        return False
    print(f"  [OK] Quality check: {len(content)} chars, {found}/{len(_REQUIRED_SECTIONS)} sections")
    return True


# ── Cost tracking ──
_cost_tracker = {"total_calls": 0, "total_tokens_in": 0, "total_tokens_out": 0, "total_time_s": 0.0}


def get_cost_summary() -> dict:
    """Return cumulative API cost tracking stats."""
    return dict(_cost_tracker)


def reset_cost_tracker():
    """Reset cumulative cost tracking."""
    for k in _cost_tracker:
        _cost_tracker[k] = 0 if k != "total_time_s" else 0.0


def _aggregate_genre(genre):
    """Aggregate all rhythm CSVs for a genre into summary statistics."""
    rhythm_d = _rhythm_dir(genre)
    if not rhythm_d.exists():
        return None

    csv_files = sorted(rhythm_d.glob("rhythm_*.csv"))
    if not csv_files:
        return None

    all_rows = []
    book_summaries = []

    for csv_path in csv_files:
        book_name = csv_path.stem.replace("rhythm_", "")
        with open(csv_path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        all_rows.extend(rows)

        # Per-book summary
        wcs = [float(r.get("wc", 0) or 0) for r in rows]
        intensities = [float(r.get("pleasure_intensity", 0) or 0) for r in rows]
        # Sub-type distribution
        sub_counter = {}
        for r in rows:
            st = r.get("dominant_sub", "")
            if st and st != "":
                sub_counter[st] = sub_counter.get(st, 0) + 1
        top_subs = sorted(sub_counter, key=sub_counter.get, reverse=True)[:3]

        book_summaries.append({
            "name": book_name,
            "chapters": len(rows),
            "avg_wc": sum(wcs) / max(len(wcs), 1),
            "avg_intensity": sum(intensities) / max(len(intensities), 1),
            "pleasure_density": sum(1 for r in rows if r.get("pleasure_type", "none") != "none") / max(len(rows), 1),
            "top_subs": ", ".join(top_subs),
        })

    if not all_rows:
        return None

    # Global aggregates
    total = len(all_rows)
    wc_vals = [float(r.get("wc", 0) or 0) for r in all_rows]
    dr_vals = [float(r.get("dialogue_ratio", 0) or 0) for r in all_rows]
    pi_vals = [float(r.get("pleasure_intensity", 0) or 0) for r in all_rows]
    hook_vals = [float(r.get("hook_density", 0) or 0) for r in all_rows]
    conflict_vals = [float(r.get("conflict_density", 0) or 0) for r in all_rows]

    # Sub-type global distribution
    global_sub_counter = {}
    pleasure_level_counter = {"small": 0, "medium": 0, "large": 0}
    for r in all_rows:
        st = r.get("dominant_sub", "")
        if st and st != "":
            global_sub_counter[st] = global_sub_counter.get(st, 0) + 1
        pl = r.get("pleasure_level", "")
        if pl in pleasure_level_counter:
            pleasure_level_counter[pl] += 1

    top_subtypes = sorted(global_sub_counter, key=global_sub_counter.get, reverse=True)[:3]
    pl_total = sum(pleasure_level_counter.values()) or 1

    avg_intensity = sum(pi_vals) / max(total, 1)
    # Label pleasure density
    pd = sum(1 for r in all_rows if r.get("pleasure_type", "none") != "none") / max(total, 1)
    if pd >= 0.7:
        pd_label = "高密度"
    elif pd >= 0.4:
        pd_label = "中密度"
    else:
        pd_label = "低密度"

    # Conflict density label
    avg_cd = sum(conflict_vals) / max(total, 1)
    if avg_cd >= 0.7:
        cd_label = "高冲突"
    elif avg_cd >= 0.3:
        cd_label = "中冲突"
    else:
        cd_label = "低冲突"

    avg_hook = sum(hook_vals) / max(total, 1)

    # Book details string
    book_lines = []
    for b in book_summaries:
        book_lines.append(
            f"- {b['name']}: {b['chapters']}章, "
            f"平均{int(b['avg_wc'])}字/章, "
            f"爽点密度{b['pleasure_density']:.2f}, "
            f"强度{b['avg_intensity']:.1f}, "
            f"主流类型: {b['top_subs']}"
        )

    return {
        "genre": genre,
        "book_count": len(book_summaries),
        "total_chaps": total,
        "avg_wc": int(sum(wc_vals) / max(total, 1)),
        "dialogue_ratio": sum(dr_vals) / max(total, 1),
        "pleasure_density": pd,
        "pleasure_density_label": pd_label,
        "avg_intensity": round(avg_intensity, 1),
        "conflict_rate": round(sum(1 for r in all_rows if r.get("conflict", "false") == "true") / max(total, 1), 2),
        "avg_hook": round(avg_hook, 1),
        "conflict_density_label": cd_label,
        "top_subtypes": ", ".join(top_subtypes) if top_subtypes else "（未识别）",
        "small_pct": pleasure_level_counter["small"] / pl_total * 100,
        "medium_pct": pleasure_level_counter["medium"] / pl_total * 100,
        "large_pct": pleasure_level_counter["large"] / pl_total * 100,
        "book_details": "\n".join(book_lines) if book_lines else "（无明细）",
    }


def _call_deepseek_api(prompt: str, config: dict) -> str | None:
    """Call DeepSeek chat API with the given prompt. Returns response text or None.
    v11.1: 3-retry with exponential backoff."""
    url = f"{config['base_url']}/v1/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {config['api_key']}",
    }
    payload = {
        "model": config["model"],
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": config["max_tokens"],
        "temperature": config["temperature"],
    }

    for attempt in range(3):
        try:
            t0 = time.time()
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers=headers,
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=config["timeout"]) as resp:
                body = json.loads(resp.read().decode("utf-8"))
            dt = time.time() - t0
            usage = body.get("usage", {})
            tokens_in = usage.get("prompt_tokens", 0)
            tokens_out = usage.get("completion_tokens", 0)
            # Update cost tracker
            _cost_tracker["total_calls"] += 1
            _cost_tracker["total_tokens_in"] += tokens_in
            _cost_tracker["total_tokens_out"] += tokens_out
            _cost_tracker["total_time_s"] += dt
            print(f"  [API] {config['model']}: {dt:.1f}s ({tokens_in} in / {tokens_out} out)")
            return body["choices"][0]["message"]["content"]
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="replace")[:200]
            if attempt < 2:
                time.sleep(2 * (attempt + 1))
            else:
                print(f"  [FAIL] DeepSeek API HTTP {e.code}: {err_body}")
        except Exception as e:
            if attempt < 2:
                time.sleep(2 * (attempt + 1))
            else:
                print(f"  [FAIL] DeepSeek API call failed: {e}")
    return None


def generate_genre_guide(genre: str, force: bool = False) -> str | None:
    """Generate a Pro API genre writing guide for the given genre.
    Returns the path to the generated guide if successful, None otherwise.

    Args:
        genre: Genre name (e.g. '末世')
        force: If True, regenerate even if guide already exists

    Returns:
        Path to the generated Markdown guide, or None
    """
    # ── Check output path ──
    genre_report_dir = _REPORTS_DIR / genre
    genre_report_dir.mkdir(parents=True, exist_ok=True)
    out_path = genre_report_dir / "pro_genre_guide.md"

    if out_path.exists() and not force:
        print(f"  [SKIP] Guide already exists: {out_path} (use --force to regenerate)")
        return str(out_path)

    # ── Load API config ──
    api_config = _load_deepseek_config()
    if api_config is None:
        print(f"  [SKIP] DeepSeek API not configured. Create secrets.yaml with deepseek.api_key to enable.")
        return None

    # ── Aggregate genre data ──
    data = _aggregate_genre(genre)
    if data is None:
        print(f"  [FAIL] No rhythm data found for genre '{genre}'")
        return None

    print(f"  [Pro] Generating genre guide for '{genre}' ({data['book_count']} books, "
          f"{data['avg_wc']} avg wc, {data['pleasure_density_label']})...")

    # ── Build prompt ──
    template = _load_guide_prompt()
    if template is None:
        return None
    prompt = template.format(**data)

    # ── Call API ──
    response = _call_deepseek_api(prompt, api_config)
    if response is None:
        return None

    # ── Quality validation ──
    if not _validate_guide(response):
        print(f"  [FAIL] Quality validation failed for '{genre}'. Guide not saved.")
        return None

    # ── Save guide ──
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    full_guide = f"""# {genre}类型写作指导（Pro API）

> 基于 {data['book_count']} 本校勘书籍 × {data.get('total_chaps', 0)} 章的聚合分析
> 生成时间: {ts}

---

{response}

---

*本指导由 DeepSeek Pro API 辅助生成，结合自动分析的聚合数据与AI的类型理解。仅供参考决策，不替代作者创意。*
"""
    out_path.write_text(full_guide, encoding="utf-8")
    print(f"  [OK] Guide saved: {out_path}")
    return str(out_path)


def generate_all_genres(force: bool = False):
    """Generate guides for all genres with rhythm data."""
    processed_dir = PROJECT_ROOT / "data" / "processed"
    if not processed_dir.exists():
        print("[FAIL] No processed data directory found")
        return

    genres = [d.name for d in processed_dir.iterdir() if d.is_dir() and (d / "rhythm").exists()]
    genres.sort()
    results = {}
    for genre in genres:
        result = generate_genre_guide(genre, force=force)
        results[genre] = "OK" if result else "SKIP/FAIL"
    print(f"\n[DONE] Pro genre guides: {sum(1 for v in results.values() if v == 'OK')}/{len(results)} generated")
    for g, r in results.items():
        print(f"  {r} {g}")
    # ── Cost summary ──
    cs = get_cost_summary()
    if cs["total_calls"] > 0:
        ds_cfg = get_deepseek_config()
        model_name = ds_cfg.get("model", "?") if ds_cfg else "?"
        print(f"\n  [Cost] {model_name}: {cs['total_calls']} calls, "
              f"{cs['total_tokens_in']} in / {cs['total_tokens_out']} out, "
              f"{cs['total_time_s']:.1f}s total")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Pro API 类型指导生成")
    parser.add_argument("--genre", type=str, default=None, help="题材名称，如 末世")
    parser.add_argument("--all", action="store_true", help="全题材生成")
    parser.add_argument("--force", action="store_true", help="强制重新生成")
    args = parser.parse_args()

    if args.all:
        generate_all_genres(force=args.force)
    elif args.genre:
        generate_genre_guide(args.genre, force=args.force)
    else:
        print("请指定 --genre 或 --all")
        sys.exit(1)
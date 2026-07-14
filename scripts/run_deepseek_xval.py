#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
DeepSeek交叉验证批量执行脚本
=============================
读取所有 _deepseek_xval.md prompt 文件，通过 DeepSeek API 逐书评分，
保存结果为 {书名}_deepseek_result.json。
"""
import json
import os
import sys
import re
import time
from pathlib import Path
import requests

PROJECT = Path(r"d:\Code\xiaoshuo")
PROMPT_DIR = PROJECT / "data" / "golden" / "末世" / "tier3" / "deepseek_xval_prompts"
SECRETS_FILE = PROJECT / "secrets.yaml"

# DeepSeek API config
API_BASE = "https://api.deepseek.com"
MODEL = "deepseek-chat"
MAX_TOKENS = 4096  # 输出最多4096 tokens (15章JSON)
TEMPERATURE = 0.0
TIMEOUT = 180  # 大prompt需要更长时间

def load_api_key():
    """从secrets.yaml加载API key."""
    with open(SECRETS_FILE, 'r', encoding='utf-8') as f:
        content = f.read()
    match = re.search(r'api_key:\s*"([^"]+)"', content)
    if match:
        return match.group(1)
    raise RuntimeError("API key not found in secrets.yaml")

def call_deepseek(system_prompt, user_prompt, api_key):
    """调用DeepSeek API."""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "max_tokens": MAX_TOKENS,
        "temperature": TEMPERATURE,
    }
    
    resp = requests.post(
        f"{API_BASE}/v1/chat/completions",
        headers=headers,
        json=payload,
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()

def extract_json_from_response(text):
    """从DeepSeek返回中提取JSON数组."""
    # 尝试匹配 ```json ... ``` 代码块
    m = re.search(r'```json\s*([\s\S]*?)\s*```', text)
    if m:
        return m.group(1).strip()
    # 尝试匹配裸JSON数组
    m = re.search(r'\[\s*\{[\s\S]*\}\s*\]', text)
    if m:
        return m.group(0).strip()
    return text.strip()

def parse_prompt_file(filepath):
    """
    解析prompt文件，提取系统提示词和完整内容。
    返回: (system_prompt, full_content) 或 (None, full_content)
    """
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 提取系统提示词 (从开头到"## 待评分章节"之前)
    m = re.search(r'^(.*?)(?=##\s+待评分章节)', content, re.DOTALL)
    if m:
        system_prompt = m.group(1).strip()
        return system_prompt, content
    return None, content

def process_all_books(api_key, dry_run=False):
    """处理所有书籍的prompt文件."""
    prompt_files = sorted(PROMPT_DIR.glob("*_deepseek_xval.md"))
    
    results_summary = {}
    
    for pf in prompt_files:
        book_name = pf.name.replace("_deepseek_xval.md", "")
        result_file = PROMPT_DIR / f"{book_name}_deepseek_result.json"
        
        print(f"\n{'='*60}")
        print(f"[BOOK] {book_name}")
        print(f"  Prompt: {pf.name} ({pf.stat().st_size/1024:.0f} KB)")
        
        if result_file.exists():
            print(f"  [SKIP] Result already exists: {result_file.name}")
            continue
        
        if dry_run:
            print(f"  [DRY RUN] Would process {book_name}")
            continue
        
        try:
            system_prompt, full_content = parse_prompt_file(pf)
            print(f"  [INFO] Sending to DeepSeek API...")
            print(f"  [INFO] Content size: {len(full_content)/1024:.0f} KB, ~{len(full_content)//2} tokens est.")
            
            response = call_deepseek(system_prompt, full_content, api_key)
            
            # 提取响应内容
            content_text = response["choices"][0]["message"]["content"]
            usage = response.get("usage", {})
            print(f"  [OK] API response: {usage.get('prompt_tokens', '?')} prompt tokens, "
                  f"{usage.get('completion_tokens', '?')} completion tokens")
            
            # 提取JSON
            json_text = extract_json_from_response(content_text)
            try:
                chapters = json.loads(json_text)
                print(f"  [OK] Parsed {len(chapters)} chapters")
            except json.JSONDecodeError as e:
                print(f"  [WARN] JSON parse error: {e}")
                print(f"  [WARN] Raw response (first 500 chars): {content_text[:500]}")
                # 保存原始响应以便调试
                raw_file = PROMPT_DIR / f"{book_name}_deepseek_raw.txt"
                with open(raw_file, 'w', encoding='utf-8') as f:
                    f.write(content_text)
                print(f"  [INFO] Raw response saved to {raw_file.name}")
                results_summary[book_name] = "JSON_PARSE_ERROR"
                continue
            
            # 保存结果
            with open(result_file, 'w', encoding='utf-8') as f:
                json.dump(chapters, f, ensure_ascii=False, indent=2)
            print(f"  [OK] Result saved: {result_file.name}")
            results_summary[book_name] = f"OK ({len(chapters)} chapters)"
            
            # 等待1秒避免API限流
            time.sleep(1)
            
        except requests.exceptions.HTTPError as e:
            print(f"  [FAIL] HTTP error: {e}")
            if hasattr(e, 'response') and e.response is not None:
                print(f"  [FAIL] Response: {e.response.text[:500]}")
            results_summary[book_name] = f"HTTP_ERROR: {e}"
        except requests.exceptions.Timeout:
            print(f"  [FAIL] Timeout after {TIMEOUT}s")
            results_summary[book_name] = "TIMEOUT"
        except Exception as e:
            print(f"  [FAIL] {type(e).__name__}: {e}")
            results_summary[book_name] = f"ERROR: {e}"
    
    return results_summary

def main():
    dry_run = "--dry-run" in sys.argv
    
    if dry_run:
        print("[DRY RUN MODE] Will not make actual API calls")
    
    api_key = load_api_key()
    print(f"[OK] API key loaded")
    print(f"[INFO] API: {API_BASE}, Model: {MODEL}")
    
    results = process_all_books(api_key, dry_run=dry_run)
    
    print(f"\n{'='*60}")
    print("[SUMMARY]")
    for book, status in results.items():
        print(f"  {book}: {status}")

if __name__ == "__main__":
    main()
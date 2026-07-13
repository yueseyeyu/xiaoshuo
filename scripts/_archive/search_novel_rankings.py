#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
联网搜索30本末世小说的口碑评价和排名
使用代理 127.0.0.1:33210
通过 Google Custom Search / DuckDuckGo / Bing 搜索
"""
import json, sys, time, urllib.request, urllib.parse, re
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')

# 30本末世小说完整列表
NOVELS = [
    # S级 (5本)
    "地球游戏场", "异兽迷城", "末世之深渊召唤师", "末世大回炉", "神秘尽头",
    # A级 (8本)
    "世界末日从考试不及格开始", "从红月开始", "废土崛起", "末世召唤狂潮",
    "末世魔神游戏", "末日拼图游戏", "黑暗血时代", "全球变异从灾厄降临开始",
    # B+级 (5本)
    "全球进化", "恐慌沸腾", "我在末世有套房", "狩魔手记", "黑暗文明",
    # B级 (5本)
    "我的女友是丧尸", "末日蟑螂", "灾厄纪元", "重卡战车在末世", "黑暗王者",
    # B-级 (4本)
    "第九特区", "我在末世种个田", "末世超级商人", "限制级末日症候",
    # C级 (2本)
    "蹉跎", "黑暗末日",
    # 未分级 (1本)
    "我的末世领地",
]

PROXY = "127.0.0.1:33210"
PROXY_HANDLER = urllib.request.ProxyHandler({
    "http": f"http://{PROXY}",
    "https": f"http://{PROXY}",
})
OPENER = urllib.request.build_opener(PROXY_HANDLER)
OPENER.addheaders = [('User-Agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36')]


def search_bing(query: str, count: int = 5) -> list:
    """通过Bing搜索，返回结果摘要"""
    url = f"https://www.bing.com/search?q={urllib.parse.quote(query)}&count={count}"
    try:
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept-Language': 'zh-CN,zh;q=0.9',
        })
        resp = OPENER.open(req, timeout=15)
        html = resp.read().decode('utf-8', errors='ignore')
        # 提取搜索结果摘要
        results = []
        # Bing搜索结果在 <li class="b_algo"> 中
        blocks = re.findall(r'<li class="b_algo">(.*?)</li>', html, re.DOTALL)
        for block in blocks[:count]:
            # 提取标题
            title_match = re.search(r'<h2>(.*?)</h2>', block, re.DOTALL)
            title = re.sub(r'<[^>]+>', '', title_match.group(1)).strip() if title_match else ""
            # 提取摘要
            desc_match = re.search(r'<p[^>]*>(.*?)</p>', block, re.DOTALL)
            desc = re.sub(r'<[^>]+>', '', desc_match.group(1)).strip() if desc_match else ""
            if title or desc:
                results.append({"title": title, "desc": desc})
        return results
    except Exception as e:
        return [{"title": "ERROR", "desc": str(e)}]


def search_novel(novel_name: str) -> dict:
    """搜索单本小说的评价"""
    queries = [
        f'"{novel_name}" 小说 评价 口碑 排名',
        f'"{novel_name}" 末世 豆瓣 知乎 评分',
    ]

    all_results = []
    for q in queries:
        results = search_bing(q, count=5)
        all_results.extend(results)
        time.sleep(0.5)

    # 提取关键信息
    combined_text = " ".join([r.get("desc", "") + r.get("title", "") for r in all_results])

    # 尝试提取评分
    scores = re.findall(r'(\d+\.\d+)\s*分', combined_text)
    # 尝试提取排名
    ranks = re.findall(r'第(\d+)名|排名.*?(\d+)|TOP\s*(\d+)', combined_text, re.IGNORECASE)

    return {
        "novel": novel_name,
        "search_results": all_results[:8],
        "extracted_scores": scores[:5] if scores else [],
        "combined_text_preview": combined_text[:500],
    }


def main():
    output_dir = Path(__file__).parent.parent / "data" / "reports" / "末世" / "novel_rankings"
    output_dir.mkdir(parents=True, exist_ok=True)

    all_data = {}
    for i, novel in enumerate(NOVELS):
        print(f"[{i+1}/{len(NOVELS)}] 搜索: {novel} ...", flush=True)
        data = search_novel(novel)
        all_data[novel] = data
        # 打印简要结果
        for r in data["search_results"][:3]:
            title = r.get("title", "")[:60]
            desc = r.get("desc", "")[:120]
            print(f"  - {title}")
            print(f"    {desc}")
        if data["extracted_scores"]:
            print(f"  评分: {data['extracted_scores']}")
        print()

    # 保存完整结果
    output_file = output_dir / "all_novels_search_results.json"
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(all_data, f, ensure_ascii=False, indent=2)
    print(f"\n完整结果已保存: {output_file}")


if __name__ == "__main__":
    main()

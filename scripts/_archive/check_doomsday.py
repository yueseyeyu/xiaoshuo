"""检查末日乐园.txt文件信息 - 自动检测编码"""
import re

path = "books/in/末日乐园.txt"

# 尝试多种编码
for enc in ["gbk", "gb18030", "utf-8-sig", "big5", "utf-16"]:
    try:
        with open(path, "r", encoding=enc) as f:
            text = f.read(10000)
        print(f"编码 {enc} 成功读取前10000字符")
        # 用成功编码读取全文
        with open(path, "r", encoding=enc) as f:
            text = f.read()
        break
    except (UnicodeDecodeError, UnicodeError) as e:
        print(f"编码 {enc} 失败: {e}")
        continue
else:
    print("所有编码都失败!")
    exit(1)

# 基本信息
lines = text.split("\n")
print(f"\n总行数: {len(lines)}")
print(f"总字符数: {len(text)}")
print(f"文件大小: {len(text.encode('utf-8')) / 1024:.0f} KB")

# 头部
print("\n=== 文件开头20行 ===")
for line in lines[:20]:
    print(line[:100])

# 尾部
print("\n=== 文件末尾15行 ===")
for line in lines[-15:]:
    print(line[:100])

# 章节匹配 - 尝试多种模式
patterns = [
    (r"第\d+章", "第N章"),
    (r"第[一二三四五六七八九十百千零]+章", "第中文数字章"),
    (r"Chapter\s*\d+", "Chapter N"),
    (r"^\s*\d+[\.、]\s*", "数字开头"),
    (r"^\s*Chapter", "Chapter开头"),
]

for pat, name in patterns:
    matches = re.findall(pat, text, re.MULTILINE)
    print(f"\n模式 '{name}': {len(matches)} 个匹配")
    if matches:
        print(f"  前5个: {matches[:5]}")
        if len(matches) > 5:
            print(f"  后5个: {matches[-5:]}")

# 检查是否有"完本"/"完结"/"大结局"等标记
end_markers = ["完本", "完结", "大结局", "全书完", "全文完", "后记", "完"]
for marker in end_markers:
    if marker in text:
        pos = text.rfind(marker)
        context = text[max(0, pos-80):pos+80]
        print(f"\n找到 '{marker}' 在位置 {pos}, 上下文: ...{context}...")

"""统计三本新书的章节数 - 自动检测编码"""
import re
import os

books = [
    ("data/raw/novels/末世/《第一序列》（校对版全本）作者：会说话的肘子.txt", "第一序列"),
    ("data/raw/novels/末世/《长夜余火》（校对版全本）作者：爱潜水的乌贼.txt", "长夜余火"),
    ("data/raw/novels/末世/末日乐园.txt", "末日乐园"),
]

for path, name in books:
    # 尝试多种编码
    text = None
    for enc in ["utf-8", "gbk", "gb18030", "utf-8-sig"]:
        try:
            with open(path, "r", encoding=enc) as f:
                text = f.read()
            print(f"  编码: {enc}")
            break
        except (UnicodeDecodeError, UnicodeError):
            continue
    
    if text is None:
        print(f"{name}: 编码检测失败!")
        continue
    
    # 章节匹配
    chapters = re.findall(r"第\d+章", text)
    ch_count = len(chapters)
    
    # 字数估算
    chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', text))
    
    print(f"{name}:")
    print(f"  章节数: {ch_count}")
    print(f"  中文字: {chinese_chars:,}")
    print(f"  文件大小: {os.path.getsize(path) / 1024 / 1024:.1f} MB")
    
    # 计算不同采样率的章节数
    print(f"  --- 采样量参考 ---")
    if ch_count > 0:
        print(f"  当前S级配置(50章): {50/ch_count*100:.1f}% 覆盖率")
        print(f"  10%采样: {int(ch_count * 0.1)}章")
        print(f"  100章采样: {100/ch_count*100:.1f}% 覆盖率")
    print()

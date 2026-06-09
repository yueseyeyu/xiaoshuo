"""将所有 GBK 编码的 txt 转为 UTF-8"""
from pathlib import Path

NOVELS_DIR = Path(__file__).parent.parent / "data" / "novels"

for f in NOVELS_DIR.glob("*.txt"):
    raw = f.read_bytes()
    # 检测并转换
    try:
        raw.decode('utf-8')
        print(f"[SKIP] 已是UTF-8: {f.name}")
        continue
    except:
        pass
    
    try:
        text = raw.decode('gbk')
        f.write_text(text, encoding='utf-8')
        print(f"[OK]   GBK->UTF-8: {f.name}")
    except Exception as e:
        print(f"[FAIL] {f.name}: {e}")

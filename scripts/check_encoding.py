"""检测 novels 目录下所有txt文件编码"""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

NOVELS_DIR = Path(__file__).parent.parent / "data" / "novels"

for f in sorted(NOVELS_DIR.glob("*.txt")):
    raw = f.read_bytes()
    # 检测 BOM
    if raw[:3] == b'\xef\xbb\xbf':
        enc = "UTF-8-BOM"
    elif raw[:2] == b'\xff\xfe':
        enc = "UTF-16-LE"
    elif raw[:2] == b'\xfe\xff':
        enc = "UTF-16-BE"
    else:
        # 尝试 UTF-8
        try:
            raw.decode('utf-8')
            enc = "UTF-8"
        except:
            try:
                raw.decode('gbk')
                enc = "GBK"
            except:
                enc = "UNKNOWN"
    
    size_mb = len(raw) / 1024 / 1024
    lines = raw.count(b'\n')
    print(f"[{enc:12s}] {size_mb:6.1f}MB  {lines:5d}行  {f.name}")

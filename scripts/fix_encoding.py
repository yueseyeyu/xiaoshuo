"""Convert GBK/UTF-16 novel files to UTF-8. Safe: backs up file size before conversion."""
from pathlib import Path

ROOT = Path(__file__).parent.parent / "data" / "raw" / "novels"

for f in sorted(ROOT.glob("*.txt")):
    raw = f.read_bytes()
    # Detect
    text = None
    src_enc = None
    for enc in ["utf-8", "gbk", "utf-16-le", "utf-16-be"]:
        try:
            text = raw.decode(enc)
            src_enc = enc
            break
        except (UnicodeDecodeError, UnicodeError):
            continue
    if text is None:
        print(f"[FAIL] {f.name}")
        continue

    wc = len(text.replace("\n", "").replace(" ", ""))
    if src_enc == "utf-8":
        print(f"[SKIP] {f.name:40s} UTF-8 {wc:,}c")
        continue

    # Convert to UTF-8
    f.write_text(text, encoding="utf-8")
    print(f"[CONV] {f.name:40s} {src_enc} -> utf-8  {wc:,}c")

print("\n[DONE] All novels are now UTF-8")

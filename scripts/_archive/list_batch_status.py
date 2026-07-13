#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""列出每本书的批次目录和评分进度。"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')

import ai_annotate as aa

aa.BATCH_SIZE = aa.DEFAULT_BATCH_SIZE

for b in aa.BOOKS:
    bd = aa.get_book_batch_dir(b)
    batches = len(list(bd.glob("new_*.json"))) if bd.exists() else 0
    scored = len(list(bd.glob("scores_new_*.json"))) if bd.exists() else 0
    print(f"{b}|{batches}|{scored}")

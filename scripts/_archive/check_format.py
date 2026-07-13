#!/usr/bin/env python
# -*- coding: utf-8 -*-
import sys, os, json
from pathlib import Path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
sys.path.insert(0, os.path.dirname(__file__))
if sys.platform == "win32": sys.stdout.reconfigure(encoding='utf-8')
import ai_annotate; ai_annotate.BATCH_SIZE = 2
from ai_annotate import get_book_batch_dir
VALID_E = {'日常','紧张','爽快','悬疑','压抑','感动','热血','悲壮','温馨'}
VALID_C = {'low','medium','high'}
VALID_P = {'slow','medium','fast'}
VALID_H = {'weak','medium','strong'}
for book in ['我在末世种个田','重卡战车在末世','长夜余火','全球变异，从灾厄降临开始']:
    bdir = get_book_batch_dir(book)
    sfs = sorted(bdir.glob('scores_*.json'))
    errs = 0
    total = 0
    for sf in sfs:
        with open(sf,'r',encoding='utf-8') as f: scores = json.load(f)
        for s in scores:
            total += 1
            if s.get('ai_emotion') not in VALID_E: errs += 1
            elif s.get('ai_conflict') not in VALID_C: errs += 1
            elif s.get('ai_pace') not in VALID_P: errs += 1
            elif s.get('ai_hook') not in VALID_H: errs += 1
    print(f'{book}: {errs}/{total} 有格式错误')

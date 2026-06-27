#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Patch prototype/index.html to load library data from library_data.json."""
import re
from pathlib import Path

HTML = Path("prototype/index.html")
text = HTML.read_text(encoding="utf-8")

# Replace static libraryBooks array with let declaration
# Match from "const libraryBooks = [" up to the following "];"
text = re.sub(
    r"const libraryBooks = \[.*?\];\s*",
    "let libraryBooks = [];\n",
    text,
    count=1,
    flags=re.DOTALL,
)

# Replace static genres array
# Use a non-greedy match for the array content between brackets
text = re.sub(
    r'const genres = \[[^\]]*\];',
    'let genres = [];',
    text,
    count=1,
)

# Insert loadLibraryData function right after the genres line, before tagPool if present
load_fn = '''
    async function loadLibraryData() {
      try {
        const res = await fetch('library_data.json');
        if (!res.ok) throw new Error('fetch failed');
        const data = await res.json();
        libraryBooks = data.books || [];
        genres = data.genres || [];
      } catch (e) {
        console.error('[FAIL] load library data:', e);
        libraryBooks = [];
        genres = [];
      }
    }
'''

# Find position right after "let genres = [];" line
insert_marker = "let genres = [];"
if insert_marker in text:
    pos = text.find(insert_marker) + len(insert_marker)
    text = text[:pos] + load_fn + text[pos:]

# Make init async and await data load at start
# Find "function init() {" and replace with "async function init() {"
text = text.replace("function init() {", "async function init() {", 1)

# Insert await loadLibraryData(); after the opening brace of init
init_open = "async function init() {"
pos = text.find(init_open)
if pos != -1:
    brace_pos = text.find("\n", pos) + 1
    text = text[:brace_pos] + "      await loadLibraryData();\n" + text[brace_pos:]

HTML.write_text(text, encoding="utf-8")
print("[OK] Patched prototype/index.html")

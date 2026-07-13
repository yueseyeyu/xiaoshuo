#!/usr/bin/env python
"""Test anti-pattern extraction."""
import sys
sys.path.insert(0, "d:/Code/xiaoshuo/src")

from xiaoshuo.pipeline.technique_store import extract_anti_patterns, process_genre, retrieve_cards, format_cards_for_prompt

# Test 1: Extract anti-patterns
print("=== Test 1: Anti-pattern extraction ===")
cards = extract_anti_patterns("末世")
print(f"Anti-pattern cards: {len(cards)}")
for c in cards:
    print(f"  [{c['card_type']}] {c['title']}")
    print(f"    {c['content'][:100]}")
print()

# Test 2: Full process_genre (do + dont)
print("=== Test 2: Full process_genre ===")
count = process_genre("末世")
print(f"Total cards saved: {count}")
print()

# Test 3: Dual-track retrieval
print("=== Test 3: Dual-track retrieval ===")
context = {"chapter_num": 1, "total_chapters": 300, "keywords": ["开篇", "钩子"]}
do_cards = retrieve_cards("末世", context, top_k=3, card_type="do")
dont_cards = retrieve_cards("末世", context, top_k=3, card_type="dont")
print(f"Do cards: {len(do_cards)}")
for c in do_cards:
    print(f"  [{c.get('card_type','do')}] {c['title']}")
print(f"Don't cards: {len(dont_cards)}")
for c in dont_cards:
    print(f"  [{c.get('card_type','dont')}] {c['title']}")
print()

# Test 4: Format for prompt
print("=== Test 4: Format for prompt ===")
all_cards = do_cards + dont_cards
formatted = format_cards_for_prompt(all_cards)
print(formatted[:500] if formatted else "(empty)")
print()

print("=== All tests passed ===")

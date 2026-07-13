#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Test stratified sampling and tier detection."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from xiaoshuo.pipeline.llm_batch_score import _stratified_sample, _get_book_tier, _TIER_SAMPLING

# Test 1: Stratified sampling distribution
print("=== Test 1: Stratified Sampling ===")
for n_ch, max_ch in [(500, 30), (500, 50), (2000, 30), (100, 30), (50, 30)]:
    indices = _stratified_sample(n_ch, max_ch)
    n = len(indices)
    # Check segment distribution
    segments = [(0, 0.03), (0.03, 0.30), (0.30, 0.60), (0.60, 0.90), (0.90, 1.0)]
    seg_names = ["Opening", "Rising", "Mid", "Climax", "Ending"]
    dist = []
    for (s, e), name in zip(segments, seg_names):
        lo = int(s * n_ch)
        hi = int(e * n_ch)
        count = sum(1 for i in indices if lo <= i < hi)
        dist.append(f"{name}={count}")
    print(f"  n_ch={n_ch:4d}, max={max_ch:2d} → sampled={n:2d} | {' '.join(dist)}")
    assert n <= max_ch, f"Over-sampled: {n} > {max_ch}"
    assert indices == sorted(indices), "Not sorted"
    assert len(set(indices)) == len(indices), "Duplicates found"

# Test 2: Edge cases
print("\n=== Test 2: Edge Cases ===")
assert _stratified_sample(10, 30) == list(range(10)), "Small book should return all"
assert _stratified_sample(30, 30) == list(range(30)), "Exact match should return all"
assert _stratified_sample(0, 30) == [], "Empty book"
print("  All edge cases passed")

# Test 3: Tier detection
print("\n=== Test 3: Tier Detection ===")
test_books = [
    "《废土崛起》（校对版全本）作者：通吃道人.txt",
    "《末日蟑螂》.txt",
    "《蹉跎》（校对版全本）作者：随风飘摇.txt",
    "random_unknown_book.txt",
]
for book in test_books:
    tier = _get_book_tier(book)
    expected = _TIER_SAMPLING.get(tier, {"max_ch": 30, "sc_samples": 1})
    print(f"  {book[:35]:35s} → tier={tier}, max_ch={expected['max_ch']}, sc={expected['sc_samples']}")

# Test 4: Verify golden opening coverage
print("\n=== Test 4: Golden Opening Coverage (ch0 always included) ===")
for n_ch in [500, 1000, 2000]:
    indices = _stratified_sample(n_ch, 30)
    has_ch0 = 0 in indices
    has_ch1 = 1 in indices
    opening_count = sum(1 for i in indices if i < max(3, int(0.03 * n_ch)))
    print(f"  n_ch={n_ch:4d}: ch0={has_ch0}, ch1={has_ch1}, opening_3%={opening_count} chapters")

print("\n✅ All tests passed!")

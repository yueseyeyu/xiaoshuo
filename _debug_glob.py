import sqlite3

# Test GLOB pattern directly
conn = sqlite3.connect(":memory:")
HASH_A = "sha256:" + "a" * 64

# Test 1: simple GLOB test
result = conn.execute("SELECT ? GLOB 'sha256:[0-9a-f]*'", (HASH_A,)).fetchone()
print(f"Test 1 (with *): {result[0]}")

# Test 2: exact 64 char classes
pattern = "sha256:" + "[0-9a-f]" * 64
result = conn.execute("SELECT ? GLOB ?", (HASH_A, pattern)).fetchone()
print(f"Test 2 (64 classes): {result[0]}")

# Test 3: count chars in hash
hash_part = HASH_A[7:]  # after "sha256:"
print(f"hash part len = {len(hash_part)}")

# Test 4: try with STRICT table
conn.execute("CREATE TABLE test_strict (content_hash TEXT NOT NULL CHECK (content_hash GLOB 'sha256:[0-9a-f]*')) STRICT")
try:
    conn.execute("INSERT INTO test_strict VALUES (?)", (HASH_A,))
    print("STRICT with * INSERT: succeeded")
except Exception as e:
    print(f"STRICT with * INSERT: {e}")

# Test 5: try with 64 character classes in STRICT
pattern64 = "sha256:" + "[0-9a-f]" * 64
conn.execute(f"CREATE TABLE test_strict2 (content_hash TEXT NOT NULL CHECK (content_hash GLOB '{pattern64}')) STRICT")
try:
    conn.execute("INSERT INTO test_strict2 VALUES (?)", (HASH_A,))
    print("STRICT 64 classes INSERT: succeeded")
except Exception as e:
    print(f"STRICT 64 classes INSERT: {e}")

# Test 6: try non-STRICT
conn.execute(f"CREATE TABLE test_nonstrict (content_hash TEXT NOT NULL CHECK (content_hash GLOB '{pattern64}'))")
try:
    conn.execute("INSERT INTO test_nonstrict VALUES (?)", (HASH_A,))
    print("non-STRICT 64 classes INSERT: succeeded")
except Exception as e:
    print(f"non-STRICT 64 classes INSERT: {e}")

# Test 7: check what v001 uses - it works
conn.execute(f"CREATE TABLE test_v001_style (content_hash TEXT NOT NULL CHECK (content_hash GLOB '{pattern64}')) STRICT")
try:
    conn.execute("INSERT INTO test_v001_style VALUES (?)", (HASH_A,))
    print("v001-style INSERT: succeeded")
except Exception as e:
    print(f"v001-style INSERT: {e}")

# Test 8: check if there's a difference in the actual pattern
# Count [0-9a-f] in v001 actual SQL file
import re
with open("src/xiaoshuo/infrastructure/persistence/sqlite/migrations/v001_initial_schema.sql") as f:
    v001 = f.read()
with open("src/xiaoshuo/infrastructure/persistence/sqlite/migrations/v002_author_decision.sql") as f:
    v002 = f.read()

v001_count = len(re.findall(r'\[0-9a-f\]', v001))
v002_count = len(re.findall(r'\[0-9a-f\]', v002))
print(f"\nv001 [0-9a-f] count: {v001_count}")
print(f"v002 [0-9a-f] count: {v002_count}")

conn.close()

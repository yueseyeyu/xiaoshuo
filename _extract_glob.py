import re
f = open("src/xiaoshuo/infrastructure/persistence/sqlite/migrations/v002_author_decision.sql").read()
print("v002 count:", len(re.findall(r'\[0-9a-f\]', f)))

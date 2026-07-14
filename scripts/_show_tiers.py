import csv, sys
rows = list(csv.DictReader(open('data/reports/rankings/末世/v8.8_final_ranking.csv', encoding='utf-8-sig')))
for r in rows:
    tier = r.get('tier', '?')
    name = r.get('book_name', r.get('name', '?'))
    print(f'{tier:4s} {name}')

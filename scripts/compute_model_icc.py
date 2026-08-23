import csv, json, numpy as np
from scipy import stats
from collections import defaultdict

# Load results
results = defaultdict(list)
with open('data/golden/末世/tier3/multi_model_phase1/results_template.csv', 'r', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    for row in reader:
        ch_key = row['book'] + '_ch' + row['ch_num']
        results[ch_key].append({
            'model': row['model'],
            'intensity': float(row['intensity']),
            'retention': float(row['retention'])
        })

# Build per-chapter per-model arrays
models = sorted(set(r['model'] for rows in results.values() for r in rows))
print(f'Models: {models}')
print(f'Chapters: {len(results)}')

# Collect scores per model
model_scores_i = {m: [] for m in models}
model_scores_r = {m: [] for m in models}
for ch_key, rows in results.items():
    for r in rows:
        model_scores_i[r['model']].append(r['intensity'])
        model_scores_r[r['model']].append(r['retention'])

# Pairwise ICC between models
def icc21(data):
    N, k = data.shape
    gm = data.mean()
    sm = data.mean(axis=1)
    MSb = k * np.sum((sm - gm)**2) / (N - 1)
    MSw = 0.0
    for i in range(N):
        for j in range(k):
            MSw += (data[i, j] - sm[i])**2
    MSw /= (N * (k - 1))
    rm = data.mean(axis=0)
    MSr = N * np.sum((rm - gm)**2) / (k - 1)
    return (MSb - MSw) / (MSb + (k-1)*MSw + k*(MSr - MSw)/N)

print('\n=== Pairwise Model ICC ===')
for i, m1 in enumerate(models):
    for j, m2 in enumerate(models):
        if i >= j: continue
        s1_i, s2_i = np.array(model_scores_i[m1]), np.array(model_scores_i[m2])
        s1_r, s2_r = np.array(model_scores_r[m1]), np.array(model_scores_r[m2])
        icc_i = icc21(np.column_stack([s1_i, s2_i]))
        icc_r = icc21(np.column_stack([s1_r, s2_r]))
        ri = stats.pearsonr(s1_i, s2_i)
        rr = stats.pearsonr(s1_r, s2_r)
        print(f'{m1} vs {m2}:')
        print(f'  Intensity: ICC={icc_i:.3f}, r={ri.statistic:.3f}')
        print(f'  Retention: ICC={icc_r:.3f}, r={rr.statistic:.3f}')

# Average ICC across all model pairs
print('\n=== Overall ===')
all_icc_i = []
all_icc_r = []
for i, m1 in enumerate(models):
    for j, m2 in enumerate(models):
        if i >= j: continue
        s1_i, s2_i = np.array(model_scores_i[m1]), np.array(model_scores_i[m2])
        s1_r, s2_r = np.array(model_scores_r[m1]), np.array(model_scores_r[m2])
        all_icc_i.append(icc21(np.column_stack([s1_i, s2_i])))
        all_icc_r.append(icc21(np.column_stack([s1_r, s2_r])))
print(f'Mean ICC Intensity: {np.mean(all_icc_i):.3f}')
print(f'Mean ICC Retention: {np.mean(all_icc_r):.3f}')

# Compare with human baseline
print('\n=== Human Baseline (for reference) ===')
print('Human-Friend ICC Intensity: 0.070')
print('Human-Friend ICC Retention: -0.134')

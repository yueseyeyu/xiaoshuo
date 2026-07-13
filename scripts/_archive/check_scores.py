"""Check which batch files have corresponding score files."""
import os, glob, json

d = 'data/processed/末世/scores/ai_annotate_batches'

# List all batch files
new_batches = sorted(glob.glob(os.path.join(d, 'new_*.json')))
rerun_batches = sorted(glob.glob(os.path.join(d, 'rerun_*.json')))

# List all score files
score_new = sorted(glob.glob(os.path.join(d, 'scores_new_*.json')))
score_rerun = sorted(glob.glob(os.path.join(d, 'scores_rerun_*.json')))

print("=== NEW batches (total: %d) ===" % len(new_batches))
for f in new_batches:
    bn = os.path.basename(f)
    num = bn.replace('new_', '').replace('.json', '')
    sf = os.path.join(d, f'scores_new_{num}.json')
    status = "DONE" if os.path.exists(sf) else "MISSING"
    # Count chapters in batch
    with open(f, 'r', encoding='utf-8') as fh:
        chapters = json.load(fh)
    print(f"  {bn} -> scores_new_{num}.json [{status}] ({len(chapters)} chapters)")

print("\n=== RERUN batches (total: %d) ===" % len(rerun_batches))
for f in rerun_batches:
    bn = os.path.basename(f)
    num = bn.replace('rerun_', '').replace('.json', '')
    sf = os.path.join(d, f'scores_rerun_{num}.json')
    status = "DONE" if os.path.exists(sf) else "MISSING"
    with open(f, 'r', encoding='utf-8') as fh:
        chapters = json.load(fh)
    print(f"  {bn} -> scores_rerun_{num}.json [{status}] ({len(chapters)} chapters)")

# Summary
missing_new = [os.path.basename(f).replace('new_', '').replace('.json', '') 
               for f in new_batches 
               if not os.path.exists(os.path.join(d, f'scores_new_{os.path.basename(f).replace("new_","").replace(".json","")}.json'))]
missing_rerun = [os.path.basename(f).replace('rerun_', '').replace('.json', '') 
                 for f in rerun_batches 
                 if not os.path.exists(os.path.join(d, f'scores_rerun_{os.path.basename(f).replace("rerun_","").replace(".json","")}.json'))]

print(f"\n=== SUMMARY ===")
print(f"Missing new scores: {missing_new if missing_new else 'NONE'}")
print(f"Missing rerun scores: {missing_rerun if missing_rerun else 'NONE'}")

"""Pure batch-score input/output helpers.

This module owns only CSV row loading, score-row shaping, initial score CSV
writing, and chapter-decision record shaping/merging.  Filesystem paths are
accepted as ``pathlib.Path`` values; no directory creation, metadata, logger,
or production orchestration belongs here.
"""

import csv
from pathlib import Path


def load_rule_rows(csv_path):
    """Load rule-score rows keyed by integer chapter number."""
    rule_rows = {}
    path = Path(csv_path) if csv_path else None
    if path and path.exists():
        with open(path, "r", encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                rule_rows[int(row["ch_num"])] = row
    return rule_rows


def load_already_scored(llm_csv_path):
    """Load integer chapter numbers already present in an LLM score CSV."""
    already_scored = set()
    path = Path(llm_csv_path) if llm_csv_path else None
    if path and path.exists():
        with open(path, "r", encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                already_scored.add(int(row.get("ch_num", 0)))
    return already_scored


def build_score_row(ch_num, llm, rule, ch_wc):
    """Build the initial fourteen-column LLM score row."""
    return {
        "ch_num": ch_num,
        "wc": int(rule.get("wc", ch_wc)),
        "llm_intensity": float(llm["intensity"]),
        "llm_conflict": llm["conflict"],
        "llm_emotion": llm["emotion"],
        "llm_pace": llm["pace"],
        "llm_hook": llm["hook"],
        "llm_retention": float(llm["retention"]),
        "llm_low_confidence": llm.get("low_confidence", False),
        "llm_confidence_note": llm.get("confidence_note", ""),
        "rule_intensity": float(rule.get("pleasure_intensity", 0)),
        "rule_hook": rule.get("hook_type", "none"),
        "rule_emotion": rule.get("emotion", "日常"),
        "rule_pace": rule.get("pace", "medium"),
    }


def write_score_csv(out_path, results):
    """Write the initial fourteen-column score CSV without side effects."""
    fields = [
        "ch_num", "wc",
        "llm_intensity", "llm_conflict", "llm_emotion", "llm_pace", "llm_hook", "llm_retention",
        "llm_low_confidence", "llm_confidence_note",
        "rule_intensity", "rule_hook", "rule_emotion", "rule_pace",
    ]
    with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(results)


def build_decision_records(rows, book_name=""):
    """Build fixed-shape chapter decision records from CSV rows."""
    records = []
    for row in rows:
        records.append({
            "chapter": int(row.get("ch_num", 0)),
            "book": book_name,
            "llm_intensity": float(row.get("llm_intensity", 0)),
            "llm_retention": float(row.get("llm_retention", 0)),
            "llm_conflict": row.get("llm_conflict", ""),
            "llm_emotion": row.get("llm_emotion", ""),
            "llm_pace": row.get("llm_pace", ""),
            "llm_hook": row.get("llm_hook", ""),
            "llm_low_confidence": row.get("llm_low_confidence", "False") == "True",
            "source": "qwen_llm_batch_score",
        })
    return records


def merge_decision_records(existing, new_records):
    """Merge records with later records replacing the same book/chapter."""
    existing_by_key = {
        (row.get("book", ""), row.get("chapter", 0)): row
        for row in existing
    }
    for record in new_records:
        key = (record["book"], record["chapter"])
        existing_by_key[key] = record
    merged = list(existing_by_key.values())
    merged.sort(key=lambda row: (row.get("book", ""), row.get("chapter", 0)))
    return merged

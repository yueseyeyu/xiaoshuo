"""Minimal unit tests for quality_gate — gate config, known quality check, manifest handling."""
import unittest
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "analysis"))
import yaml
from quality_gate import _is_known_quality


class TestQualityConfig(unittest.TestCase):
    def test_config_has_required_keys(self):
        cfg_path = PROJECT_ROOT / "config.yaml"
        with open(cfg_path, 'r', encoding='utf-8') as f:
            cfg = yaml.safe_load(f)
        qg = cfg.get("analysis", {}).get("quality_gate", {})
        self.assertIn("min_rhythm_chapters", qg)
        self.assertIn("min_commercial_score", qg)
        self.assertTrue(qg["min_rhythm_chapters"] > 0)
        self.assertTrue(0 < qg["min_commercial_score"] <= 100)


class TestKnownQuality(unittest.TestCase):
    def test_known_book_detected(self):
        known = ["十日终焉", "全球进化"]
        self.assertTrue(_is_known_quality("《十日终焉》.txt", known))
        self.assertTrue(_is_known_quality("全球进化全本.txt", known))

    def test_unknown_book_rejected(self):
        self.assertFalse(_is_known_quality("随便一本烂书.txt", ["十日终焉"]))

    def test_empty_known_list(self):
        self.assertFalse(_is_known_quality("十日终焉.txt", []))


class TestManifestFormat(unittest.TestCase):
    def test_manifest_schema(self):
        manifest_path = PROJECT_ROOT / "data" / "processed" / "quality_manifest.json"
        if not manifest_path.exists():
            self.skipTest("no manifest yet")
        with open(manifest_path, 'r', encoding='utf-8') as f:
            m = json.load(f)
        self.assertIn("approved", m)
        self.assertIn("gate_version", m)
        for a in m["approved"]:
            self.assertIn("file", a)
            self.assertIn("stem", a)


if __name__ == "__main__":
    unittest.main()

"""Minimal unit tests for book_processor — encoding detection, genre detection, basic filter."""
import unittest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "analysis"))
from book_processor import detect_encoding, detect_genre, passes_basic_filter


class TestEncoding(unittest.TestCase):
    def test_utf8_detection(self):
        p = Path(__file__).parent / "fixture_utf8.txt"
        p.write_text("测试中文内容", encoding='utf-8')
        self.assertIn(detect_encoding(p), ["UTF-8", "UTF-8-BOM"])

    def test_gbk_detection(self):
        p = Path(__file__).parent / "fixture_gbk.txt"
        p.write_text("测试中文内容".encode('gbk').decode('gbk'), encoding='gbk')
        self.assertEqual(detect_encoding(p), "GBK")

    def test_empty_file(self):
        p = Path(__file__).parent / "fixture_empty.txt"
        p.write_text("", encoding='utf-8')
        enc = detect_encoding(p)
        self.assertIn(enc, ["UTF-8", "UNKNOWN"])


class TestGenreDetection(unittest.TestCase):
    def test_apocalypse_keywords(self):
        p = Path(__file__).parent / "fixture_moshi.txt"
        p.write_text("末世降临，丧尸横行，幸存者在废土中挣扎求生存进化觉醒", encoding='utf-8')
        self.assertEqual(detect_genre(p), "末世")

    def test_unknown_genre(self):
        p = Path(__file__).parent / "fixture_unknown.txt"
        p.write_text("hello world this is a test file", encoding='utf-8')
        self.assertEqual(detect_genre(p), "未知")


class TestBasicFilter(unittest.TestCase):
    def test_tiny_file_fails(self):
        p = Path(__file__).parent / "fixture_tiny.txt"
        p.write_text("短小", encoding='utf-8')
        passed, reason, name, genre, known = passes_basic_filter(p)
        self.assertFalse(passed)

    def test_big_file_skips_chapter_check(self):
        p = Path(__file__).parent / "fixture_big.txt"
        # 6MB of repetitive Chinese (big file, auto-passes chapter check)
        chunk = "测试中文内容填充数据\n" * 100
        data = (chunk * (6 * 1024)).encode('utf-8')
        p.write_bytes(data)
        passed, reason, name, genre, known = passes_basic_filter(p)
        self.assertTrue(passed, f"big file should auto-pass: {reason}")

    def test_normal_file_with_chapters(self):
        p = Path(__file__).parent / "fixture_normal.txt"
        # 200+KB with valid chapters and Chinese content
        line = "第一章 开局大背景设定的人物介绍世界观展开故事推进中语文\n"
        text = line * 4000  # ~200KB
        p.write_text(text, encoding='utf-8')
        passed, reason, name, genre, known = passes_basic_filter(p)
        self.assertTrue(passed, f"normal file should pass: {reason}")


if __name__ == "__main__":
    result = unittest.main(exit=False)
    # Cleanup fixtures
    for f in Path(__file__).parent.glob("fixture_*.txt"):
        f.unlink()
    sys.exit(0 if result.result.wasSuccessful() else 1)

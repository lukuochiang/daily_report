"""流水线核心逻辑单元测试：python -m unittest discover -s tests"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
os.environ["TRANSLATE_ENABLED"] = "false"

from ai_process import process_with_ai  # noqa: E402
from clean_news import clean_all  # noqa: E402
from deduplicate import deduplicate, normalize_url, process_dedup  # noqa: E402
from generate_site import generate_site  # noqa: E402
from utils import utc_now_iso  # noqa: E402
from validate_data import ValidationError, validate_daily  # noqa: E402


def sample_item(url="https://example.com/a", title="New AI model released for developers"):
    return {
        "id": "n" + str(abs(hash(url)))[:10],
        "source": "Test Source",
        "source_url": url,
        "original_title": title,
        "published_at": utc_now_iso(),
        "collected_at": utc_now_iso(),
        "original_language": "en",
        "categories": ["ai"],
        "excerpt": "A short factual excerpt about a model release.",
        "heuristic_category": "ai",
        "heuristic_importance": 4,
    }


class DedupTests(unittest.TestCase):
    def test_normalize_url_removes_tracking(self):
        self.assertEqual(
            normalize_url("https://www.Example.com/a/b/?utm_source=x&b=2&a=1#top"),
            "//example.com/a/b?a=1&b=2",
        )

    def test_url_and_title_duplicates(self):
        first = sample_item()
        same_url = sample_item("https://example.com/a?utm_source=newsletter")
        same_title = sample_item("https://other.example.com/story", "New AI model released for developers!")
        kept = deduplicate([first, same_url, same_title])
        self.assertEqual(len(kept), 1)

    def test_distinct_stories_are_kept(self):
        items = [sample_item("https://example.com/1", "Open source database adds SQL support"),
                 sample_item("https://example.com/2", "Regulator publishes new breach reporting rules")]
        self.assertEqual(len(deduplicate(items)), 2)


class CleanTests(unittest.TestCase):
    def test_drops_invalid_items(self):
        items = [sample_item("ftp://bad.example.com/a"), sample_item("https://ok.example.com/a", "Hi")]
        self.assertEqual(clean_all(items), [])

    def test_assigns_category_and_importance(self):
        cleaned = clean_all([sample_item()])
        self.assertEqual(cleaned[0]["heuristic_category"], "ai")
        self.assertTrue(1 <= cleaned[0]["heuristic_importance"] <= 5)


class AiFallbackTests(unittest.TestCase):
    def test_fallback_preserves_original(self):
        items = [sample_item()]
        with patch.dict(os.environ, {"AI_API_KEY": ""}, clear=False):
            articles, highlights, trends, meta = process_with_ai(items, {}, "2026-11-21", force_disabled=True)
        self.assertEqual(articles[0]["title_zh"], items[0]["original_title"])
        self.assertEqual(articles[0]["source_url"], items[0]["source_url"])
        self.assertFalse(articles[0]["ai_generated"])
        self.assertEqual(meta["ai_status"], "disabled")
        self.assertEqual(highlights, [items[0]["id"]])


class AiProcessingTests(unittest.TestCase):
    def _fake_response(self, content):
        class Response:
            def raise_for_status(self):
                return None

            def json(self):
                return {"choices": [{"message": {"content": content}}]}
        return Response()

    def test_successful_ai_response(self):
        item = sample_item()
        ai_json = {
            "articles": [{
                "id": item["id"], "importance": 5, "category": "ai", "tags": ["model"],
                "title_zh": "新型人工智能模型发布", "title_en": "New AI model launched",
                "summary_zh": "一项面向开发者的模型发布。", "summary_en": "A model release for developers.",
                "event_group": "event-01",
            }],
            "highlights": [item["id"]],
            "trends": [{
                "title_zh": "模型轻量化", "title_en": "Lighter models",
                "summary_zh": "更多模型面向端侧优化。", "summary_en": "More models target edge devices.",
            }],
        }
        import json
        with patch.dict(os.environ, {"AI_API_KEY": "test-key"}), \
             patch("ai_process.requests.post", return_value=self._fake_response(json.dumps(ai_json))):
            articles, highlights, trends, meta = process_with_ai([item], {}, "2026-11-21")
        self.assertTrue(articles[0]["ai_generated"])
        self.assertEqual(articles[0]["title_zh"], "新型人工智能模型发布")
        self.assertEqual(articles[0]["category"], "ai")
        self.assertEqual(highlights, [item["id"]])
        self.assertEqual(len(trends), 1)
        self.assertEqual(meta["ai_status"], "ok")

    def test_invalid_ai_json_falls_back(self):
        with patch.dict(os.environ, {"AI_API_KEY": "test-key"}), \
             patch("ai_process.requests.post", return_value=self._fake_response("not json")):
            articles, _, _, meta = process_with_ai([sample_item()], {}, "2026-11-21")
        self.assertFalse(articles[0]["ai_generated"])
        self.assertEqual(meta["ai_status"], "error")


class AutoTranslationTests(unittest.TestCase):
    def test_translation_fills_other_language(self):
        item = sample_item()
        with patch.dict(os.environ, {"AI_API_KEY": "", "TRANSLATE_ENABLED": "true"}), \
             patch("ai_process.auto_translate", side_effect=lambda text, target: "译文:" + text):
            articles, _, _, meta = process_with_ai([item], {}, "2026-11-21", force_disabled=True)
        self.assertEqual(articles[0]["title_zh"], "译文:" + item["original_title"])
        self.assertTrue(articles[0]["summary_zh"].startswith("【自动翻译】"))
        self.assertEqual(articles[0]["translation_source"], "auto")
        self.assertEqual(meta["translation_status"], "auto")


class ValidationTests(unittest.TestCase):
    def test_valid_data(self):
        articles, _, _, _ = process_with_ai([sample_item()], {}, "2026-11-21", force_disabled=True)
        data = {"date": "2026-11-21", "generated_at": utc_now_iso(), "article_count": 1,
                "articles": articles, "highlights": [articles[0]["id"]], "trends": [],
                "source_stats": []}
        self.assertTrue(validate_daily(data))

    def test_rejects_bad_category(self):
        articles, _, _, _ = process_with_ai([sample_item()], {}, "2026-11-21", force_disabled=True)
        articles[0]["category"] = "unknown"
        data = {"date": "2026-11-21", "generated_at": utc_now_iso(), "article_count": 1,
                "articles": articles, "highlights": [], "trends": [], "source_stats": []}
        with self.assertRaises(ValidationError):
            validate_daily(data)


class SiteTests(unittest.TestCase):
    def test_generates_static_pages(self):
        articles, highlights, trends, meta = process_with_ai(
            [sample_item()], {}, "2026-11-21", force_disabled=True)
        data = {"date": "2026-11-21", "generated_at": utc_now_iso(), "article_count": 1,
                "articles": articles, "highlights": highlights, "trends": trends,
                "source_stats": [], "ai": meta}
        with tempfile.TemporaryDirectory() as tmp:
            with patch("generate_site.DATA_DIR", os.path.join(tmp, "data")), \
                 patch("generate_site.PUBLIC_DIR", tmp):
                generate_site(data)
                from pathlib import Path
                index = Path(tmp, "index.html").read_text(encoding="utf-8")
                daily = Path(tmp, "daily", "2026-11-21", "index.html").read_text(encoding="utf-8")
                archives = Path(tmp, "archives", "index.html").read_text(encoding="utf-8")
                sitemap = Path(tmp, "sitemap.xml").read_text(encoding="utf-8")
        self.assertIn('rel="canonical"', index)
        self.assertIn('data-zh=', index)
        self.assertIn('data-en=', index)
        self.assertIn('target="_blank"', daily)
        self.assertIn('rel="noopener noreferrer"', daily)
        self.assertIn('/daily/2026-11-21/', archives)
        self.assertIn('/daily/2026-11-21/', sitemap)


class SelectionTests(unittest.TestCase):
    def test_diversity_cap(self):
        items = [sample_item("https://example.com/%d" % i, "Distinct technology headline number %d" % i)
                 for i in range(30)]
        for i, item in enumerate(items):
            item["source"] = "Only Source"
        selected = process_dedup(items, {"settings": {"max_articles": 25}})
        self.assertLessEqual(len(selected), 25)
        self.assertLessEqual(sum(1 for i in selected if i["source"] == "Only Source"), 25)


if __name__ == "__main__":
    unittest.main()

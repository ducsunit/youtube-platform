import tempfile
import unittest
from pathlib import Path

from youtube_pipeline.core.llm_cache import LLMResponseCache


class LLMResponseCacheTests(unittest.TestCase):
    def test_put_get_roundtrip_and_key_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = LLMResponseCache(Path(tmp))
            key1 = cache.build_key(
                provider="gemini", model="m", system="s", prompt="p", temperature=0.2, thinking_level="high"
            )
            key2 = cache.build_key(
                provider="gemini", model="m", system="s", prompt="p2", temperature=0.2, thinking_level="high"
            )
            cache.put(key1, '{"ok":true}')
            self.assertEqual(cache.get(key1), '{"ok":true}')
            self.assertNotEqual(key1, key2)
            self.assertIsNone(cache.get(key2))

    def test_schema_version_changes_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = LLMResponseCache(Path(tmp), schema_version="2")
            key1 = cache.build_key(provider="gemini", model="m", system="s", prompt="p", temperature=0.2, schema_version="2")
            key2 = cache.build_key(provider="gemini", model="m", system="s", prompt="p", temperature=0.2, schema_version="3")
            self.assertNotEqual(key1, key2)

    def test_stats_report_hits_and_misses(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = LLMResponseCache(Path(tmp))
            key = cache.build_key(provider="gemini", model="m", system="s", prompt="p", temperature=0.2)
            self.assertIsNone(cache.get(key))
            cache.put(key, "value")
            self.assertEqual(cache.get(key), "value")
            stats = cache.stats()
            self.assertEqual(stats["hits"], 1)
            self.assertEqual(stats["misses"], 1)
            self.assertEqual(stats["requests"], 2)
            self.assertEqual(stats["hit_rate"], 0.5)

    def test_disabled_cache_is_noop(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = LLMResponseCache(Path(tmp), enabled=False)
            key = cache.build_key(
                provider="deepseek", model="m", system="s", prompt="p", temperature=0.2
            )
            cache.put(key, "value")
            self.assertIsNone(cache.get(key))


if __name__ == "__main__":
    unittest.main()

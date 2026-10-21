"""Test provider resolution in engine/llm.py (lmstudio + deepseek presets).

Offline tests: they pin the config→parameters mapping without calling any API.
"""
import os
import unittest
from unittest import mock

from openharness.engine.llm import PROVIDERS, build_llm, resolve_provider
from openharness.engine.query_engine import default_config


class TestProviderPresets(unittest.TestCase):
    def test_lmstudio_defaults(self):
        r = resolve_provider({})
        self.assertEqual(r["provider"], "lmstudio")
        self.assertEqual(r["base_url"], "http://127.0.0.1:1234/v1")
        self.assertEqual(r["model"], "")
        self.assertTrue(r["discover"])

    def test_deepseek_defaults(self):
        with mock.patch.dict(os.environ, {"DEEPSEEK_API_KEY": "sk-env"}, clear=False):
            r = resolve_provider({"provider": "deepseek"})
        self.assertEqual(r["base_url"], "https://api.deepseek.com")
        self.assertEqual(r["model"], "deepseek-flash")
        self.assertEqual(r["api_key"], "sk-env")
        self.assertFalse(r["discover"])

    def test_unknown_provider_lists_known_ones(self):
        with self.assertRaises(ValueError) as ctx:
            resolve_provider({"provider": "openai"})
        for name in PROVIDERS:
            self.assertIn(name, str(ctx.exception))


class TestProviderOverrides(unittest.TestCase):
    def test_explicit_api_key_beats_env(self):
        with mock.patch.dict(os.environ, {"DEEPSEEK_API_KEY": "sk-env"}, clear=False):
            r = resolve_provider({"provider": "deepseek", "api_key": "sk-explicit"})
        self.assertEqual(r["api_key"], "sk-explicit")

    def test_explicit_model_beats_preset(self):
        r = resolve_provider({"provider": "deepseek", "model": "deepseek-v4-pro"})
        self.assertEqual(r["model"], "deepseek-v4-pro")

    def test_explicit_base_url_beats_preset(self):
        r = resolve_provider({"provider": "deepseek", "base_url": "https://proxy.test/v1"})
        self.assertEqual(r["base_url"], "https://proxy.test/v1")

    def test_empty_string_does_not_override_preset(self):
        # default_config ships `model: ""`; it must not blank out the preset.
        config = default_config(".")
        config["provider"] = "deepseek"
        with mock.patch.dict(os.environ, {"DEEPSEEK_API_KEY": "sk-env"}, clear=False):
            r = resolve_provider(config)
        self.assertEqual(r["model"], "deepseek-flash")
        self.assertEqual(r["base_url"], "https://api.deepseek.com")

    def test_nested_legacy_model_dict_still_supported(self):
        r = resolve_provider({"model": {"model": "legacy-x", "temperature": 0.5}})
        self.assertEqual(r["model"], "legacy-x")
        self.assertEqual(r["temperature"], 0.5)


class TestBuildLlmGuards(unittest.TestCase):
    def test_cloud_provider_without_key_raises_actionable_error(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("DEEPSEEK_API_KEY", None)
            with self.assertRaises(ValueError) as ctx:
                build_llm({"provider": "deepseek"})
        self.assertIn("DEEPSEEK_API_KEY", str(ctx.exception))

    def test_cloud_provider_builds_with_key_and_model(self):
        llm = build_llm({"provider": "deepseek", "api_key": "sk-test"})
        self.assertEqual(llm.model_name, "deepseek-flash")
        self.assertEqual(llm.openai_api_base, "https://api.deepseek.com")


if __name__ == "__main__":
    unittest.main()

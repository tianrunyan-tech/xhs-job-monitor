import unittest

from scripts.config_loader import ConfigError, load_config, parse_simple_yaml, validate_config


class ConfigLoaderTests(unittest.TestCase):
    def test_parse_simple_yaml(self):
        parsed = parse_simple_yaml(
            """
keywords:
  - "AI产品经理实习"
search:
  sort: "latest"
  max_pages: 3
  note_type: "all"
  lookback_hours: 48
llm:
  provider: "mock"
  model: "test"
  temperature: 0
feishu:
  app_id: "a"
  app_secret: "b"
  app_token: "c"
  table_id: "d"
runtime:
  output_format: "json"
  cache_dir: "~/.cache"
  xhs_command: "xhs"
"""
        )
        self.assertEqual(parsed["keywords"][0], "AI产品经理实习")
        self.assertEqual(parsed["search"]["max_pages"], 3)

    def test_validate_config_requires_keywords(self):
        with self.assertRaises(ConfigError):
            validate_config({})


if __name__ == "__main__":
    unittest.main()

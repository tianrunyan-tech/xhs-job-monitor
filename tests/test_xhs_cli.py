import json
import unittest
from unittest.mock import patch

from scripts.adapters.xhs_cli import XhsCliAdapter, _build_note_url, _normalize_note_url, _normalize_publish_time


class XhsCliTests(unittest.TestCase):
    @patch("scripts.adapters.xhs_cli.subprocess.run")
    def test_search_maps_items(self, mock_run):
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = json.dumps(
            {"ok": True, "data": {"items": [{"note_card": {"id": "n1", "title": "t1", "url": "u1"}}]}}
        )
        mock_run.return_value.stderr = ""
        adapter = XhsCliAdapter("xhs")
        items = adapter.search("kw", "latest", "all", 1)
        self.assertEqual(items[0].note_id, "n1")
        self.assertEqual(items[0].note_url, "u1")

    @patch("scripts.adapters.xhs_cli.subprocess.run")
    def test_search_skips_hot_query_items(self, mock_run):
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = json.dumps(
            {
                "ok": True,
                "data": {
                    "items": [
                        {"id": "hot1", "model_type": "hot_query", "hot_query": {"queries": []}},
                        {"id": "n1", "model_type": "note", "note_card": {"title": "t1", "url": "u1"}},
                    ]
                },
            }
        )
        mock_run.return_value.stderr = ""
        adapter = XhsCliAdapter("xhs")
        items = adapter.search("kw", "latest", "all", 1)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].note_id, "n1")

    def test_normalize_publish_time_timestamp(self):
        self.assertEqual(_normalize_publish_time(1776093871681), "2026-04-13 23:24")

    def test_normalize_publish_time_date_text(self):
        self.assertEqual(_normalize_publish_time("2026-04-15 10:20:30"), "2026-04-15 10:20")

    def test_build_note_url_uses_mobile_discovery_path(self):
        self.assertEqual(
            _build_note_url("69d4e7600000000023012b82", "tok"),
            "https://www.xiaohongshu.com/discovery/item/69d4e7600000000023012b82?xsec_token=tok&xsec_source=pc_search",
        )

    def test_normalize_note_url_adds_token_and_converts_explore(self):
        self.assertEqual(
            _normalize_note_url("n1", "https://www.xiaohongshu.com/explore/n1", "tok"),
            "https://www.xiaohongshu.com/discovery/item/n1?xsec_token=tok&xsec_source=pc_search",
        )

    @patch("scripts.adapters.xhs_cli.subprocess.run")
    def test_search_prefers_share_url(self, mock_run):
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = json.dumps(
            {
                "ok": True,
                "data": {
                    "items": [
                        {
                            "id": "n1",
                            "xsec_token": "tok",
                            "model_type": "note",
                            "note_card": {
                                "note_url": "https://www.xiaohongshu.com/explore/n1",
                                "share_url": "https://www.xiaohongshu.com/discovery/item/n1",
                            },
                        }
                    ]
                },
            }
        )
        mock_run.return_value.stderr = ""
        adapter = XhsCliAdapter("xhs")
        items = adapter.search("kw", "latest", "all", 1)
        self.assertEqual(items[0].note_url, "https://www.xiaohongshu.com/discovery/item/n1?xsec_token=tok&xsec_source=pc_search")

if __name__ == "__main__":
    unittest.main()

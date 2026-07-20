import unittest
import tempfile
from pathlib import Path
from unittest import mock

from scripts.run_search_sync import build_note_cache_key, build_record, is_role_compatible, load_keyword_expand_cache, load_processed_note_cache, mark_note_processed, match_score, publish_sort_value, resolve_keywords, resolve_keywords_with_cache, save_keyword_expand_cache, save_processed_note_cache, select_candidates_for_limit, should_fetch_first_comment, should_skip_summary_by_title, trace_timings_dict, validate_candidate_before_write
from scripts.schemas import JobExtraction, NoteDetail, NoteSummary
from scripts import bot_logic


class SearchSyncTests(unittest.TestCase):
    def test_build_record_sets_hash_and_status(self):
        note = NoteDetail(note_id="1", note_url="u", keyword="kw", title="AI", raw_text="招聘", image_text="")
        extraction = JobExtraction(is_job_post=True, confidence=0.9, job_title="AI PM", position_info="info", requirement="req", contact_info="hr@example.com")
        record = build_record(note, extraction)
        self.assertEqual(set(record), {"note_id", "company", "job_title", "position_info", "requirement", "location", "publish_time", "contact_info", "note_url"})
        self.assertEqual(record["position_info"], "info")
        self.assertEqual(record["requirement"], "req")

    def test_resolve_keywords_prefers_cli_values(self):
        self.assertEqual(resolve_keywords(["old"], [" new ", ""]), ["new"])
        self.assertEqual(resolve_keywords(["old"], []), ["old"])

    def test_resolve_keywords_expands_cli_values(self):
        self.assertIn("AI产品经理实习", resolve_keywords(["old"], ["AI产品实习"]))

    def test_resolve_keywords_uses_expander(self):
        class FakeExpander:
            def expand(self, keyword):
                return [keyword, "算法实习", "大模型算法实习"]

        self.assertEqual(resolve_keywords(["old"], ["算法岗"], FakeExpander()), ["算法岗", "算法实习", "大模型算法实习"])

    def test_resolve_keywords_with_cache_stores_expansion(self):
        class FakeExpander:
            def expand(self, keyword):
                return [keyword, "AI产品经理实习", "AIGC产品经理实习"]

        with tempfile.TemporaryDirectory() as temp_dir:
            cache = load_keyword_expand_cache(temp_dir)
            result = resolve_keywords_with_cache(["old"], ["AI产品实习"], FakeExpander(), cache)
            self.assertEqual(result, ["AI产品实习", "AI产品经理实习", "AIGC产品经理实习"])
            self.assertTrue(cache["dirty"])
            save_keyword_expand_cache(cache)
            reloaded = load_keyword_expand_cache(temp_dir)
            self.assertIn("ai产品实习", reloaded["items"])

    def test_resolve_keywords_with_cache_reuses_cached_values(self):
        class FakeExpander:
            def __init__(self):
                self.calls = 0

            def expand(self, keyword):
                self.calls += 1
                return [keyword, "AI产品经理实习"]

        with tempfile.TemporaryDirectory() as temp_dir:
            cache = load_keyword_expand_cache(temp_dir)
            expander = FakeExpander()
            first = resolve_keywords_with_cache(["old"], ["AI产品实习"], expander, cache)
            second = resolve_keywords_with_cache(["old"], ["AI产品实习"], expander, cache)
            self.assertEqual(first, second)
            self.assertEqual(expander.calls, 1)

    def test_publish_sort_value(self):
        self.assertGreater(publish_sort_value("2026-04-13T10:00:00+00:00"), publish_sort_value("2026-04-12T10:00:00+00:00"))

    def test_match_score(self):
        note = NoteDetail(note_id="1", note_url="u", keyword="kw", title="AI产品经理实习招聘", raw_text="大模型产品", image_text="")
        extraction = JobExtraction(is_job_post=True, confidence=0.9, job_title="AI产品经理实习生")
        self.assertGreater(match_score(note, extraction, ["AI产品经理实习"]), 0)

    def test_role_compatible_for_product_operations(self):
        self.assertTrue(is_role_compatible(["AI产品运营实习"], JobExtraction(is_job_post=True, confidence=0.9, job_title="AI产品运营实习生")))
        self.assertFalse(is_role_compatible(["AI产品运营实习"], JobExtraction(is_job_post=True, confidence=0.9, job_title="AI产品经理实习生")))

    def test_role_compatible_for_product_manager_is_broad_but_rejects_other_families(self):
        self.assertTrue(is_role_compatible(["AI产品经理实习"], JobExtraction(is_job_post=True, confidence=0.9, job_title="AI产品实习生")))
        self.assertTrue(is_role_compatible(["AI产品经理实习"], JobExtraction(is_job_post=True, confidence=0.9, job_title="产品岗实习")))
        self.assertTrue(is_role_compatible(["AI产品经理实习"], JobExtraction(is_job_post=True, confidence=0.9, job_title="AI产品经理实习生")))
        self.assertFalse(is_role_compatible(["AI产品经理实习"], JobExtraction(is_job_post=True, confidence=0.9, job_title="AI产品运营实习生")))
        self.assertFalse(is_role_compatible(["AI产品经理实习"], JobExtraction(is_job_post=True, confidence=0.9, job_title="AI产品研发实习生")))

    def test_validate_candidate_rejects_role_mismatch(self):
        note = NoteDetail(note_id="1", note_url="u", keyword="kw", title="AI产品经理实习招聘")
        extraction = JobExtraction(is_job_post=True, confidence=0.9, job_title="AI产品经理实习生", position_info="1. 负责需求", requirement="1. 本科")
        self.assertEqual(validate_candidate_before_write(["AI产品运营实习"], note, extraction), (False, "role_mismatch"))

    def test_validate_candidate_rejects_missing_jd_details(self):
        note = NoteDetail(note_id="1", note_url="u", keyword="kw", title="AI产品运营实习招聘")
        extraction = JobExtraction(is_job_post=True, confidence=0.9, job_title="AI产品运营实习生")
        self.assertEqual(validate_candidate_before_write(["AI产品运营实习"], note, extraction), (False, "missing_jd_details"))

    def test_select_candidates_for_limit_prioritizes_new_records(self):
        class FakeStats:
            records_skipped = 0
            errors = 0

        class FakeFeishu:
            def find_record_by_note_id(self, note_id):
                if note_id in {"old-1", "old-2"}:
                    return {"record_id": f"rec-{note_id}"}
                return None

        def candidate(note_id):
            return {
                "detail": NoteDetail(note_id=note_id, note_url="u", keyword="kw"),
                "extraction": JobExtraction(is_job_post=True, confidence=0.9),
                "error_message": "",
                "parse_status": "parsed",
                "match_score": 1,
            }

        stats = FakeStats()
        warnings = []
        selected = select_candidates_for_limit(
            FakeFeishu(),
            [candidate("old-1"), candidate("old-2"), candidate("new-1"), candidate("new-2")],
            2,
            stats,
            [],
            warnings,
        )

        self.assertEqual([item["detail"].note_id for item in selected], ["new-1", "new-2"])
        self.assertEqual(stats.records_skipped, 2)
        self.assertEqual(warnings[0]["existing_candidates"], 2)

    def test_should_skip_summary_by_title_filters_obvious_interview_posts(self):
        note = NoteSummary(note_id="1", note_url="u", keyword="kw", title="AI产品经理面经复盘")
        self.assertTrue(should_skip_summary_by_title(note))

    def test_should_skip_summary_by_title_filters_added_noise_tokens(self):
        self.assertTrue(should_skip_summary_by_title(NoteSummary(note_id="1", note_url="u", keyword="kw", title="AI产品经理面试必问3题")))
        self.assertTrue(should_skip_summary_by_title(NoteSummary(note_id="2", note_url="u", keyword="kw", title="AI 产品经理基本功：接到需求怎么做")))
        self.assertTrue(should_skip_summary_by_title(NoteSummary(note_id="3", note_url="u", keyword="kw", title="产品经理day1")))

    def test_should_skip_summary_by_title_keeps_explicit_recruiting_titles(self):
        note = NoteSummary(note_id="1", note_url="u", keyword="kw", title="AI产品经理实习招人啦")
        self.assertFalse(should_skip_summary_by_title(note))

    def test_should_fetch_first_comment_always_true(self):
        detail = NoteDetail(note_id="1", note_url="u", keyword="kw", title="招聘", raw_text="投递方式见首评")
        self.assertTrue(should_fetch_first_comment(detail))
        self.assertTrue(should_fetch_first_comment(NoteDetail(note_id="2", note_url="u", keyword="kw", title="招聘", raw_text="正常正文")))

    def test_processed_note_cache_roundtrip(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = load_processed_note_cache(temp_dir)
            mark_note_processed(cache, "k1")
            mark_note_processed(cache, "k2")
            save_processed_note_cache(cache)
            reloaded = load_processed_note_cache(temp_dir)
            self.assertIn("k1", reloaded["seen"])
            self.assertIn("k2", reloaded["seen"])

    def test_mark_note_processed_deduplicates(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = load_processed_note_cache(temp_dir)
            mark_note_processed(cache, "k1")
            mark_note_processed(cache, "k1")
            self.assertEqual(cache["keys"], ["k1"])

    def test_build_note_cache_key_varies_by_keyword_family(self):
        self.assertEqual(
            build_note_cache_key("n1", ["AI产品经理实习", "AIGC产品经理实习"]),
            build_note_cache_key("n1", ["AIGC产品经理实习", "AI产品经理实习"]),
        )
        self.assertNotEqual(
            build_note_cache_key("n1", ["AI产品经理实习"]),
            build_note_cache_key("n1", ["AI产品运营实习"]),
        )

    def test_trace_timings_dict_handles_missing_or_null_timings(self):
        self.assertEqual(trace_timings_dict(None), {})
        self.assertEqual(trace_timings_dict({}), {})
        self.assertEqual(trace_timings_dict({"timings": None}), {})
        self.assertEqual(trace_timings_dict({"timings": {"classify_elapsed_ms": 12}}), {"classify_elapsed_ms": 12})

    def test_run_sync_returns_timeout_payload(self):
        with mock.patch("scripts.bot_logic.subprocess.run", side_effect=bot_logic.subprocess.TimeoutExpired(cmd=["python3"], timeout=1)):
            payload = bot_logic.run_sync("config.local.yaml", "AI产品经理实习", "tbl123", 5, lookback_hours=72)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["errors"][0]["category"], "subprocess_timeout")


if __name__ == "__main__":
    unittest.main()

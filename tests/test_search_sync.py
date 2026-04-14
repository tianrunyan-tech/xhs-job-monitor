import unittest

from scripts.run_search_sync import build_record, is_role_compatible, match_score, publish_sort_value, resolve_keywords, select_candidates_for_limit, validate_candidate_before_write
from scripts.schemas import JobExtraction, NoteDetail


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

    def test_publish_sort_value(self):
        self.assertGreater(publish_sort_value("2026-04-13T10:00:00+00:00"), publish_sort_value("2026-04-12T10:00:00+00:00"))

    def test_match_score(self):
        note = NoteDetail(note_id="1", note_url="u", keyword="kw", title="AI产品经理实习招聘", raw_text="大模型产品", image_text="")
        extraction = JobExtraction(is_job_post=True, confidence=0.9, job_title="AI产品经理实习生")
        self.assertGreater(match_score(note, extraction, ["AI产品经理实习"]), 0)

    def test_role_compatible_for_product_operations(self):
        self.assertTrue(is_role_compatible(["AI产品运营实习"], JobExtraction(is_job_post=True, confidence=0.9, job_title="AI产品运营实习生")))
        self.assertFalse(is_role_compatible(["AI产品运营实习"], JobExtraction(is_job_post=True, confidence=0.9, job_title="AI产品经理实习生")))

    def test_validate_candidate_rejects_role_mismatch(self):
        note = NoteDetail(note_id="1", note_url="u", keyword="kw", title="AI产品经理实习招聘")
        extraction = JobExtraction(is_job_post=True, confidence=0.9, job_title="AI产品经理实习生", position_info="1. 负责需求", requirement="1. 本科")
        self.assertEqual(validate_candidate_before_write(["AI产品运营实习"], note, extraction), (False, "role_mismatch"))

    def test_validate_candidate_rejects_missing_jd_details(self):
        note = NoteDetail(note_id="1", note_url="u", keyword="kw", title="AI产品运营实习招聘")
        extraction = JobExtraction(is_job_post=True, confidence=0.9, job_title="AI产品运营实习生")
        self.assertEqual(validate_candidate_before_write(["AI产品运营实习"], note, extraction), (False, "missing_jd_details"))

    def test_validate_candidate_rejects_traffic_referral_ad(self):
        note = NoteDetail(
            note_id="1",
            note_url="u",
            keyword="kw",
            title="字节实习继任｜内推直达",
            raw_text="急寻实习继任 内推简历直转字节部门leader 可投岗位：内容运营、用户增长、前端开发、后端开发、数据分析、软件测试、算法助理、电商运营、商业化运营、社区运营、平台运营、用户运营、HR助理、行政助理、法务助理",
        )
        extraction = JobExtraction(is_job_post=True, confidence=0.9, job_title="AI产品运营实习生", position_info="1. 参与运营", requirement="1. 本科")
        self.assertEqual(validate_candidate_before_write(["AI产品运营实习"], note, extraction), (False, "traffic_referral_ad"))

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


if __name__ == "__main__":
    unittest.main()

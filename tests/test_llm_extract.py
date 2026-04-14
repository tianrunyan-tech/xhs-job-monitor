import unittest

from scripts.adapters.llm_extract import OpenAICompatibleExtractor, is_traffic_referral_ad, parse_llm_response
from scripts.schemas import NoteDetail


class LlmExtractTests(unittest.TestCase):
    def test_parse_llm_response(self):
        note = NoteDetail(note_id="1", note_url="", keyword="kw")
        payload = {
            "choices": [
                {
                    "message": {
                        "content": '{"is_job_post": true, "confidence": 0.91, "company": "A", "job_title": "PM Intern", "position_info": "info", "requirement": "req", "location": null, "contact_info": "hr@example.com"}'
                    }
                }
            ]
        }
        result = parse_llm_response(payload, note)
        self.assertTrue(result.is_job_post)
        self.assertEqual(result.company, "A")
        self.assertEqual(result.contact_info, "hr@example.com")

    def test_parse_llm_response_accepts_nested_prompt_schema(self):
        note = NoteDetail(note_id="1", note_url="", keyword="kw")
        payload = {
            "choices": [
                {
                    "message": {
                        "content": '{"is_job_post": true, "judgment_reason": "详细列出岗位职责和邮箱", "data": {"company": "腾讯CSIG", "job_title": "AI产品经理实习生", "location": "北京", "position_info": "1. 负责需求调研\\n2. 完成原型设计", "requirements": "1. 本科及以上\\n2. 每周4天", "contact_info": "hr@example.com"}}'
                    }
                }
            ]
        }
        result = parse_llm_response(payload, note)
        self.assertTrue(result.is_job_post)
        self.assertEqual(result.confidence, 0.9)
        self.assertEqual(result.company, "腾讯CSIG")
        self.assertEqual(result.job_title, "AI产品经理实习生")
        self.assertEqual(result.requirement, "1. 本科及以上\n2. 每周4天")

    def test_parse_llm_response_clears_fields_for_non_job_post(self):
        note = NoteDetail(note_id="1", note_url="", keyword="kw")
        payload = {
            "choices": [
                {
                    "message": {
                        "content": '{"is_job_post": false, "judgment_reason": "面试经历分享", "data": {"company": "腾讯", "job_title": "产品经理", "location": "北京", "position_info": "脏数据", "requirements": "脏数据", "contact_info": "hr@example.com"}}'
                    }
                }
            ]
        }
        result = parse_llm_response(payload, note)
        self.assertFalse(result.is_job_post)
        self.assertIsNone(result.company)
        self.assertIsNone(result.job_title)
        self.assertIsNone(result.requirement)
        self.assertIsNone(result.contact_info)

    def test_parse_llm_response_accepts_null_data_for_non_job_post(self):
        note = NoteDetail(note_id="1", note_url="", keyword="kw")
        payload = {
            "choices": [
                {
                    "message": {
                        "content": '{"is_job_post": false, "judgment_reason": "个人求职帖", "data": null}'
                    }
                }
            ]
        }
        result = parse_llm_response(payload, note)
        self.assertFalse(result.is_job_post)
        self.assertIsNone(result.company)
        self.assertIsNone(result.job_title)
        self.assertIsNone(result.requirement)

    def test_parse_llm_response_extracts_json_after_thinking(self):
        note = NoteDetail(note_id="1", note_url="", keyword="kw")
        payload = {
            "choices": [
                {
                    "message": {
                        "content": '<think>analysis</think>\n{"is_job_post": false, "confidence": 0.2, "company": null, "job_title": null, "position_info": null, "requirement": null, "location": null, "contact_info": null}'
                    }
                }
            ]
        }
        result = parse_llm_response(payload, note)
        self.assertFalse(result.is_job_post)

    def test_parse_llm_response_returns_failure_for_no_json_with_note(self):
        note = NoteDetail(note_id="1", note_url="", keyword="kw")
        payload = {"choices": [{"message": {"content": "<think>only reasoning</think>"}}]}
        result = parse_llm_response(payload, note)
        self.assertFalse(result.is_job_post)
        self.assertEqual(result.confidence, 0.0)

    def test_traffic_referral_ad_is_not_job_post(self):
        note = NoteDetail(
            note_id="1",
            note_url="",
            keyword="AI产品运营实习",
            title="字节实习继任｜内推直达",
            raw_text="急寻实习继任 内推简历直转字节部门leader 可投岗位：内容运营、用户增长、前端开发、后端开发、数据分析、软件测试、算法助理、电商运营、商业化运营、社区运营、平台运营、用户运营、HR助理、行政助理、法务助理",
        )
        self.assertTrue(is_traffic_referral_ad(note))

    def test_mock_extractor_rejects_traffic_referral_ad(self):
        note = NoteDetail(
            note_id="1",
            note_url="",
            keyword="AI产品运营实习",
            title="字节实习继任｜内推直达",
            raw_text="急寻实习继任 内推简历直转字节部门leader 可投岗位：内容运营、用户增长、前端开发、后端开发、数据分析、软件测试、算法助理、电商运营、商业化运营、社区运营、平台运营、用户运营、HR助理、行政助理、法务助理",
        )
        result = OpenAICompatibleExtractor({"provider": "mock"}).extract(note)
        self.assertFalse(result.is_job_post)


if __name__ == "__main__":
    unittest.main()

import unittest
from unittest.mock import patch

from scripts.adapters.llm_extract import OpenAICompatibleExtractor, parse_llm_response
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

    @patch("scripts.adapters.llm_extract.request.urlopen")
    def test_extractor_retries_once_on_timeout(self, mock_urlopen):
        note = NoteDetail(note_id="1", note_url="", keyword="kw")

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return b'{"choices":[{"message":{"content":"{\\"is_job_post\\": false, \\"data\\": null}"}}]}'

        mock_urlopen.side_effect = [TimeoutError("timed out"), FakeResponse()]
        extractor = OpenAICompatibleExtractor(
            {
                "provider": "openai_compatible",
                "model": "m",
                "api_base": "https://example.com/v1",
                "api_key": "sk-test",
                "timeout_seconds": 1,
                "max_retries": 1,
            }
        )
        result = extractor.extract(note)
        self.assertFalse(result.is_job_post)
        self.assertEqual(mock_urlopen.call_count, 2)

    @patch.object(OpenAICompatibleExtractor, "_chat_completion")
    def test_extract_uses_single_call_and_no_ocr_payload(self, mock_chat_completion):
        mock_chat_completion.return_value = {
            "choices": [{"message": {"content": '{"is_job_post": true, "confidence": 0.6, "judgment_reason": "是招聘", "data": {"company": "智谱", "job_title": "AI产品经理实习", "location": "北京", "position_info": "1. 做产品", "requirements": "1. 有经验", "contact_info": "hr@zhipu.cn"}}'}}]
        }
        extractor = OpenAICompatibleExtractor({"provider": "openai_compatible", "model": "m"})
        note = NoteDetail(note_id="1", note_url="", keyword="kw", title="标题", raw_text="正文", image_text="图片OCR", first_comment="首评")
        result = extractor.extract(note)
        self.assertTrue(result.is_job_post)
        self.assertEqual(result.company, "智谱")
        self.assertEqual(result.contact_info, "hr@zhipu.cn")
        self.assertEqual(result.confidence, 0.6)
        self.assertEqual(mock_chat_completion.call_count, 1)
        payload = mock_chat_completion.call_args[0][1]
        self.assertEqual(payload["first_comment"], "首评")
        self.assertNotIn("image_text", payload)


if __name__ == "__main__":
    unittest.main()

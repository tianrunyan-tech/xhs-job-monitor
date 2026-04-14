import unittest

from scripts.adapters.keyword_expand import normalize_keywords, parse_keyword_expand_response


class KeywordExpandTests(unittest.TestCase):
    def test_parse_keyword_expand_response(self):
        payload = {
            "choices": [
                {
                    "message": {
                        "content": '{"keywords": ["算法岗", "算法实习", "大模型算法实习", "机器学习实习"]}'
                    }
                }
            ]
        }
        self.assertEqual(
            parse_keyword_expand_response(payload, "算法岗"),
            ["算法岗", "算法实习", "大模型算法实习", "机器学习实习"],
        )

    def test_parse_keyword_expand_response_extracts_json_after_thinking(self):
        payload = {
            "choices": [
                {
                    "message": {
                        "content": '<think>analysis</think>\n{"keywords": ["AI产品实习", "AI产品经理实习"]}'
                    }
                }
            ]
        }
        self.assertEqual(
            parse_keyword_expand_response(payload, "AI产品实习"),
            ["AI产品实习", "AI产品经理实习"],
        )

    def test_normalize_keywords_keeps_original_first_and_deduplicates(self):
        self.assertEqual(
            normalize_keywords([" 算法岗 ", "算法岗", "大模型 算法 实习"], "算法岗"),
            ["算法岗", "大模型算法实习"],
        )


if __name__ == "__main__":
    unittest.main()

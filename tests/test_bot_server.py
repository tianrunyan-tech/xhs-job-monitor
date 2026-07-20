import unittest
from unittest.mock import patch

from scripts.bot_runtime import BotRuntime
from scripts.bot_logic import extract_message, expand_search_keywords, format_constraint_collection, format_help_message, format_jobs_message, format_result_message, format_search_started_message, format_stop_message, parse_control_command, parse_job_command, parse_job_constraints, parse_result_limit, parse_update_interval_seconds, table_name_for_keyword


class BotServerTests(unittest.TestCase):
    def test_parse_job_command(self):
        self.assertEqual(parse_job_command("/job 找AI产品经理的岗位"), "AI产品经理")
        self.assertEqual(parse_job_command("/job AI产品经理实习"), "AI产品经理实习")
        self.assertEqual(parse_job_command("帮我找 AI产品经理实习岗位"), "AI产品经理实习")
        self.assertIsNone(parse_job_command("找 AI产品经理实习"))

    def test_parse_control_command(self):
        self.assertEqual(parse_control_command("/help"), "help")
        self.assertEqual(parse_control_command("/jobs"), "list")
        self.assertEqual(parse_control_command("停止监控"), "stop")
        self.assertEqual(parse_control_command("立即更新"), "rerun")

    def test_format_constraint_collection_omits_job_type_when_keyword_has_type(self):
        text = format_constraint_collection("AI产品经理实习")
        self.assertIn("公司偏好", text)
        self.assertIn("地点偏好", text)
        self.assertIn("默认我会每2小时帮你更新一次最新岗位", text)
        self.assertNotIn("岗位类型：", text)

    def test_format_search_started_message(self):
        text = format_search_started_message()
        self.assertIn("收到啦，我现在开始帮你找", text)
        self.assertIn("更新到表格", text)

    def test_format_result_message(self):
        text = format_result_message(
            "AI产品经理实习",
            "AI产品经理实习",
            "app1",
            "tbl1",
            {
                "stats": {"records_created": 1},
                "data": [{"company": "字节跳动", "job_title": "AI产品经理实习", "location": "北京", "publish_time": "2026-05-02", "note_url": "https://example.com/1"}],
            },
            next_update_hours=2,
        )
        self.assertIn("最新岗位信息已经更新到表格里", text)
        self.assertIn("https://feishu.cn/base/app1?table=tbl1", text)
        self.assertIn("字节跳动 | AI产品经理实习 | 北京 | 2026-05-02", text)
        self.assertIn("下次更新会在2小时后", text)

    def test_format_result_message_warns_when_max_records_reached(self):
        result = {"stats": {}, "warnings": [{"category": "max_records_reached", "max_records": 50, "overflow": 3}]}
        text = format_result_message("AI产品经理实习", "AI产品经理实习", "app1", "tbl1", result)
        self.assertIn("暂时没有找到符合条件", text)

    def test_format_result_message_warns_when_max_records_reached_with_written_records(self):
        result = {"stats": {"records_created": 50}, "warnings": [{"category": "max_records_reached", "max_records": 50, "overflow": 3}]}
        text = format_result_message("AI产品经理实习", "AI产品经理实习", "app1", "tbl1", result)
        self.assertIn("优先根据发布时间和岗位匹配度找到了50个岗位", text)
        self.assertIn("如果需要更多，可以告诉我数字", text)

    def test_format_result_message_for_failed_result(self):
        result = {"ok": False, "stats": {}, "errors": [{"message": "auth failed"}]}
        text = format_result_message("AI产品经理实习", "AI产品经理实习", "app1", "tbl1", result)
        self.assertIn("没有完成", text)

    def test_parse_job_constraints(self):
        result = parse_job_constraints("只看上海和北京，优先字节和腾讯，最近一周的新帖，每天更新一次。", "AI产品经理实习")
        self.assertEqual(result["lookback_hours"], 7 * 24)
        self.assertEqual(result["interval_seconds"], 24 * 60 * 60)
        self.assertIn("AI产品经理实习", result["search_keyword"])
        self.assertIn("上海和北京", result["search_keyword"])
        self.assertNotIn("每天更新", result["search_keyword"])

    def test_parse_job_constraints_accepts_no_constraints(self):
        result = parse_job_constraints("都不需要，直接找岗位信息", "算法实习")
        self.assertEqual(result["search_keyword"], "算法实习")
        self.assertEqual(result["lookback_hours"], 3 * 24)

    def test_parse_update_interval_seconds(self):
        self.assertEqual(parse_update_interval_seconds("每天更新一次"), 24 * 60 * 60)
        self.assertEqual(parse_update_interval_seconds("每6小时更新一次"), 6 * 60 * 60)
        self.assertIsNone(parse_update_interval_seconds("只查一次"))
        self.assertIsNone(parse_update_interval_seconds("只差一次"))

    def test_parse_result_limit(self):
        self.assertEqual(parse_result_limit("先帮我找最近的5个帖子，只查一次"), 5)

    def test_parse_job_constraints_with_result_limit(self):
        result = parse_job_constraints("先帮我找最近的5个帖子，只差一次", "AI产品经理实习")
        self.assertEqual(result["result_limit"], 5)
        self.assertEqual(result["search_keyword"], "AI产品经理实习")
        self.assertIsNone(result["interval_seconds"])

    def test_table_name_for_keyword_sanitizes(self):
        self.assertEqual(table_name_for_keyword("AI/PM:实习"), "AI_PM_实习")

    def test_expand_search_keywords_for_ai_product_internship(self):
        self.assertEqual(
            expand_search_keywords("AI产品实习"),
            [
                "AI产品实习",
                "AI产品经理实习",
                "AI产品岗实习",
                "AI产品实习继任",
                "AIGC产品实习",
                "大模型产品实习",
                "大模型产品经理实习",
                "AIGC产品经理实习",
                "AI产品日常实习",
                "AI产品校招实习",
            ],
        )

    def test_extract_message_from_v2_event(self):
        chat_id, message_id, text = extract_message(
            {
                "event": {
                    "message": {
                        "chat_id": "oc_1",
                        "message_id": "om_1",
                        "content": '{"text":"找 AI产品经理实习"}',
                    }
                }
            }
        )
        self.assertEqual(chat_id, "oc_1")
        self.assertEqual(message_id, "om_1")
        self.assertEqual(text, "找 AI产品经理实习")

    def test_format_help_message(self):
        text = format_help_message()
        self.assertIn("/job AI产品经理实习", text)
        self.assertIn("/stop", text)

    def test_format_jobs_message(self):
        text = format_jobs_message({"display_keyword": "AI产品经理实习", "keyword": "AI产品经理实习 北京", "lookback_hours": 72, "interval_seconds": 7200})
        self.assertIn("关键词：AI产品经理实习", text)
        self.assertIn("更新频率：2小时", text)

    def test_format_jobs_message_without_job(self):
        self.assertIn("还没有正在自动更新", format_jobs_message(None))

    def test_format_stop_message(self):
        self.assertIn("已经停止", format_stop_message(True))
        self.assertIn("没有正在运行", format_stop_message(False))

    def test_split_reply_text_splits_long_messages(self):
        runtime = BotRuntime.__new__(BotRuntime)
        runtime.FEISHU_TEXT_LIMIT = 20
        chunks = runtime._split_reply_text("第一行内容很长很长很长\n第二行内容也很长很长很长\n第三行内容也很长")
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(chunk) <= 20 for chunk in chunks))

    @patch("scripts.bot_runtime.threading.Thread")
    def test_collect_constraints_clears_existing_schedule_for_run_once(self, mock_thread):
        runtime = BotRuntime.__new__(BotRuntime)
        runtime.limit = 50
        runtime.pending_jobs = {
            "chat1": {
                "keyword": "AI产品经理实习",
                "stage": "collect_constraints",
                "lookback_hours": 72,
                "interval_seconds": 7200,
            }
        }
        runtime.scheduled_jobs = {
            "chat1": {
                "keyword": "旧任务",
                "interval_seconds": 7200,
                "next_run_at": 1,
            }
        }
        runtime.send_reply = lambda *args, **kwargs: None
        runtime.log = lambda *args, **kwargs: None
        runtime._save_state = lambda: None
        runtime._interval_hours = lambda job: None
        runtime.process_keyword = lambda *args, **kwargs: None

        class FakeThread:
            def __init__(self, *args, **kwargs):
                pass

            def start(self):
                return None

        mock_thread.side_effect = FakeThread
        runtime.handle_text("chat1", "msg1", "先帮我找最近的5个帖子，只查一次")
        self.assertNotIn("chat1", runtime.scheduled_jobs)


if __name__ == "__main__":
    unittest.main()

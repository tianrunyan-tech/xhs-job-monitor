#!/usr/bin/env python3
import argparse
import json
import os
import sys
import threading
import time
import traceback
from pathlib import Path

CURRENT_DIR = Path(__file__).resolve().parent
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))

from adapters.feishu_bitable import FeishuBitableAdapter
from adapters.feishu_bot import FeishuBotAdapter
from bot_logic import DEFAULT_INTERVAL_SECONDS, DEFAULT_LOOKBACK_HOURS, FIELD_SCHEMA, extract_message, format_constraint_collection, format_result_message, format_search_started_message, parse_job_command, parse_job_constraints, run_sync, table_name_for_keyword
from config_loader import load_config


def _load_lark_sdk():
    try:
        import lark_oapi as lark
        from lark_oapi.api.im.v1 import P2ImMessageReceiveV1
        return lark, P2ImMessageReceiveV1
    except ModuleNotFoundError as exc:
        raise RuntimeError("Missing dependency lark-oapi. Install it with: python3 -m pip install --user lark-oapi") from exc


class LongConnectionBot:
    def __init__(self, config_path: str, limit: int):
        self.config_path = config_path
        self.limit = limit
        self.config = load_config(config_path).raw
        self.bitable = FeishuBitableAdapter(self.config["feishu"])
        self.bot = FeishuBotAdapter(self.config["feishu"]["app_id"], self.config["feishu"]["app_secret"])
        self.pending_jobs = {}
        self.scheduled_jobs = {}
        threading.Thread(target=self.scheduler_loop, daemon=True).start()

    def handle_payload(self, payload):
        chat_id, message_id, text = extract_message(payload)
        if not chat_id or not text:
            return
        job_keyword = parse_job_command(text)
        if job_keyword:
            self.pending_jobs[chat_id] = {
                "keyword": job_keyword,
                "stage": "collect_constraints",
                "lookback_hours": DEFAULT_LOOKBACK_HOURS,
                "interval_seconds": DEFAULT_INTERVAL_SECONDS,
            }
            self.send_reply(chat_id, message_id, format_constraint_collection(job_keyword))
            print(json.dumps({"event": "job_constraints_requested", "chat_id": chat_id, "keyword": job_keyword}, ensure_ascii=False))
            return

        if chat_id in self.pending_jobs and self.pending_jobs[chat_id].get("stage") == "collect_constraints":
            job = self.pending_jobs.pop(chat_id)
            original_keyword = job["keyword"]
            constraints = parse_job_constraints(text, original_keyword)
            keyword = constraints["search_keyword"]
            job["keyword"] = keyword
            job["display_keyword"] = original_keyword
            job["constraints"] = constraints
            job["lookback_hours"] = constraints["lookback_hours"]
            job["interval_seconds"] = constraints["interval_seconds"]
            if job["interval_seconds"]:
                self.scheduled_jobs[chat_id] = {**job, "next_run_at": time.time()}
            lookback_hours = job["lookback_hours"]
            interval_hours = job["interval_seconds"] / 60 / 60 if job["interval_seconds"] else None
        else:
            return

        self.send_reply(chat_id, message_id, format_search_started_message())
        print(json.dumps({"event": "keyword_received", "chat_id": chat_id, "message_id": message_id, "keyword": keyword}, ensure_ascii=False))
        threading.Thread(target=self.process_keyword, args=(chat_id, message_id, keyword, lookback_hours, interval_hours, original_keyword), daemon=True).start()

    def scheduler_loop(self) -> None:
        while True:
            now = time.time()
            for chat_id, job in list(self.scheduled_jobs.items()):
                if now < job.get("next_run_at", 0):
                    continue
                keyword = job["keyword"]
                job["next_run_at"] = now + job["interval_seconds"]
                interval_hours = job["interval_seconds"] / 60 / 60
                update_lookback_hours = max(1, int(interval_hours))
                threading.Thread(target=self.process_keyword, args=(chat_id, "", keyword, update_lookback_hours, interval_hours, job.get("display_keyword") or keyword), daemon=True).start()
            time.sleep(60)

    def send_reply(self, chat_id: str, message_id: str, text: str) -> None:
        if message_id:
            try:
                self.bot.reply_text(message_id, text)
                print(json.dumps({"event": "reply_sent", "mode": "reply", "message_id": message_id}, ensure_ascii=False))
                return
            except Exception as exc:
                print(json.dumps({"event": "reply_failed", "mode": "reply", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        self.bot.send_text(chat_id, text)
        print(json.dumps({"event": "reply_sent", "mode": "chat", "chat_id": chat_id}, ensure_ascii=False))

    def process_keyword(self, chat_id: str, message_id: str, keyword: str, lookback_hours=None, next_update_hours=None, table_keyword=None) -> None:
        try:
            table_name = table_name_for_keyword(table_keyword or keyword)
            table_id = self.bitable.ensure_table(table_name, FIELD_SCHEMA)
            result = run_sync(self.config_path, keyword, table_id, self.limit, lookback_hours=lookback_hours)
            reply = format_result_message(keyword, table_name, self.config["feishu"]["app_token"], table_id, result, next_update_hours=next_update_hours)
            self.send_reply(chat_id, message_id, reply)
        except Exception as exc:
            traceback.print_exc()
            self.send_reply(chat_id, message_id, f"处理关键词失败：{keyword}\n错误：{exc}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--verification-token", default=os.getenv("FEISHU_VERIFICATION_TOKEN", ""))
    parser.add_argument("--encrypt-key", default=os.getenv("FEISHU_ENCRYPT_KEY", ""))
    args = parser.parse_args()

    lark, P2ImMessageReceiveV1 = _load_lark_sdk()
    bot = LongConnectionBot(args.config, args.limit)

    def on_message(data: P2ImMessageReceiveV1) -> None:
        payload = json.loads(lark.JSON.marshal(data))
        bot.handle_payload(payload)

    handler = (
        lark.EventDispatcherHandler.builder(args.encrypt_key, args.verification_token, lark.LogLevel.INFO)
        .register_p2_im_message_receive_v1(on_message)
        .build()
    )
    ws_client = lark.ws.Client(
        app_id=bot.config["feishu"]["app_id"],
        app_secret=bot.config["feishu"]["app_secret"],
        event_handler=handler,
        log_level=lark.LogLevel.INFO,
    )
    print(json.dumps({"ok": True, "mode": "feishu_long_connection", "limit": args.limit}, ensure_ascii=False))
    ws_client.start()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
import argparse
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict

CURRENT_DIR = Path(__file__).resolve().parent
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))

from adapters.feishu_bitable import FeishuBitableAdapter
from adapters.feishu_bot import FeishuBotAdapter
from bot_logic import FIELD_SCHEMA, extract_message, format_constraint_collection, format_result_message, format_search_started_message, parse_job_command, parse_job_constraints, run_sync, table_name_for_keyword
from config_loader import load_config


class BotHandler(BaseHTTPRequestHandler):
    server_version = "XhsJobMonitorBot/1.0"

    def _send_json(self, status: int, payload: Dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")

        if payload.get("type") == "url_verification" or payload.get("challenge"):
            self._send_json(200, {"challenge": payload.get("challenge")})
            return

        token = getattr(self.server, "verification_token", "")
        if token and payload.get("token") and payload.get("token") != token:
            self._send_json(403, {"ok": False, "error": "invalid verification token"})
            return

        chat_id, message_id, text = extract_message(payload)
        if not chat_id or not text:
            self._send_json(200, {"ok": True, "ignored": True})
            return

        if chat_id in self.server.pending_jobs and self.server.pending_jobs[chat_id].get("stage") == "collect_constraints":
            job = self.server.pending_jobs.pop(chat_id)
            constraints = parse_job_constraints(text, job["keyword"])
            keyword = constraints["search_keyword"]
            self.server.send_reply(chat_id, message_id, format_search_started_message())
            threading.Thread(target=self.server.process_keyword, args=(chat_id, message_id, keyword, constraints["lookback_hours"], job["keyword"]), daemon=True).start()
            self._send_json(200, {"ok": True})
            return

        keyword = parse_job_command(text)
        if not keyword:
            self._send_json(200, {"ok": True, "ignored": True})
            return

        self.server.pending_jobs[chat_id] = {"keyword": keyword, "stage": "collect_constraints"}
        self.server.send_reply(chat_id, message_id, format_constraint_collection(keyword))
        self._send_json(200, {"ok": True})

    def log_message(self, format: str, *args: Any) -> None:
        return


class BotServer(ThreadingHTTPServer):
    def __init__(self, address, handler, config_path: str, limit: int, verification_token: str):
        super().__init__(address, handler)
        self.config_path = config_path
        self.limit = limit
        self.verification_token = verification_token
        self.config = load_config(config_path).raw
        self.bitable = FeishuBitableAdapter(self.config["feishu"])
        self.bot = FeishuBotAdapter(self.config["feishu"]["app_id"], self.config["feishu"]["app_secret"])
        self.pending_jobs = {}

    def send_reply(self, chat_id: str, message_id: str, text: str) -> None:
        if message_id:
            try:
                self.bot.reply_text(message_id, text)
                return
            except Exception as exc:
                print(f"reply_text failed, falling back to send_text: {exc}", file=sys.stderr)
        self.bot.send_text(chat_id, text)

    def process_keyword(self, chat_id: str, message_id: str, keyword: str, lookback_hours=None, table_keyword=None) -> None:
        try:
            table_name = table_name_for_keyword(table_keyword or keyword)
            table_id = self.bitable.ensure_table(table_name, FIELD_SCHEMA)
            result = run_sync(self.config_path, keyword, table_id, self.limit, lookback_hours=lookback_hours)
            text = format_result_message(keyword, table_name, self.config['feishu']['app_token'], table_id, result)
            self.send_reply(chat_id, message_id, text)
        except Exception as exc:
            print(f"process_keyword failed: {exc}", file=sys.stderr)
            self.send_reply(chat_id, message_id, f"处理关键词失败：{keyword}\n错误：{exc}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=int(os.getenv("FEISHU_BOT_PORT", "8787")))
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--verification-token", default=os.getenv("FEISHU_VERIFICATION_TOKEN", ""))
    args = parser.parse_args()

    server = BotServer((args.host, args.port), BotHandler, args.config, args.limit, args.verification_token)
    print(json.dumps({"ok": True, "listening": f"{args.host}:{args.port}"}, ensure_ascii=False))
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

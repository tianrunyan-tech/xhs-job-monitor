#!/usr/bin/env python3
import argparse
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict

CURRENT_DIR = Path(__file__).resolve().parent
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))

from bot_logic import extract_message
from bot_runtime import BotRuntime


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
        self.server.runtime.handle_text(chat_id, message_id, text)
        self._send_json(200, {"ok": True})

    def log_message(self, format: str, *args: Any) -> None:
        return


class BotServer(ThreadingHTTPServer):
    def __init__(self, address, handler, config_path: str, limit: int, verification_token: str):
        super().__init__(address, handler)
        self.verification_token = verification_token
        self.runtime = BotRuntime(config_path, limit, logger=self._log)

    @staticmethod
    def _log(payload, is_error=False):
        print(json.dumps(payload, ensure_ascii=False), file=sys.stderr if is_error else sys.stdout)


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

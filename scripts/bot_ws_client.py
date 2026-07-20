#!/usr/bin/env python3
import argparse
import json
import os
import sys
from pathlib import Path

CURRENT_DIR = Path(__file__).resolve().parent
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))

from bot_logic import extract_message
from bot_runtime import BotRuntime
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
        self.config = load_config(config_path).raw
        self.runtime = BotRuntime(config_path, limit, logger=self._log)

    def handle_payload(self, payload):
        chat_id, message_id, text = extract_message(payload)
        self.runtime.handle_text(chat_id, message_id, text)

    @staticmethod
    def _log(payload, is_error=False):
        print(json.dumps(payload, ensure_ascii=False), file=sys.stderr if is_error else sys.stdout)


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

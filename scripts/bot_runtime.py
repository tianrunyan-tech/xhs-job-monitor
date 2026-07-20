import json
import sys
import threading
import time
import traceback
from pathlib import Path
from typing import Any, Callable, Dict, Optional

try:
    from adapters.feishu_bitable import FeishuBitableAdapter, FeishuError
    from adapters.feishu_bot import FeishuBotAdapter
    from bot_logic import (
        CONTROL_HELP,
        CONTROL_LIST,
        CONTROL_RERUN,
        CONTROL_STOP,
        DEFAULT_INTERVAL_SECONDS,
        DEFAULT_LOOKBACK_HOURS,
        FIELD_SCHEMA,
        format_constraint_collection,
        format_help_message,
        format_jobs_message,
        format_result_message,
        format_search_started_message,
        format_stop_message,
        parse_control_command,
        parse_job_command,
        parse_job_constraints,
        run_sync,
        table_name_for_keyword,
    )
    from config_loader import load_config
except ModuleNotFoundError:
    from scripts.adapters.feishu_bitable import FeishuBitableAdapter, FeishuError
    from scripts.adapters.feishu_bot import FeishuBotAdapter
    from scripts.bot_logic import (
        CONTROL_HELP,
        CONTROL_LIST,
        CONTROL_RERUN,
        CONTROL_STOP,
        DEFAULT_INTERVAL_SECONDS,
        DEFAULT_LOOKBACK_HOURS,
        FIELD_SCHEMA,
        format_constraint_collection,
        format_help_message,
        format_jobs_message,
        format_result_message,
        format_search_started_message,
        format_stop_message,
        parse_control_command,
        parse_job_command,
        parse_job_constraints,
        run_sync,
        table_name_for_keyword,
    )
    from scripts.config_loader import load_config


class BotRuntime:
    FEISHU_TEXT_LIMIT = 2800

    def __init__(self, config_path: str, limit: int, logger: Optional[Callable[[Dict[str, Any], bool], None]] = None):
        self.config_path = config_path
        self.limit = limit
        self.config = load_config(config_path).raw
        self.bitable = FeishuBitableAdapter(self.config["feishu"])
        self.bot = FeishuBotAdapter(self.config["feishu"]["app_id"], self.config["feishu"]["app_secret"])
        self.pending_jobs: Dict[str, Dict[str, Any]] = {}
        self.scheduled_jobs: Dict[str, Dict[str, Any]] = {}
        self.logger = logger or self._default_logger
        self.state_path = self._resolve_state_path()
        self._load_state()
        threading.Thread(target=self.scheduler_loop, daemon=True).start()

    def handle_text(self, chat_id: str, message_id: str, text: str) -> None:
        if not chat_id or not text:
            return

        control = parse_control_command(text)
        if control == CONTROL_HELP:
            self.send_reply(chat_id, message_id, format_help_message())
            return
        if control == CONTROL_LIST:
            self.send_reply(chat_id, message_id, format_jobs_message(self.scheduled_jobs.get(chat_id)))
            return
        if control == CONTROL_STOP:
            stopped = self.scheduled_jobs.pop(chat_id, None) is not None
            self.pending_jobs.pop(chat_id, None)
            self._save_state()
            self.send_reply(chat_id, message_id, format_stop_message(stopped))
            return
        if control == CONTROL_RERUN:
            job = self.scheduled_jobs.get(chat_id)
            if not job:
                self.send_reply(chat_id, message_id, "当前聊天还没有自动更新任务。你可以直接发 “帮我找 AI产品实习” 给我。")
                return
            self.send_reply(chat_id, message_id, format_search_started_message())
            threading.Thread(
                target=self.process_keyword,
                args=(chat_id, message_id, job["keyword"], job.get("lookback_hours"), self._interval_hours(job), job.get("display_keyword") or job["keyword"], job.get("result_limit")),
                daemon=True,
            ).start()
            return

        job_keyword = parse_job_command(text)
        if job_keyword:
            self.pending_jobs[chat_id] = {
                "keyword": job_keyword,
                "stage": "collect_constraints",
                "lookback_hours": DEFAULT_LOOKBACK_HOURS,
                "interval_seconds": DEFAULT_INTERVAL_SECONDS,
            }
            self.send_reply_card(chat_id, message_id, format_constraint_collection(job_keyword))
            self.log({"event": "job_constraints_requested", "chat_id": chat_id, "keyword": job_keyword})
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
            job["result_limit"] = constraints.get("result_limit") or self.limit
            self.scheduled_jobs.pop(chat_id, None)
            if job["interval_seconds"]:
                self.scheduled_jobs[chat_id] = {**job, "next_run_at": time.time() + job["interval_seconds"]}
            self._save_state()
            lookback_hours = job["lookback_hours"]
            interval_hours = self._interval_hours(job)
            self.send_reply(chat_id, message_id, format_search_started_message())
            self.log({"event": "keyword_received", "chat_id": chat_id, "message_id": message_id, "keyword": keyword})
            threading.Thread(
                target=self.process_keyword,
                args=(chat_id, message_id, keyword, lookback_hours, interval_hours, original_keyword, job["result_limit"]),
                daemon=True,
            ).start()
            return

        if text.strip():
            self.send_reply(chat_id, message_id, "如果你想开始找岗位，可以直接发：`帮我找 AI产品经理实习`。也可以发 `/help` 看可用命令。")

    def scheduler_loop(self) -> None:
        while True:
            now = time.time()
            for chat_id, job in list(self.scheduled_jobs.items()):
                if now < float(job.get("next_run_at", 0)):
                    continue
                interval_seconds = int(job["interval_seconds"])
                job["next_run_at"] = now + interval_seconds
                self._save_state()
                interval_hours = interval_seconds / 60 / 60
                update_lookback_hours = max(1, int(interval_hours))
                threading.Thread(
                    target=self.process_keyword,
                    args=(chat_id, "", job["keyword"], update_lookback_hours, interval_hours, job.get("display_keyword") or job["keyword"], job.get("result_limit")),
                    daemon=True,
                ).start()
            time.sleep(60)

    def send_reply(self, chat_id: str, message_id: str, text: str) -> None:
        chunks = self._split_reply_text(text)
        if message_id and chunks:
            try:
                self.bot.reply_text(message_id, chunks[0])
                self.log({"event": "reply_sent", "mode": "reply", "message_id": message_id})
                for chunk in chunks[1:]:
                    self.bot.send_text(chat_id, chunk)
                    self.log({"event": "reply_sent", "mode": "chat", "chat_id": chat_id, "continued": True})
                return
            except Exception as exc:
                self.log({"event": "reply_failed", "mode": "reply", "error": str(exc)}, is_error=True)
        for index, chunk in enumerate(chunks):
            self.bot.send_text(chat_id, chunk)
            self.log({"event": "reply_sent", "mode": "chat", "chat_id": chat_id, "continued": index > 0})

    def send_reply_card(self, chat_id: str, message_id: str, markdown_text: str) -> None:
        if message_id:
            try:
                self.bot.reply_card(message_id, markdown_text)
                self.log({"event": "reply_sent", "mode": "reply_card", "message_id": message_id})
                return
            except Exception as exc:
                self.log({"event": "reply_failed", "mode": "reply_card", "error": str(exc)}, is_error=True)
        self.bot.send_card(chat_id, markdown_text)
        self.log({"event": "reply_sent", "mode": "chat_card", "chat_id": chat_id})

    def process_keyword(
        self,
        chat_id: str,
        message_id: str,
        keyword: str,
        lookback_hours: Optional[int] = None,
        next_update_hours: Optional[float] = None,
        table_keyword: Optional[str] = None,
        result_limit: Optional[int] = None,
    ) -> None:
        try:
            table_name = table_name_for_keyword(table_keyword or keyword)
            table_id = self.bitable.ensure_table(table_name, FIELD_SCHEMA)
            run_limit = result_limit or self.limit
            result = run_sync(self.config_path, keyword, table_id, run_limit, lookback_hours=lookback_hours)
            reply = format_result_message(keyword, table_name, self.config["feishu"]["app_token"], table_id, result, next_update_hours=next_update_hours)
            self.send_reply(chat_id, message_id, reply)
        except FeishuError as exc:
            error_text = str(exc)
            if "HTTP Error 403" in error_text or "Forbidden" in error_text:
                error_text += "\n请确认飞书应用已开通多维表格的数据表管理、记录读写权限，并已发布最新版本后重新授权。"
            self.send_reply(chat_id, message_id, f"处理关键词失败：{keyword}\n错误：{error_text}")
        except Exception as exc:
            traceback.print_exc()
            self.send_reply(chat_id, message_id, f"处理关键词失败：{keyword}\n错误：{exc}")

    def _resolve_state_path(self) -> Path:
        runtime = self.config.get("runtime") or {}
        cache_dir = Path(runtime.get("cache_dir") or ".").expanduser()
        cache_dir.mkdir(parents=True, exist_ok=True)
        return cache_dir / "bot_state.json"

    def _load_state(self) -> None:
        if not self.state_path.exists():
            return
        try:
            payload = json.loads(self.state_path.read_text(encoding="utf-8"))
        except Exception as exc:
            self.log({"event": "state_load_failed", "path": str(self.state_path), "error": str(exc)}, is_error=True)
            return
        jobs = payload.get("scheduled_jobs")
        if isinstance(jobs, dict):
            self.scheduled_jobs = jobs

    def _save_state(self) -> None:
        payload = {"scheduled_jobs": self.scheduled_jobs}
        self.state_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _interval_hours(self, job: Dict[str, Any]) -> Optional[float]:
        interval_seconds = job.get("interval_seconds")
        if not interval_seconds:
            return None
        return float(interval_seconds) / 60 / 60

    def _split_reply_text(self, text: str) -> list:
        content = text or ""
        if len(content) <= self.FEISHU_TEXT_LIMIT:
            return [content]

        chunks = []
        remaining = content
        while len(remaining) > self.FEISHU_TEXT_LIMIT:
            split_at = remaining.rfind("\n", 0, self.FEISHU_TEXT_LIMIT)
            if split_at <= 0:
                split_at = self.FEISHU_TEXT_LIMIT
            chunk = remaining[:split_at].rstrip()
            if not chunk:
                chunk = remaining[: self.FEISHU_TEXT_LIMIT]
                split_at = len(chunk)
            chunks.append(chunk)
            remaining = remaining[split_at:].lstrip("\n")
        if remaining:
            chunks.append(remaining)
        return chunks

    def log(self, payload: Dict[str, Any], is_error: bool = False) -> None:
        self.logger(payload, is_error)

    @staticmethod
    def _default_logger(payload: Dict[str, Any], is_error: bool = False) -> None:
        stream = sys.stderr if is_error else sys.stdout
        print(json.dumps(payload, ensure_ascii=False), file=stream)

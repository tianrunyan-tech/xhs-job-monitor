import json
import subprocess
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

try:
    from schemas import NoteDetail, NoteSummary
    from utils import compact_text, utc_now_iso
except ModuleNotFoundError:
    from scripts.schemas import NoteDetail, NoteSummary
    from scripts.utils import compact_text, utc_now_iso

XHS_TIMEZONE = timezone(timedelta(hours=8))


class XhsCliError(Exception):
    def __init__(self, category: str, message: str):
        super().__init__(message)
        self.category = category
        self.message = message


class XhsCliAdapter:
    def __init__(self, command: str = "xhs"):
        self.command = command

    def _run_raw(self, args: List[str], capture_output: bool = True) -> subprocess.CompletedProcess:
        try:
            return subprocess.run(
                [self.command] + args,
                check=False,
                capture_output=capture_output,
                text=True,
            )
        except FileNotFoundError as exc:
            raise XhsCliError("parse_error", f"xhs command not found: {self.command}") from exc

    def _classify_error(self, stderr: str) -> str:
        lowered = stderr.lower()
        if "login" in lowered or "auth" in lowered or "not_authenticated" in lowered or "session expired" in lowered or "401" in lowered:
            return "auth_error"
        if "captcha" in lowered or "461" in lowered or "471" in lowered:
            return "captcha_required"
        if "429" in lowered or "rate" in lowered:
            return "rate_limited"
        if "403" in lowered or "blocked" in lowered or "forbidden" in lowered:
            return "ip_blocked"
        return "parse_error"

    def _run(self, args: List[str]) -> Dict[str, Any]:
        process = self._run_raw(args + ["--json"])
        if process.returncode != 0:
            raise XhsCliError(self._classify_error(process.stderr), process.stderr.strip() or process.stdout.strip())
        try:
            payload = json.loads(process.stdout)
        except json.JSONDecodeError as exc:
            raise XhsCliError("parse_error", f"Invalid xhs JSON output: {exc}") from exc
        if isinstance(payload, dict) and payload.get("ok") is False:
            error = payload.get("error") or payload.get("message") or "xhs command failed"
            raise XhsCliError(self._classify_error(str(error)), str(error))
        return payload

    def status(self) -> Dict[str, Any]:
        return self._run(["status"])

    def is_authenticated(self) -> bool:
        try:
            payload = self.status()
        except XhsCliError:
            return False
        data = payload.get("data") if isinstance(payload, dict) else {}
        return bool(data.get("authenticated"))

    def login_qrcode(self) -> Dict[str, Any]:
        # Do not capture output so the terminal can display the QR code while xhs waits for scan confirmation.
        process = self._run_raw(["login", "--qrcode"], capture_output=False)
        if process.returncode != 0:
            raise XhsCliError("auth_error", f"xhs login --qrcode failed with exit code {process.returncode}")
        return self.status()

    def ensure_authenticated(self, allow_qrcode: bool = False) -> bool:
        if self.is_authenticated():
            return True
        if not allow_qrcode:
            raise XhsCliError("auth_error", "Xiaohongshu session is not authenticated. Run xhs login --qrcode first, or pass --login-if-needed.")
        self.login_qrcode()
        if self.is_authenticated():
            return True
        raise XhsCliError("auth_error", "Xiaohongshu login did not produce an authenticated session.")

    def search(self, keyword: str, sort: str, note_type: str, page: int) -> List[NoteSummary]:
        normalized_type = {"normal": "image", "text": "image", "图文": "image"}.get(note_type, note_type)
        payload = self._run(["search", keyword, "--sort", sort, "--page", str(page), "--type", normalized_type])
        items = payload.get("data", {}).get("items") or payload.get("data") or []
        results = []
        for item in items:
            if isinstance(item, dict) and item.get("model_type") not in (None, "note"):
                continue
            note = self._extract_summary(item, keyword)
            if note:
                results.append(note)
        return results

    def _note_ref_args(self, note_ref: str) -> List[str]:
        if "#xsec_token=" in note_ref:
            note_ref, xsec_token = note_ref.split("#xsec_token=", 1)
            return [note_ref, "--xsec-token", xsec_token]
        return [note_ref]

    def read_note(self, note_ref: str, keyword: str, fetch_first_comment: bool = False) -> NoteDetail:
        payload = self._run(["read"] + self._note_ref_args(note_ref))
        data = payload.get("data") or {}
        if isinstance(data, dict) and isinstance(data.get("items"), list) and data["items"]:
            data = data["items"][0]
        summary = self._extract_summary(data, keyword)
        if summary is None:
            raise XhsCliError("parse_error", f"Unable to parse note summary for {note_ref}")
        content = data.get("desc") or data.get("content") or data.get("note_card", {}).get("desc") or ""
        return NoteDetail(
            **asdict(summary),
            raw_text=compact_text(content),
            first_comment=self.first_comment(note_ref) if fetch_first_comment else "",
            crawl_time=utc_now_iso(),
        )

    def first_comment(self, note_ref: str) -> str:
        try:
            payload = self._run(["comments"] + self._note_ref_args(note_ref))
        except XhsCliError:
            return ""
        data = payload.get("data") or {}
        comments = data.get("comments") or data.get("items") or data.get("list") or []
        if not comments:
            return ""
        first = comments[0]
        if not isinstance(first, dict):
            return compact_text(first)
        return compact_text(first.get("content") or first.get("text") or first.get("desc") or first)

    def _extract_summary(self, item: Dict[str, Any], keyword: str) -> Optional[NoteSummary]:
        if not isinstance(item, dict):
            return None
        note = item.get("note_card") if isinstance(item.get("note_card"), dict) else item
        note_id = item.get("id") or item.get("note_id") or item.get("noteId") or note.get("id") or note.get("note_id") or note.get("noteId")
        if not note_id:
            return None
        xsec_token = item.get("xsec_token") or note.get("xsec_token") or ""
        return NoteSummary(
            note_id=str(note_id),
            note_url=_normalize_note_url(str(note_id), note.get("share_url") or note.get("note_url") or note.get("url"), xsec_token),
            keyword=keyword,
            xsec_token=xsec_token,
            title=note.get("title") or note.get("display_title") or "",
            author_name=(note.get("user") or {}).get("nickname") if isinstance(note.get("user"), dict) else note.get("author_name") or "",
            author_id=(note.get("user") or {}).get("user_id") if isinstance(note.get("user"), dict) else note.get("author_id") or "",
            publish_time=_normalize_publish_time(_extract_publish_time_value(note)),
        )


def _extract_publish_time(note: Dict[str, Any]) -> Optional[str]:
    for item in note.get("corner_tag_info") or []:
        if isinstance(item, dict) and item.get("type") == "publish_time":
            return item.get("text")
    return None


def _extract_publish_time_value(note: Dict[str, Any]) -> Any:
    for key in ("time", "publish_time", "last_update_time", "create_time", "update_time", "timestamp", "publish_time_millis"):
        if note.get(key):
            return note.get(key)
    return _extract_publish_time(note)


def _normalize_publish_time(value: Any) -> Optional[str]:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return _timestamp_to_date(value)
    text = str(value).strip()
    if not text:
        return None
    if text.isdigit():
        return _timestamp_to_date(int(text))
    parsed = _parse_relative_publish_time(text)
    if parsed:
        return parsed
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return _format_publish_datetime(datetime.strptime(text.replace("Z", "+0000"), fmt))
        except ValueError:
            continue
    return text


def _timestamp_to_date(value: Any) -> str:
    timestamp = float(value)
    if timestamp > 10_000_000_000:
        timestamp = timestamp / 1000
    return _format_publish_datetime(datetime.fromtimestamp(timestamp, tz=XHS_TIMEZONE))


def _parse_relative_publish_time(text: str) -> Optional[str]:
    now = datetime.now(XHS_TIMEZONE)
    if text in {"刚刚", "今天"}:
        return _format_publish_datetime(now)
    if text == "昨天":
        return _format_publish_datetime(now - timedelta(days=1))
    if text.endswith("分钟前"):
        return _format_publish_datetime(now - timedelta(minutes=int(text[:-3] or 0)))
    if text.endswith("小时前"):
        return _format_publish_datetime(now - timedelta(hours=int(text[:-3] or 0)))
    if text.endswith("天前"):
        return _format_publish_datetime(now - timedelta(days=int(text[:-2] or 0)))
    return None


def _format_publish_datetime(value: datetime) -> str:
    return value.strftime("%Y-%m-%d %H:%M")


def _build_note_url(note_id: str, xsec_token: str) -> str:
    if xsec_token:
        return f"https://www.xiaohongshu.com/discovery/item/{note_id}?xsec_token={xsec_token}&xsec_source=pc_search"
    return f"https://www.xiaohongshu.com/discovery/item/{note_id}"


def _normalize_note_url(note_id: str, url: Any, xsec_token: str) -> str:
    text = str(url or "").strip()
    if not text:
        return _build_note_url(note_id, xsec_token)
    if "xiaohongshu.com/explore/" in text:
        text = text.replace("xiaohongshu.com/explore/", "xiaohongshu.com/discovery/item/")
    if "xiaohongshu.com/discovery/item/" in text and xsec_token and "xsec_token=" not in text:
        separator = "&" if "?" in text else "?"
        text = f"{text}{separator}xsec_token={xsec_token}&xsec_source=pc_search"
    return text

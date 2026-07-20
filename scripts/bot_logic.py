import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

CURRENT_DIR = Path(__file__).resolve().parent

DEFAULT_LOOKBACK_HOURS = 3 * 24
DEFAULT_INTERVAL_SECONDS = 2 * 60 * 60
DEFAULT_SYNC_TIMEOUT_SECONDS = 5 * 60

FIELD_SCHEMA = [
    {"field_name": "note_id", "type": 1},
    {"field_name": "company", "type": 1},
    {"field_name": "job_title", "type": 1},
    {"field_name": "position_info", "type": 1},
    {"field_name": "requirement", "type": 1},
    {"field_name": "location", "type": 1},
    {"field_name": "publish_time", "type": 1},
    {"field_name": "contact_info", "type": 1},
    {"field_name": "note_url", "type": 1},
]

CONTROL_HELP = "help"
CONTROL_LIST = "list"
CONTROL_STOP = "stop"
CONTROL_RERUN = "rerun"


def parse_job_command(text: str) -> Optional[str]:
    cleaned = re.sub(r"@\S+", "", text).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    match = re.match(r"^/job\s+(.+)$", cleaned, flags=re.IGNORECASE)
    if not match:
        match = re.match(r"^(?:请)?帮我找\s*(.+)$", cleaned, flags=re.IGNORECASE)
    if not match:
        return None
    description = match.group(1).strip()
    description = re.sub(r"^(找|搜索|监控|爬取)\s*", "", description)
    description = re.sub(r"(的)?(岗位|岗位信息|招聘信息|招聘)$", "", description).strip()
    return description or None


def parse_control_command(text: str) -> Optional[str]:
    cleaned = re.sub(r"@\S+", "", text or "").strip().lower()
    cleaned = re.sub(r"\s+", " ", cleaned)
    command_map = {
        "/help": CONTROL_HELP,
        "帮助": CONTROL_HELP,
        "help": CONTROL_HELP,
        "/jobs": CONTROL_LIST,
        "/list": CONTROL_LIST,
        "查看任务": CONTROL_LIST,
        "查看监控": CONTROL_LIST,
        "当前任务": CONTROL_LIST,
        "/stop": CONTROL_STOP,
        "停止": CONTROL_STOP,
        "停止更新": CONTROL_STOP,
        "停止监控": CONTROL_STOP,
        "/rerun": CONTROL_RERUN,
        "立即更新": CONTROL_RERUN,
        "重新搜索": CONTROL_RERUN,
        "立刻刷新": CONTROL_RERUN,
    }
    return command_map.get(cleaned)


def expand_search_keywords(keyword: str, max_keywords: int = 10) -> List[str]:
    cleaned = re.sub(r"\s+", "", keyword or "").strip()
    if not cleaned:
        return []

    expanded: List[str] = []

    def add(value: str) -> None:
        value = re.sub(r"\s+", "", value or "").strip()
        if value and value not in expanded and len(expanded) < max_keywords:
            expanded.append(value)

    add(cleaned)

    internship = any(token in cleaned for token in ["实习", "校招", "应届", "继任"])
    product_role = "产品" in cleaned
    ai_role = any(token in cleaned for token in ["AI", "AIGC", "大模型", "人工智能"])

    if product_role and internship:
        add(_ensure_product_manager(cleaned))
        add(_ensure_product_gang(cleaned))
        add(_ensure_suffix(cleaned, "继任"))

    if product_role and ai_role and internship:
        base = _replace_ai_direction(cleaned, "AIGC")
        add(_replace_product_role(base, "产品实习"))
        base = _replace_ai_direction(cleaned, "大模型")
        add(_replace_product_role(base, "产品实习"))
        add(_replace_product_role(base, "产品经理实习"))
        base = _replace_ai_direction(cleaned, "AIGC")
        add(_replace_product_role(base, "产品经理实习"))

    if product_role and internship:
        add(_replace_internship_suffix(cleaned, "日常实习"))
        add(_replace_internship_suffix(cleaned, "校招实习"))

    return expanded


def _ensure_product_manager(keyword: str) -> str:
    if "产品经理" in keyword:
        return keyword
    return keyword.replace("产品岗", "产品经理").replace("产品实习", "产品经理实习")


def _ensure_product_gang(keyword: str) -> str:
    if "产品岗" in keyword:
        return keyword
    return keyword.replace("产品经理", "产品岗").replace("产品实习", "产品岗实习")


def _ensure_suffix(keyword: str, suffix: str) -> str:
    if keyword.endswith(suffix) or suffix in keyword:
        return keyword
    return keyword + suffix


def _replace_internship_suffix(keyword: str, suffix: str) -> str:
    for token in ["日常实习", "校招实习", "实习生", "实习"]:
        if token in keyword:
            return keyword.replace(token, suffix, 1)
    return keyword + suffix


def _replace_ai_direction(keyword: str, direction: str) -> str:
    for token in ["人工智能", "AIGC", "大模型", "AI"]:
        if token in keyword:
            return keyword.replace(token, direction, 1)
    return direction + keyword


def _replace_product_role(keyword: str, role: str) -> str:
    for token in ["产品经理实习生", "产品经理实习", "产品岗实习", "产品实习生", "产品实习"]:
        if token in keyword:
            return keyword.replace(token, role, 1)
    return keyword


def has_job_type(keyword: str) -> bool:
    return any(token in (keyword or "") for token in ["实习", "校招", "社招", "全职", "应届", "日常实习", "暑期实习"])


def format_constraint_collection(keyword: str) -> str:
    type_line = ""
    if not has_job_type(keyword):
        type_line = "- **岗位类型**：你说的岗位是实习、校招，还是社招岗位？\n"
    return (
        "好呀，没问题！开始帮你找之前，我想先确认几个小问题，这样结果会更贴近你的需求～你可以按你关心的部分告诉我：\n\n"
        "- **公司偏好**：你有没有特别想投的公司？比如只看字节、腾讯、阿里，或者排除某些公司。\n"
        "- **地点偏好**：你希望在哪些城市找？比如北京、上海、深圳，或者接受远程。\n"
        f"{type_line}"
        "- **时间要求**：是否希望优先看最近 24 小时的新帖，还是其他时间限制\n"
        "- **更新周期**：默认我会每2小时帮你更新一次最新岗位，你也可以告诉我你的期望周期，比如每天更新一次、只查一次。\n\n"
        "你可以直接一句话告诉我，比如：\n"
        "「只看上海和北京，优先字节和腾讯，最近一周的新帖，每天更新一次。」"
    )


def format_search_started_message() -> str:
    return (
        "收到啦，我现在开始帮你找～\n"
        "等我整理好并更新到表格后，会把结果直接发给你。"
    )


def format_help_message() -> str:
    return (
        "可以这样跟我交互：\n"
        "/job AI产品经理实习\n"
        "帮我找 数据分析实习岗位\n"
        "/jobs 查看当前监控任务\n"
        "/rerun 立即刷新一次当前任务\n"
        "/stop 停止当前聊天的自动更新"
    )


def format_jobs_message(job: Optional[Dict[str, Any]]) -> str:
    if not job:
        return "当前聊天还没有正在自动更新的岗位监控任务。你可以直接发 `/job 岗位关键词` 给我。"

    interval_seconds = job.get("interval_seconds")
    if interval_seconds:
        interval_text = _format_hours(interval_seconds / 60 / 60)
    else:
        interval_text = "仅搜索一次"
    lookback_hours = int(job.get("lookback_hours") or DEFAULT_LOOKBACK_HOURS)
    return (
        "当前监控任务：\n"
        f"关键词：{job.get('display_keyword') or job.get('keyword')}\n"
        f"搜索词：{job.get('keyword')}\n"
        f"时间窗口：最近{_format_hours(lookback_hours / 1)}\n"
        f"更新频率：{interval_text}"
    )


def format_stop_message(stopped: bool) -> str:
    if stopped:
        return "已经停止这个聊天里的自动更新任务。之后如果要重新开始，直接再发一次岗位需求就行。"
    return "当前聊天里没有正在运行的自动更新任务。"


def parse_job_constraints(text: str, keyword: str) -> Dict[str, Any]:
    cleaned = re.sub(r"[\s，。；、,.!?！？;：:]+", "", text or "")
    no_constraints = cleaned in {"无", "没有", "都可以", "不限", "无要求", "直接找", "都不需要直接找岗位信息"}
    lookback_hours = _parse_lookback_hours(text)
    interval_seconds = parse_update_interval_seconds(text)
    result_limit = parse_result_limit(text)
    if no_constraints:
        return {
            "raw_text": "",
            "search_keyword": keyword,
            "lookback_hours": lookback_hours or DEFAULT_LOOKBACK_HOURS,
            "interval_seconds": interval_seconds,
            "result_limit": result_limit,
        }
    search_hint = _clean_constraint_text_for_search(text)
    search_keyword = keyword if not search_hint else f"{keyword} {search_hint}"
    return {
        "raw_text": (text or "").strip(),
        "search_keyword": search_keyword.strip(),
        "lookback_hours": lookback_hours or DEFAULT_LOOKBACK_HOURS,
        "interval_seconds": interval_seconds,
        "result_limit": result_limit,
    }


def parse_update_interval_seconds(text: str) -> Optional[int]:
    cleaned = re.sub(r"\s+", "", text or "")
    if any(token in cleaned for token in ["只查一次", "只找一次", "只搜一次", "查一次", "不更新", "不用更新", "只差一次"]):
        return None
    if any(token in cleaned for token in ["每天更新", "一天一次", "每日更新"]):
        return 24 * 60 * 60
    if any(token in cleaned for token in ["每周更新", "一周一次", "每星期更新"]):
        return 7 * 24 * 60 * 60
    match = re.search(r"每(\d+)(小时|天|周)(更新)?(一次)?", cleaned)
    if match:
        value = int(match.group(1))
        unit = match.group(2)
        if unit == "小时":
            return value * 60 * 60
        if unit == "天":
            return value * 24 * 60 * 60
        return value * 7 * 24 * 60 * 60
    return DEFAULT_INTERVAL_SECONDS


def parse_result_limit(text: str) -> Optional[int]:
    cleaned = re.sub(r"\s+", "", text or "")
    match = re.search(r"(最近的?|只看|先找|先帮我找)?(\d+)(个|条)(帖子|岗位|招聘帖|笔记)", cleaned)
    if match:
        return int(match.group(2))
    return None


def _parse_lookback_hours(text: str) -> Optional[int]:
    cleaned = re.sub(r"\s+", "", text or "")
    if any(token in cleaned for token in ["24小时", "一天", "1天"]):
        return 24
    match = re.search(r"最近(\d+)(小时|天|周|个月|月)", cleaned)
    if match:
        value = int(match.group(1))
        unit = match.group(2)
        if unit == "小时":
            return value
        if unit == "天":
            return value * 24
        if unit == "周":
            return value * 7 * 24
        return value * 30 * 24
    if "一周" in cleaned or "本周" in cleaned:
        return 7 * 24
    if "一个月" in cleaned or "1个月" in cleaned or "近一个月" in cleaned:
        return 30 * 24
    return None


def _clean_constraint_text_for_search(text: str) -> str:
    cleaned = (text or "").strip()
    cleaned = re.sub(r"(最近的?|只看|先找|先帮我找)?\d+(个|条)(帖子|岗位|招聘帖|笔记)", " ", cleaned)
    cleaned = re.sub(r"先帮我找|先找", " ", cleaned)
    cleaned = re.sub(r"最近\s*\d+\s*(小时|天|周|个月|月)(的)?(新帖|帖子)?", " ", cleaned)
    cleaned = re.sub(r"(最近)?(一周|一个月|24\s*小时|本周|近一个月)(的)?(新帖|帖子)?", " ", cleaned)
    cleaned = re.sub(r"(默认)?每\s*\d+\s*(小时|天|周)(帮你)?更新(一次)?(最新岗位)?", " ", cleaned)
    cleaned = re.sub(r"(每天更新一次|一天一次|每日更新|每周更新|一周一次|每星期更新|只查一次|只找一次|只搜一次|只差一次|查一次|不更新|不用更新)", " ", cleaned)
    cleaned = re.sub(r"[，。；、,.!?！？;：:]+", " ", cleaned)
    cleaned = re.sub(r"(只看|优先|希望|想看|接受|地点|城市|公司|偏好|岗位类型|时间要求|更新周期)", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if cleaned in {"无", "没有", "都可以", "不限", "无要求", "直接找", "都不需要 直接找岗位信息"}:
        return ""
    return cleaned


def table_name_for_keyword(keyword: str) -> str:
    safe = re.sub(r"[\\/:*?\"<>|#%&{}$!'@+`=]", "_", keyword).strip()
    return safe[:80] or "小红书招聘"


def extract_message(payload: Dict[str, Any]) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    event = payload.get("event") or {}
    message = event.get("message") or payload.get("message") or {}
    chat_id = message.get("chat_id") or event.get("chat_id")
    message_id = message.get("message_id") or event.get("message_id")
    content = message.get("content") or ""
    if isinstance(content, str):
        try:
            content_data = json.loads(content)
            text = content_data.get("text", content)
        except json.JSONDecodeError:
            text = content
    elif isinstance(content, dict):
        text = content.get("text", "")
    else:
        text = ""
    return chat_id, message_id, text


def run_sync(config_path: str, keyword: str, table_id: str, limit: int, lookback_hours: Optional[int] = None) -> Dict[str, Any]:
    cmd = [
        sys.executable,
        str(CURRENT_DIR / "run_search_sync.py"),
        "--config",
        config_path,
        "--table-id",
        table_id,
        "--login-if-needed",
        "--json",
    ]
    cmd.extend(["--keyword", keyword])
    if limit:
        cmd.extend(["--limit", str(limit)])
    if lookback_hours:
        cmd.extend(["--lookback-hours", str(lookback_hours)])
    try:
        process = subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
            timeout=DEFAULT_SYNC_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "ok": False,
            "errors": [
                {
                    "category": "subprocess_timeout",
                    "message": f"run_search_sync.py exceeded {DEFAULT_SYNC_TIMEOUT_SECONDS} seconds",
                    "stdout": (exc.stdout or "")[-2000:],
                    "stderr": (exc.stderr or "")[-2000:],
                }
            ],
            "stats": {},
        }
    try:
        payload = json.loads(process.stdout)
    except json.JSONDecodeError:
        payload = {
            "ok": False,
            "errors": [{"category": "subprocess_error", "message": process.stderr or process.stdout}],
            "stats": {},
        }
    if process.returncode != 0 and payload.get("ok") is not False:
        payload["ok"] = False
    return payload


def format_result_message(keyword: str, table_name: str, app_token: str, table_id: str, result: Dict[str, Any], next_update_hours: Optional[float] = None) -> str:
    link = f"https://feishu.cn/base/{app_token}?table={table_id}"
    stats = result.get("stats") or {}
    written = int(stats.get("records_created", 0) or 0) + int(stats.get("records_updated", 0) or 0)
    if result.get("ok") is False:
        return "这次岗位信息更新没有完成"
    if written == 0:
        return (
            "这次暂时没有找到符合条件的岗位\n"
            f"你可以在这里查看表格：{link}"
        )
    text = (
        "最新岗位信息已经更新到表格里\n"
        f"你可以在这里查看最新结果：{link}\n"
        f"{_format_top_jobs(result)}"
    )
    max_record_warning = _find_max_record_warning(result)
    if max_record_warning:
        text += (
            f"\n由于选择的时间窗口比较长，我优先根据发布时间和岗位匹配度找到了{max_record_warning.get('max_records', 50)}个岗位，"
            "如果需要更多，可以告诉我数字"
        )
    if next_update_hours:
        text += f"\n根据你的设置，下次更新会在{_format_hours(next_update_hours)}后"
    return text


def _find_max_record_warning(result: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    for warning in result.get("warnings") or []:
        if warning.get("category") == "max_records_reached":
            return warning
    return None


def _format_top_jobs(result: Dict[str, Any], limit: int = 5) -> str:
    items = result.get("data") or []
    if not items:
        return "本次没有可直接展示的岗位摘要。"

    lines = ["这次先帮你整理了几个重点岗位："]
    for index, item in enumerate(items[:limit], start=1):
        company = item.get("company") or "未知公司"
        job_title = item.get("job_title") or "未知岗位"
        location = item.get("location") or "地点未注明"
        publish_time = item.get("publish_time") or "发布时间未注明"
        note_url = item.get("note_url") or ""
        line = f"{index}. {company} | {job_title} | {location} | {publish_time}"
        if note_url:
            line += f"\n{note_url}"
        lines.append(line)
    return "\n".join(lines)


def _format_hours(hours: float) -> str:
    if hours < 1:
        minutes = max(1, int(round(hours * 60)))
        return f"{minutes}分钟"
    if float(hours).is_integer() and int(hours) % 24 == 0:
        return f"{int(hours) // 24}天"
    if float(hours).is_integer():
        return f"{int(hours)}小时"
    return f"{hours:.1f}小时"

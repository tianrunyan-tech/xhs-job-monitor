#!/usr/bin/env python3
import argparse
import json
import sys
import time
from pathlib import Path

CURRENT_DIR = Path(__file__).resolve().parent
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))

from adapters.feishu_bitable import FeishuBitableAdapter, FeishuError
from adapters.keyword_expand import KeywordExpandError, OpenAICompatibleKeywordExpander
from adapters.llm_extract import LlmExtractError, OpenAICompatibleExtractor
from adapters.xhs_cli import XhsCliAdapter, XhsCliError
from bot_logic import expand_search_keywords, table_name_for_keyword
from config_loader import load_config
from schemas import RunResult, RunStats
from utils import compact_text, ensure_cache_dir, is_within_hours, merge_error, parse_datetime, read_json_file, stable_hash, write_json_file

CROSS_RUN_NOTE_CACHE_FILE = "processed_note_ids.json"
CROSS_RUN_NOTE_CACHE_LIMIT = 5000
KEYWORD_EXPAND_CACHE_FILE = "keyword_expand_cache.json"
KEYWORD_EXPAND_CACHE_LIMIT = 500


def log_progress(event, **fields):
    print(json.dumps({"event": event, **fields}, ensure_ascii=False), file=sys.stderr, flush=True)


def elapsed_ms(started_at: float) -> int:
    return int((time.perf_counter() - started_at) * 1000)


def trace_timings_dict(trace):
    if not isinstance(trace, dict):
        return {}
    timings = trace.get("timings")
    if not isinstance(timings, dict):
        return {}
    return timings


def build_record(note, extraction, error_message="", parse_status="parsed"):
    def text(value):
        if value is None:
            return None
        return str(value)

    return {
        "note_id": text(note.note_id),
        "company": text(extraction.company),
        "job_title": text(extraction.job_title),
        "position_info": text(extraction.position_info),
        "requirement": text(extraction.requirement),
        "location": text(extraction.location),
        "publish_time": text(note.publish_time),
        "contact_info": text(extraction.contact_info),
        "note_url": text(note.note_url),
    }


def resolve_keywords(config_keywords, cli_keywords, expander=None):
    if cli_keywords:
        keywords = []
        for item in cli_keywords:
            try:
                expanded_items = expander.expand(item) if expander else expand_search_keywords(item)
            except KeywordExpandError:
                expanded_items = expand_search_keywords(item)
            for expanded in expanded_items:
                if expanded not in keywords:
                    keywords.append(expanded)
        return keywords
    return config_keywords


def normalize_keyword_cache_key(keyword: str) -> str:
    return compact_text(keyword).replace(" ", "").lower()


def load_keyword_expand_cache(cache_dir: str) -> dict:
    cache_path = ensure_cache_dir(cache_dir) / KEYWORD_EXPAND_CACHE_FILE
    payload = read_json_file(cache_path, {"items": {}})
    items = payload.get("items") if isinstance(payload, dict) else {}
    if not isinstance(items, dict):
        items = {}
    cleaned = {}
    for key, value in items.items():
        normalized_key = str(key or "").strip()
        if not normalized_key or not isinstance(value, list):
            continue
        normalized_values = []
        for item in value:
            text = compact_text(item)
            if text and text not in normalized_values:
                normalized_values.append(text)
        if normalized_values:
            cleaned[normalized_key] = normalized_values
    return {"path": cache_path, "items": cleaned, "dirty": False}


def save_keyword_expand_cache(cache: dict) -> None:
    if not cache.get("dirty"):
        return
    items = cache.get("items") or {}
    if len(items) > KEYWORD_EXPAND_CACHE_LIMIT:
        trimmed_keys = list(items.keys())[-KEYWORD_EXPAND_CACHE_LIMIT:]
        items = {key: items[key] for key in trimmed_keys}
        cache["items"] = items
    write_json_file(cache["path"], {"items": items})
    cache["dirty"] = False


def resolve_keywords_with_cache(config_keywords, cli_keywords, expander, cache: dict):
    if not cli_keywords:
        return config_keywords
    keywords = []
    items = cache.get("items") if isinstance(cache, dict) else {}
    for item in cli_keywords:
        cache_key = normalize_keyword_cache_key(item)
        expanded_items = items.get(cache_key)
        if not expanded_items:
            try:
                expanded_items = expander.expand(item) if expander else expand_search_keywords(item)
            except KeywordExpandError:
                expanded_items = expand_search_keywords(item)
            normalized_values = []
            for expanded in expanded_items:
                text = compact_text(expanded)
                if text and text not in normalized_values:
                    normalized_values.append(text)
            expanded_items = normalized_values
            if cache_key and expanded_items:
                items[cache_key] = expanded_items
                cache["dirty"] = True
        for expanded in expanded_items:
            if expanded not in keywords:
                keywords.append(expanded)
    return keywords


def match_score(note, extraction, keywords):
    target = compact_text([note.title, note.raw_text, note.first_comment, extraction.company, extraction.job_title, extraction.position_info, extraction.requirement])
    normalized_target = target.replace(" ", "").lower()
    score = 0
    for keyword in keywords:
        normalized_keyword = compact_text(keyword).replace(" ", "").lower()
        if normalized_keyword and normalized_keyword in normalized_target:
            score += 10
        for token in re_split_keyword(normalized_keyword):
            if token and token in normalized_target:
                score += 1
    return score


def is_role_compatible(raw_keywords, extraction):
    target = "".join(compact_text(item) for item in raw_keywords)
    job_title = compact_text(extraction.job_title)
    if not job_title:
        return False
    if "产品运营" in target:
        return "产品" in job_title and "运营" in job_title
    if "运营" in target:
        return "运营" in job_title
    if "产品经理" in target:
        if "产品" not in job_title:
            return False
        incompatible_tokens = ["运营", "研发", "开发", "工程", "算法", "测试", "设计", "销售", "市场", "商务", "hr", "行政", "财务", "法务"]
        return not any(token in job_title.lower() for token in incompatible_tokens)
    return True


def validate_candidate_before_write(raw_keywords, detail, extraction):
    if not is_role_compatible(raw_keywords, extraction):
        return False, "role_mismatch"
    if not compact_text(extraction.job_title):
        return False, "missing_job_title"
    if not compact_text(extraction.position_info) and not compact_text(extraction.requirement):
        return False, "missing_jd_details"
    return True, ""


def skip_candidate(stats, warnings, note_id, reason):
    stats.records_skipped += 1
    warnings.append({"category": "candidate_skipped", "note_id": note_id, "reason": reason})


def re_split_keyword(keyword):
    import re
    return [item for item in re.split(r"[^\w\u4e00-\u9fff]+", keyword) if item]


def publish_sort_value(value):
    parsed = parse_datetime(value)
    if parsed is None:
        return 0
    return parsed.timestamp()


def default_field_schema():
    return [
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


def build_note_cache_key(note_id: str, raw_keywords) -> str:
    normalized_note_id = str(note_id or "").strip()
    normalized_keywords = [compact_text(item).replace(" ", "").lower() for item in (raw_keywords or []) if compact_text(item)]
    return stable_hash([normalized_note_id, sorted(normalized_keywords)])


def load_processed_note_cache(cache_dir: str) -> dict:
    cache_path = ensure_cache_dir(cache_dir) / CROSS_RUN_NOTE_CACHE_FILE
    payload = read_json_file(cache_path, {"keys": []})
    keys = payload.get("keys") if isinstance(payload, dict) else []
    if not isinstance(keys, list):
        keys = []
    cleaned = [str(key).strip() for key in keys if str(key).strip()]
    return {"path": cache_path, "keys": cleaned, "seen": set(cleaned), "dirty": False}


def mark_note_processed(cache: dict, cache_key: str) -> None:
    normalized = str(cache_key or "").strip()
    if not normalized or normalized in cache["seen"]:
        return
    cache["keys"].append(normalized)
    cache["seen"].add(normalized)
    if len(cache["keys"]) > CROSS_RUN_NOTE_CACHE_LIMIT:
        overflow = len(cache["keys"]) - CROSS_RUN_NOTE_CACHE_LIMIT
        removed = cache["keys"][:overflow]
        cache["keys"] = cache["keys"][overflow:]
        for item in removed:
            cache["seen"].discard(item)
        cache["seen"].update(cache["keys"])
    cache["dirty"] = True


def save_processed_note_cache(cache: dict) -> None:
    if not cache.get("dirty"):
        return
    write_json_file(cache["path"], {"keys": cache["keys"]})
    cache["dirty"] = False


def should_skip_summary_by_title(note) -> bool:
    text = compact_text(note.title).lower()
    if not text:
        return False
    positive_signals = ["招聘", "招人", "招募", "急招", "内推", "继任", "岗位", "hc", "base", "实习生", "jd"]
    negative_signals = [
        "面经",
        "面试",
        "基本功",
        "day1",
        "复盘",
        "总结",
        "心得",
        "经验",
        "上岸",
        "指令",
        "拿了",
        "offer",
        "困惑",
        "怎么准备",
        "怎么",
        "必问",
        "抽奖",
        "选offer",
        "求帮选",
        "焦虑",
        "一面",
        "二面",
        "三面",
        "群面",
    ]
    if any(token in text for token in positive_signals):
        return False
    return any(token in text for token in negative_signals)


def should_fetch_first_comment(detail) -> bool:
    return True


def run_with_optional_login_retry(xhs, operation, allow_login):
    try:
        return operation()
    except XhsCliError as exc:
        if exc.category != "auth_error" or not allow_login:
            raise
        xhs.ensure_authenticated(allow_qrcode=True)
        return operation()


def upsert_candidate(feishu, stats, errors, data, item):
    detail = item["detail"]
    extraction = item["extraction"]
    record = build_record(detail, extraction, error_message=item["error_message"], parse_status=item["parse_status"])
    try:
        if "existing_record" in item:
            existing = item["existing_record"]
            if existing:
                feishu.update_record(existing["record_id"], record)
                outcome = "updated"
            else:
                feishu.create_record(record)
                outcome = "created"
        else:
            outcome = feishu.upsert_by_note_id(detail.note_id, record)
    except FeishuError as exc:
        merge_error(errors, "feishu_error", str(exc), detail.note_id)
        stats.errors += 1
        return False
    if outcome == "created":
        stats.records_created += 1
    else:
        stats.records_updated += 1
    stats.notes_parsed += 1
    data.append(
        {
            "note_id": detail.note_id,
            "action": outcome,
            "parse_status": item["parse_status"],
            "match_score": item["match_score"],
            "company": record.get("company"),
            "job_title": record.get("job_title"),
            "location": record.get("location"),
            "publish_time": record.get("publish_time"),
            "contact_info": record.get("contact_info"),
            "note_url": record.get("note_url"),
        }
    )
    return True


def select_candidates_for_limit(feishu, candidates, limit, stats, errors, warnings):
    if not limit:
        return candidates

    new_candidates = []
    existing_candidates = []
    for item in candidates:
        note_id = item["detail"].note_id
        try:
            existing = feishu.find_record_by_note_id(note_id)
        except FeishuError as exc:
            merge_error(errors, "feishu_error", f"Failed to precheck note_id before limit selection: {exc}", note_id)
            stats.errors += 1
            continue
        item["existing_record"] = existing
        if existing:
            existing_candidates.append(item)
        else:
            new_candidates.append(item)

    selected = (new_candidates + existing_candidates)[:limit]
    overflow = len(new_candidates) + len(existing_candidates) - len(selected)
    if overflow > 0:
        stats.records_skipped += overflow
        warnings.append(
            {
                "category": "max_records_reached",
                "message": "valid job records exceeded the write limit; new records were prioritized before existing updates",
                "max_records": limit,
                "overflow": overflow,
                "new_candidates": len(new_candidates),
                "existing_candidates": len(existing_candidates),
            }
        )
    return selected


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--keyword", action="append", default=[], help="Override config keywords; repeat to pass multiple keywords.")
    parser.add_argument("--app-token", default="", help="Override feishu.app_token from config.")
    parser.add_argument("--table-id", default="", help="Override feishu.table_id from config.")
    parser.add_argument("--auto-table", action="store_true", help="Create or reuse a per-keyword Feishu table instead of using config feishu.table_id.")
    parser.add_argument("--lookback-hours", type=int, default=0, help="Override search.lookback_hours from config.")
    parser.add_argument("--limit", type=int, default=0, help="Maximum job records to write after filtering and ranking; 0 means no limit.")
    parser.add_argument("--stop-after-writes", action="store_true", help="Write matching jobs immediately and stop once --limit records are written.")
    parser.add_argument("--login-if-needed", action="store_true", help="Check xhs login status before search and show a QR code login flow if the session is expired.")
    parser.add_argument("--debug-trace", action="store_true", help="Include per-note debug trace in the final JSON output for testing.")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()

    config = load_config(args.config).raw
    raw_keywords = resolve_keywords(config["keywords"], args.keyword)
    keyword_expander = OpenAICompatibleKeywordExpander(config["llm"])
    keyword_expand_cache = load_keyword_expand_cache(config["runtime"]["cache_dir"])
    config["keywords"] = resolve_keywords_with_cache(config["keywords"], args.keyword, keyword_expander, keyword_expand_cache)
    if args.app_token:
        config["feishu"]["app_token"] = args.app_token
    if args.table_id:
        config["feishu"]["table_id"] = args.table_id
    if args.lookback_hours:
        config["search"]["lookback_hours"] = args.lookback_hours
    xhs = XhsCliAdapter(config["runtime"]["xhs_command"])
    llm = OpenAICompatibleExtractor(config["llm"])
    feishu = FeishuBitableAdapter(config["feishu"])
    try:
        xhs.ensure_authenticated(allow_qrcode=args.login_if_needed)
    except XhsCliError as exc:
        merge_error(errors := [], exc.category, exc.message)
        stats = RunStats(keywords=len(config["keywords"]))
        result = RunResult(False, "1", "search_sync", stats, [], errors, [])
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
        return 1
    if args.auto_table:
        table_keyword = raw_keywords[0] if raw_keywords else config["keywords"][0]
        config["feishu"]["table_id"] = feishu.ensure_table(table_name_for_keyword(table_keyword), default_field_schema())
        feishu = FeishuBitableAdapter(config["feishu"])
    stats = RunStats(keywords=len(config["keywords"]))
    errors = []
    data = []
    warnings = []
    debug = []
    processed_note_cache = load_processed_note_cache(config["runtime"]["cache_dir"])

    seen_ids = set()
    candidates = []

    try:
        for keyword in config["keywords"]:
            log_progress("keyword_start", keyword=keyword)
            for page in range(1, config["search"]["max_pages"] + 1):
                log_progress("search_page_start", keyword=keyword, page=page)
                try:
                    search_started_at = time.perf_counter()
                    notes = run_with_optional_login_retry(
                        xhs,
                        lambda keyword=keyword, page=page: xhs.search(keyword, config["search"]["sort"], config["search"]["note_type"], page),
                        args.login_if_needed,
                    )
                except XhsCliError as exc:
                    if exc.category in {"auth_error", "captcha_required", "ip_blocked", "rate_limited"}:
                        raise
                    merge_error(errors, exc.category, exc.message)
                    stats.errors += 1
                    continue
                log_progress("search_page_done", keyword=keyword, page=page, note_count=len(notes), elapsed_ms=elapsed_ms(search_started_at))
                if not notes:
                    continue
                for note in notes:
                    cache_key = build_note_cache_key(note.note_id, raw_keywords)
                    if note.note_id in seen_ids:
                        continue
                    seen_ids.add(note.note_id)
                    stats.notes_seen += 1
                    log_progress("note_seen", keyword=keyword, note_id=note.note_id, publish_time=note.publish_time, title=note.title)
                    if cache_key in processed_note_cache["seen"]:
                        stats.records_skipped += 1
                        log_progress("note_skipped", note_id=note.note_id, reason="cross_run_note_cache_hit")
                        continue
                    if should_skip_summary_by_title(note):
                        stats.records_skipped += 1
                        log_progress("note_skipped", note_id=note.note_id, reason="summary_title_filtered")
                        continue
                    if not is_within_hours(note.publish_time, config["search"]["lookback_hours"]):
                        stats.records_skipped += 1
                        log_progress("note_skipped", note_id=note.note_id, reason="out_of_lookback_window")
                        continue
                    try:
                        note_ref = note.note_url or note.note_id
                        if note.xsec_token:
                            note_ref = f"{note.note_id}#xsec_token={note.xsec_token}"
                        log_progress("note_read_start", note_id=note.note_id)
                        note_read_started_at = time.perf_counter()
                        detail = run_with_optional_login_retry(
                            xhs,
                            lambda note_ref=note_ref, keyword=keyword: xhs.read_note(note_ref, keyword, fetch_first_comment=False),
                            args.login_if_needed,
                        )
                        note_read_elapsed_ms = elapsed_ms(note_read_started_at)
                        first_comment_elapsed_ms = 0
                        if should_fetch_first_comment(detail):
                            first_comment_started_at = time.perf_counter()
                            detail.first_comment = run_with_optional_login_retry(
                                xhs,
                                lambda note_ref=note_ref: xhs.first_comment(note_ref),
                                args.login_if_needed,
                            )
                            first_comment_elapsed_ms = elapsed_ms(first_comment_started_at)
                        log_progress(
                            "note_read_done",
                            note_id=note.note_id,
                            first_comment_len=len(detail.first_comment or ""),
                            read_elapsed_ms=note_read_elapsed_ms,
                            first_comment_elapsed_ms=first_comment_elapsed_ms,
                        )
                    except XhsCliError as exc:
                        if exc.category in {"auth_error", "captcha_required", "ip_blocked", "rate_limited"}:
                            raise
                        merge_error(errors, exc.category, exc.message, note.note_id)
                        stats.errors += 1
                        log_progress("note_read_failed", note_id=note.note_id, error=exc.message)
                        continue
                    try:
                        log_progress("llm_extract_start", note_id=detail.note_id)
                        llm_started_at = time.perf_counter()
                        if args.debug_trace:
                            extraction, trace = llm.extract_with_trace(detail)
                        else:
                            extraction = llm.extract(detail)
                            trace = {}
                        llm_elapsed_ms = elapsed_ms(llm_started_at)
                        trace_timings = trace_timings_dict(trace)
                        log_progress(
                            "llm_extract_done",
                            note_id=detail.note_id,
                            is_job_post=extraction.is_job_post,
                            company=extraction.company,
                            job_title=extraction.job_title,
                            elapsed_ms=llm_elapsed_ms,
                            classify_elapsed_ms=trace_timings.get("classify_elapsed_ms", 0),
                            extract_elapsed_ms=trace_timings.get("extract_elapsed_ms", 0),
                            secondary_review_elapsed_ms=trace_timings.get("secondary_review_elapsed_ms", 0),
                        )
                        if not extraction.is_job_post:
                            skip_candidate(stats, warnings, detail.note_id, "not_job_post")
                            log_progress("candidate_skipped", note_id=detail.note_id, reason="not_job_post")
                            continue
                        error_message = ""
                        valid, skip_reason = validate_candidate_before_write(raw_keywords, detail, extraction)
                        if args.debug_trace:
                            debug.append(
                                {
                                    "note_id": detail.note_id,
                                    "note_url": detail.note_url,
                                    "title": detail.title,
                                    "raw_text": detail.raw_text,
                                    "first_comment": detail.first_comment,
                                    "trace": trace,
                                    "valid_before_write": valid,
                                    "skip_reason": skip_reason if not valid else "",
                                }
                            )
                        if not valid:
                            skip_candidate(stats, warnings, detail.note_id, skip_reason)
                            log_progress("candidate_skipped", note_id=detail.note_id, reason=skip_reason)
                            continue
                        parse_status = "parsed"
                    except LlmExtractError as exc:
                        from schemas import JobExtraction
                        extraction = JobExtraction.empty_failure()
                        parse_status = "failed"
                        error_message = str(exc)
                        merge_error(errors, "llm_error", str(exc), detail.note_id)
                        stats.errors += 1
                        log_progress("llm_extract_failed", note_id=detail.note_id, error=str(exc))
                        continue
                    mark_note_processed(processed_note_cache, cache_key)
                    candidate = {
                        "detail": detail,
                        "extraction": extraction,
                        "error_message": error_message,
                        "parse_status": parse_status,
                        "match_score": match_score(detail, extraction, config["keywords"]),
                    }
                    if args.stop_after_writes:
                        log_progress("upsert_start", note_id=detail.note_id, mode="immediate")
                        upsert_started_at = time.perf_counter()
                        upsert_candidate(feishu, stats, errors, data, candidate)
                        log_progress("upsert_done", note_id=detail.note_id, created=stats.records_created, updated=stats.records_updated, elapsed_ms=elapsed_ms(upsert_started_at))
                        if args.limit and stats.notes_parsed >= args.limit:
                            break
                    else:
                        candidates.append(candidate)
                        log_progress("candidate_buffered", note_id=detail.note_id, match_score=candidate["match_score"])
                if args.stop_after_writes and args.limit and stats.notes_parsed >= args.limit:
                    break
            if args.stop_after_writes and args.limit and stats.notes_parsed >= args.limit:
                break
    except XhsCliError as exc:
        merge_error(errors, exc.category, exc.message)
        stats.errors += 1
        save_processed_note_cache(processed_note_cache)
        result = RunResult(False, "1", "search_sync", stats, data, errors, warnings, debug)
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
        return 1

    if not args.stop_after_writes:
        candidates.sort(key=lambda item: (publish_sort_value(item["detail"].publish_time), item["match_score"]), reverse=True)
        selected = select_candidates_for_limit(feishu, candidates, args.limit, stats, errors, warnings)
        log_progress("selected_candidates", count=len(selected), limit=args.limit or 0)

        for item in selected:
            log_progress("upsert_start", note_id=item["detail"].note_id, mode="batch")
            upsert_started_at = time.perf_counter()
            upsert_candidate(feishu, stats, errors, data, item)
            log_progress("upsert_done", note_id=item["detail"].note_id, created=stats.records_created, updated=stats.records_updated, elapsed_ms=elapsed_ms(upsert_started_at))

    result = RunResult(True, "1", "search_sync", stats, data, errors, warnings, debug)
    log_progress("run_complete", ok=True, seen=stats.notes_seen, parsed=stats.notes_parsed, created=stats.records_created, updated=stats.records_updated, errors=stats.errors)
    save_processed_note_cache(processed_note_cache)
    save_keyword_expand_cache(keyword_expand_cache)
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

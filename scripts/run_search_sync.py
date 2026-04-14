#!/usr/bin/env python3
import argparse
import json
import sys
from pathlib import Path

CURRENT_DIR = Path(__file__).resolve().parent
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))

from adapters.feishu_bitable import FeishuBitableAdapter, FeishuError
from adapters.keyword_expand import KeywordExpandError, OpenAICompatibleKeywordExpander
from adapters.llm_extract import LlmExtractError, OpenAICompatibleExtractor, is_traffic_referral_ad
from adapters.xhs_cli import XhsCliAdapter, XhsCliError
from bot_logic import expand_search_keywords, table_name_for_keyword
from config_loader import load_config
from schemas import RunResult, RunStats
from utils import compact_text, is_within_hours, merge_error, parse_datetime


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


def match_score(note, extraction, keywords):
    target = compact_text([note.title, note.raw_text, note.image_text, extraction.company, extraction.job_title, extraction.position_info, extraction.requirement])
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
        return "产品经理" in job_title
    return True


def validate_candidate_before_write(raw_keywords, detail, extraction):
    if not extraction.is_job_post:
        return False, "not_job_post"
    if is_traffic_referral_ad(detail):
        return False, "traffic_referral_ad"
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
    data.append({"note_id": detail.note_id, "action": outcome, "parse_status": item["parse_status"], "match_score": item["match_score"]})
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
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()

    config = load_config(args.config).raw
    raw_keywords = resolve_keywords(config["keywords"], args.keyword)
    keyword_expander = OpenAICompatibleKeywordExpander(config["llm"])
    config["keywords"] = resolve_keywords(config["keywords"], args.keyword, keyword_expander)
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

    seen_ids = set()
    candidates = []

    try:
        for keyword in config["keywords"]:
            for page in range(1, config["search"]["max_pages"] + 1):
                try:
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
                if not notes:
                    continue
                for note in notes:
                    if note.note_id in seen_ids:
                        continue
                    seen_ids.add(note.note_id)
                    stats.notes_seen += 1
                    if not is_within_hours(note.publish_time, config["search"]["lookback_hours"]):
                        stats.records_skipped += 1
                        continue
                    try:
                        note_ref = note.note_url or note.note_id
                        if note.xsec_token:
                            note_ref = f"{note.note_id}#xsec_token={note.xsec_token}"
                        detail = run_with_optional_login_retry(
                            xhs,
                            lambda note_ref=note_ref, keyword=keyword: xhs.read_note(note_ref, keyword),
                            args.login_if_needed,
                        )
                    except XhsCliError as exc:
                        if exc.category in {"auth_error", "captcha_required", "ip_blocked", "rate_limited"}:
                            raise
                        merge_error(errors, exc.category, exc.message, note.note_id)
                        stats.errors += 1
                        continue
                    try:
                        extraction = llm.extract(detail)
                        error_message = ""
                        valid, skip_reason = validate_candidate_before_write(raw_keywords, detail, extraction)
                        if not valid:
                            skip_candidate(stats, warnings, detail.note_id, skip_reason)
                            continue
                        parse_status = "parsed"
                    except LlmExtractError as exc:
                        from schemas import JobExtraction
                        extraction = JobExtraction.empty_failure()
                        parse_status = "failed"
                        error_message = str(exc)
                        merge_error(errors, "llm_error", str(exc), detail.note_id)
                        stats.errors += 1
                        continue
                    candidate = {
                        "detail": detail,
                        "extraction": extraction,
                        "error_message": error_message,
                        "parse_status": parse_status,
                        "match_score": match_score(detail, extraction, config["keywords"]),
                    }
                    if args.stop_after_writes:
                        upsert_candidate(feishu, stats, errors, data, candidate)
                        if args.limit and stats.notes_parsed >= args.limit:
                            break
                    else:
                        candidates.append(candidate)
                if args.stop_after_writes and args.limit and stats.notes_parsed >= args.limit:
                    break
            if args.stop_after_writes and args.limit and stats.notes_parsed >= args.limit:
                break
    except XhsCliError as exc:
        merge_error(errors, exc.category, exc.message)
        stats.errors += 1
        result = RunResult(False, "1", "search_sync", stats, data, errors, warnings)
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
        return 1

    if not args.stop_after_writes:
        candidates.sort(key=lambda item: (publish_sort_value(item["detail"].publish_time), item["match_score"]), reverse=True)
        selected = select_candidates_for_limit(feishu, candidates, args.limit, stats, errors, warnings)

        for item in selected:
            upsert_candidate(feishu, stats, errors, data, item)

    result = RunResult(True, "1", "search_sync", stats, data, errors, warnings)
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

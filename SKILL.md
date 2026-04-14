---
name: xhs-job-monitor
description: End-to-end Xiaohongshu recruiting post monitoring and Feishu bitable sync. Use when Codex needs to search Xiaohongshu job posts by keyword, read note details and first comments, extract structured hiring fields with an LLM, and upsert Feishu bitable records by note_id. 
---

# XHS Job Monitor

File layout:

- `SKILL.md`: skill trigger, usage policy, and high-level workflow.
- `scripts/run_search_sync.py`: main ingestion pipeline for Codex or scheduled runs.
- `scripts/adapters/`: external integrations for Xiaohongshu, Feishu, LLM extraction, and keyword expansion.
- `scripts/bot_logic.py`, `scripts/bot_ws_client.py`, `scripts/bot_server.py`: optional Feishu bot entrypoints and shared bot message logic.
- `tests/`: focused regression tests for parsing, extraction, syncing, and adapters.
- `references/`: config examples, Feishu schema, prompt contract, optional bot deployment templates, and operational notes.

Check credentials before running:

- Ensure `xhs` is installed. Prefer passing `--login-if-needed` to the search script so the terminal shows a Xiaohongshu QR code when the session is expired.
- Ensure the config file contains Feishu app credentials, bitable IDs, and LLM endpoint credentials.
- Ensure the target Feishu table contains the fields defined in `references/feishu-field-schema.md`.

Runtime input expectations:

- Treat `keywords` as user-supplied input. Update the config file or generate it dynamically before each run.
- Default `search.note_type` to image-and-text notes only. Use video notes only if the operator explicitly changes the config.

Use `scripts/run_search_sync.py` for the ingestion pipeline when you need to:

- search one or more Xiaohongshu keywords
- read note details and the first comment sequentially
- extract `company`, `job_title`, `position_info`, `requirement`, `location`, and `contact_info`
- upsert records into Feishu by `note_id`
- emit a stable machine-readable result envelope

For interactive Terminal/Codex runs, pass `--login-if-needed` by default. If `xhs status` reports an expired session or a search/read call returns `auth_error`, the script should launch `xhs login --qrcode`, display the QR code in the terminal, wait for the user to scan, then retry the failed xhs operation once.

Keyword input options:

- Pass `--keyword "词1" --keyword "词2"` to override the config file at runtime.
- Omit `--keyword` to use the `keywords` list already stored in the config file.
- Pass `--table-id "tbl..."` when a Feishu bot creates or selects a per-keyword table dynamically.
- Runtime user keywords are expanded with the configured LLM into high-relevance Xiaohongshu search keywords before search; if LLM expansion fails, use the local deterministic fallback.

Optional Feishu bot integration:

- Prefer `scripts/bot_ws_client.py` for long-connection mode when the bot must stay online and support scheduled follow-up updates.
- Use `scripts/bot_server.py` only as an HTTP callback fallback. It can process an incoming request and reply after a run, but it does not own a durable scheduler by itself.
- The bot first collects one round of user constraints such as company preference, location, job type, lookback window, and update cadence, then creates or reuses one table per constrained keyword under the configured base, runs search sync, and replies with the table link and stats.

Load extra references only when needed:

- Read `references/feishu-field-schema.md` before creating or auditing the Feishu table.
- Read `references/prompt-contract.md` before changing extraction fields, enums, or LLM prompts.
- Read `references/operational-playbook.md` when handling auth failures, captcha, rate limits, or rollout questions.
- Read `references/com.xhs-job-monitor.bot.plist` only when setting up launchd for the optional long-connection Feishu bot.

Failure handling:

- Treat empty search results as a successful no-op run.
- Stop the whole run on `auth_error`, `captcha_required`, `ip_blocked`, or `rate_limited`.
- Continue per-note on parse, LLM, or Feishu record errors and include them in the output envelope.

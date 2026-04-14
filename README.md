# XHS Job Monitor

A Codex skill for monitoring Xiaohongshu recruiting posts, filtering noisy results, extracting structured job fields with an LLM, and syncing results to a Feishu Bitable.

## Who Is This For?

Students and job seekers looking for internships or campus recruiting opportunities through Xiaohongshu.

Xiaohongshu is a useful recruiting source because many posts are written by team members. For internships, especially replacement internships, posts often include a direct email, referral path, or private-message channel. The application path can be shorter than a standard job board flow and may not require the same HR screening steps.

The problem is that Xiaohongshu recruiting information is fragmented and noisy:

- **Low timeliness**: manual refreshes are slow, so candidates can miss the first hour after a post is published, which is often the best time to apply.
- **Low effiency**: default/latest ranking mixes many irrelevant results, including old posts, ads, referral traffic posts, agency posts, and mismatched jobs.
- **High extraction cost**: useful information is scattered across the note title, body text, images/OCR, and first comment, so manually copying it into a table is tedious.

## What It Does

The goal is to automate the full workflow from **search -> filtering -> structured extraction -> Feishu Bitable sync**, producing a high-timeliness recruiting dashboard with cleaner, more actionable job records.

- Expands a user job target into Xiaohongshu-friendly search keywords to improve recall.
- Searches Xiaohongshu notes by time window and reads note detail, OCR text, and first comments when available.
- Uses an LLM to classify whether a note is a real, concrete recruiting post.
- Extracts structured fields such as company, job title, location, responsibilities, requirements, contact info, publish time, and note URL.
- Filters traffic-style referral ads, agency-like posts, non-recruiting posts, and mismatched roles before writing records.
- Upserts records into Feishu Bitable by `note_id`, with newer and higher-match jobs prioritized.

## Setup

Copy the example files and fill your own local credentials:

```bash
cp .env.local.example .env.local
cp references/config.example.yaml config.local.yaml
```

Required local values:

- `MINIMAX_API_KEY` in `.env.local`
- Feishu app credentials and Bitable IDs in `config.local.yaml`
- Xiaohongshu CLI authentication via the configured `xhs` command

Local credential files are ignored by git.

## Run

```bash
source .env.local
python3 scripts/run_search_sync.py \
  --config config.local.yaml \
  --keyword "AI产品运营实习" \
  --auto-table \
  --limit 50 \
  --login-if-needed \
  --json
```

## Optional Bot Entry Points

- `scripts/bot_ws_client.py`: Feishu long-connection bot mode.
- `scripts/bot_server.py`: HTTP callback fallback.
- `references/com.xhs-job-monitor.bot.plist`: launchd template for the long-connection bot. Replace `/path/to/xhs-job-monitor` before use.

## Tests

```bash
python3 -m py_compile scripts/*.py scripts/adapters/*.py
python3 -m unittest discover -s tests
```

## Public Repo Safety

Before publishing, verify that only example configs are included:

- Keep `.env.local.example`.
- Keep `references/config.example.yaml`.
- Do not commit `.env.local`, `config.local.yaml`, `logs/`, `__pycache__/`, or `.DS_Store`.

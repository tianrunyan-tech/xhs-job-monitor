# XHS Job Monitor

[中文](README.md) | English

XHS Job Monitor is a Codex skill for monitoring Xiaohongshu recruiting posts, filtering noisy results, extracting structured job fields with an LLM, and syncing results to a Feishu Bitable.

## Who Is This For?

Students and job seekers looking for internships or campus recruiting opportunities through Xiaohongshu.

Xiaohongshu is a useful recruiting source because many posts are written by team members. For internships, especially replacement internships, posts often include a direct email, referral path, or private-message channel. The application path can be shorter than a standard job board flow and may not require the same HR screening steps.

The problem is that Xiaohongshu recruiting information is fragmented and noisy:

- **Low timeliness**: manual refreshes are slow, so candidates can miss the first hour after a post is published, which is often the best time to apply.
- **Low efficiency**: default/latest ranking mixes many irrelevant results, including old posts, ads, referral traffic posts, agency posts, and mismatched jobs.
- **High extraction cost**: useful information is scattered across the note title, body text, images/OCR, and first comment, so manually copying it into a table is tedious.

## What It Does

The goal is to automate the full workflow from **search -> filtering -> structured extraction -> Feishu Bitable sync**, producing a high-timeliness recruiting dashboard with cleaner, more actionable job records.

- Expands a user job target into Xiaohongshu-friendly search keywords to improve recall.
- Searches Xiaohongshu notes by time window and reads note detail, OCR text, and first comments.
- Uses an LLM to classify whether a note is a real, concrete recruiting post.
- Extracts structured fields such as company, job title, location, responsibilities, requirements, contact info, publish time, and note URL.
- Filters traffic-style referral ads, agency-like posts, non-recruiting posts, and mismatched roles before writing records.
- Deduplicates by `note_id` and syncs records to Feishu Bitable, prioritizing newer and higher-match jobs.

## Installation

Put this repository in the skill/command directory used by your agent.

**Codex:**

```bash
mkdir -p ~/.codex/skills
cp -R xhs-job-monitor ~/.codex/skills/xhs-job-monitor
```

**Other agents:**

Place it in the directory where your agent reads skill or command definitions.

## Prerequisites

- Install and configure [Xhs CLI](https://github.com/jackwener/xiaohongshu-cli)
- Create a Feishu Open Platform app and grant Bitable read/write permissions
- Prepare an LLM API key for keyword expansion and structured recruiting post extraction
- Copy the example config files and fill in your local credentials:

```bash
cp .env.local.example .env.local
cp references/config.example.yaml config.local.yaml
```

```bash
LLM_API_KEY="your_openai_compatible_api_key"
```

## Usage

Describe the job target directly to the agent:

```text
帮我找AI产品运营的实习岗位
```

You can also add filtering constraints:

```text
只看字节、腾讯、阿里等知名科技大厂和初创公司，最近3天。
```

The agent will confirm the job target and constraints, then search, filter, extract structured fields, and write the results to Feishu Bitable.

## Supported Capabilities

| Capability | What the Agent Does |
| ---------- | ------------------- |
| Constraint collection | Asks for company, location, job type, time window, update cadence, and other preferences before searching |
| Keyword expansion | Expands the user-entered job target into Xiaohongshu-friendly search keywords |
| Xiaohongshu search | Searches recruiting-related notes by keyword and time window |
| Note reading | Reads title, body text, image OCR text, and first comment |
| Recruiting post classification | Uses an LLM to filter interview experiences, job-seeking ads, agency/referral traffic posts, generic referral posts, and role mismatches |
| Structured extraction | Extracts company, role, city, responsibilities, requirements, contact info, publish time, and original note URL |
| Feishu sync | Deduplicates and writes records to Feishu Bitable |
| Scheduled updates | Continues searching for new posts using the user-defined or default update cadence |

## License

MIT

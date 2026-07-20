# XHS Job Monitor

[中文](README_CN.md) | English

XHS Job Monitor is a Codex skill for monitoring Xiaohongshu recruiting posts, filtering noisy results, extracting structured job fields with an LLM, and syncing results to a Feishu Bitable.

## Who Is This For?

Students and early-career candidates seeking internship or campus recruiting opportunities.

Beyond traditional job boards and corporate career sites, Xiaohongshu has emerged as a high-signal yet underutilized recruiting channel -- an **unstructured job market with strong informational edge**. As a highly active social platform, it offers several advantages over conventional hiring pipelines:

- **Direct access to hiring teams**  
  A significant portion of posts are created by frontline team members or outgoing interns, often for "replacement" roles. Compared to the traditional HR-driven funnel, the application path is substantially flatter and faster.

- **More transparent and authentic information**  
  Posts frequently include candid details about team context, responsibilities, and expectations. Many provide direct contact methods, such as team email or private messaging, enabling immediate communication without intermediary layers.

- **High-quality, rapidly growing supply**  
  Due to better targeting and faster response loops, an increasing number of teams are choosing Xiaohongshu as a primary channel for sourcing candidates.

Despite its advantages, recruiting information on Xiaohongshu is highly fragmented and noisy:

- **Limited timeliness**  
  Users rely on manual refresh and feed browsing, making it easy to miss the critical early window after a post goes live, often when response rates are highest.

- **Low search precision**  
  Both default and latest sorting are heavily polluted with irrelevant content, including outdated posts, personal interview write-ups, training advertisements, and agency-driven referral posts. Signal-to-noise ratio is low, and filtering is time-consuming.

- **High extraction cost**  
  Key information is distributed across multiple modalities: title, body text, images requiring OCR, and first comment. Manually consolidating this into a structured format is inefficient. Candidates may also lose track of submitted applications, and posts may be deleted.

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

If installing directly from GitHub:

```bash
mkdir -p ~/.codex/skills
git clone https://github.com/tianrunyan-tech/xhs-job-monitor.git ~/.codex/skills/xhs-job-monitor
```

If you have already downloaded this repository and are currently in the repository root:

```bash
mkdir -p ~/.codex/skills/xhs-job-monitor
cp -R SKILL.md README.md README_CN.md LICENSE .env.local.example references scripts tests ~/.codex/skills/xhs-job-monitor/
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

## Feishu Bot Interaction

If you want users to talk to a Feishu bot directly instead of using the terminal, the repository already includes a long-connection bot entrypoint.

1. Create a self-built Feishu app with bot capability and event subscription enabled.
2. Subscribe to the `message receive v2` event.
3. Prepare local config:

```bash
cp .env.local.example .env.local
cp references/config.example.yaml config.local.yaml
python3 -m pip install --user lark-oapi
```

4. Fill `config.local.yaml` with:
   - `feishu.app_id`
   - `feishu.app_secret`
   - `feishu.app_token`
   - `feishu.table_id` can be an existing table; the bot can also create per-keyword tables at runtime

5. Start the bot:

```bash
./scripts/start_bot_ws.sh
```

Then a user can message the bot directly in Feishu:

```text
Help me find AI product manager internships
```

The bot will:
- collect one round of constraints such as company, city, lookback window, and update cadence
- run the search/filter/extraction/sync pipeline
- return a structured job summary directly in chat
- attach the Feishu Bitable link for full browsing

Basic control commands:

```text
/help
/jobs
/rerun
/stop
```

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

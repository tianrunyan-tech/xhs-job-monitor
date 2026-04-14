# Operational Playbook

## Run cadence

- Schedule `run_search_sync.py` every 2 hours.
## Stop conditions

Stop the current run and alert the operator when the adapter classifies an error as:

- `auth_error`
- `captcha_required`
- `ip_blocked`
- `rate_limited`

## Retry guidance

- Do not blindly retry captcha or auth failures.
- Retry single-record Feishu or LLM failures on the next scheduled run.
- Keep Xiaohongshu note reads sequential to reduce risk.

## OpenClaw wiring

Recommended nodes:

1. schedule trigger
2. inject user-provided keywords into the generated config payload
3. `python scripts/run_search_sync.py --config ... --keyword "AI产品经理实习" --auto-table --limit 50 --json`
4. branch on `ok`
5. log or alert on `errors`
6. notify the user with the target Feishu table link and summary counts

## Optional Feishu bot wiring, long connection mode

Use this mode only when the Feishu bot itself is the user entrypoint or needs to stay online for follow-up updates. If the workflow is triggered elsewhere and only writes to Feishu Bitable, this bot layer is optional.

Install the official Feishu SDK if needed:

```bash
python3 -m pip install --user lark-oapi
```

In Feishu Open Platform, set event subscription to long connection mode, subscribe to the receive-message event, and grant bot message send plus bitable table/record read-write permissions.

Run:

```bash
MINIMAX_API_KEY="..." python scripts/bot_ws_client.py --config references/config.example.yaml --limit 50
```

Users can send either the `/job` command or a natural request:

```text
/job 找AI产品经理实习
帮我找AI产品经理实习岗位
```

The bot will:

- parse `AI产品经理实习` as the keyword
- create or reuse a table with that keyword as the table name
- collect one round of constraints before search
- run `run_search_sync.py --keyword "AI产品经理实习 <constraints>" --table-id <created table>`
- reply first when search starts, then send the table link after records are updated

For background launchd setup on this machine, use `references/com.xhs-job-monitor.bot.plist` as the deployment template.

## Optional Feishu bot wiring, HTTP callback fallback

Use this mode only for request-response bot callbacks. This script does not own a durable scheduler, so do not rely on it for recurring updates unless an external scheduler calls it.

Run the bot callback service:

```bash
MINIMAX_API_KEY="..." python scripts/bot_server.py --config references/config.example.yaml --port 8787 --limit 50
```

Expose the local port with your preferred tunnel or deployment gateway, then configure the Feishu app event callback URL to this service. Subscribe the app to message receive events and grant message send plus bitable table/record read-write permissions.

Users can send:

```text
/job 找AI产品经理实习
帮我找AI产品经理实习岗位
```

The bot will:

- parse `AI产品经理实习` as the keyword
- create or reuse a table with that keyword as the table name
- collect one round of constraints before search
- run `run_search_sync.py --keyword "AI产品经理实习 <constraints>" --table-id <created table>`
- reply first when search starts, then send the table link after records are updated

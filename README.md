# XHS Job Monitor

A Codex skill for monitoring Xiaohongshu recruiting posts, filtering noisy results, extracting structured job fields with an LLM, and syncing results to a Feishu Bitable.

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
- Searches Xiaohongshu notes by time window and reads note detail, OCR text, and first comments when available.
- Uses an LLM to classify whether a note is a real, concrete recruiting post.
- Extracts structured fields such as company, job title, location, responsibilities, requirements, contact info, publish time, and note URL.
- Filters traffic-style referral ads, agency-like posts, non-recruiting posts, and mismatched roles before writing records.
- Upserts records into Feishu Bitable by `note_id`, with newer and higher-match jobs prioritized.

## 安装

把这个仓库放到你的 agent 的 skill/command 目录下。

**Codex：**

```bash
mkdir -p ~/.codex/skills
cp -R xhs-job-monitor ~/.codex/skills/xhs-job-monitor
```

**其他 Agent：**

放到你的 agent 读取 skill/command 定义的目录下即可。

## 前置条件

- 准备一个可用的小红书数据源适配器。默认配置会调用名为 `xhs` 的本地命令行工具，但这个仓库不包含该工具的安装包
- 准备飞书开放平台应用，并配置多维表格读写权限
- 准备 LLM API Key，用于关键词扩写和招聘帖结构化提取
- 复制示例配置并填写本地凭据：

```bash
cp .env.local.example .env.local
cp references/config.example.yaml config.local.yaml
```

```bash
MINIMAX_API_KEY="your_api_key"
```

默认的小红书适配器通过 `references/config.example.yaml` 里的 `runtime.xhs_command` 配置：

```yaml
runtime:
  xhs_command: "xhs"
```

这个命令需要支持以下能力：

```bash
xhs status --json
xhs login --qrcode
xhs search "<关键词>" --sort latest --page 1 --type image --json
xhs read "<note_id>" --json
xhs comments "<note_id>" --json
```

如果你没有现成的 `xhs` CLI，需要先实现或接入一个兼容上述接口的数据源命令，再把 `runtime.xhs_command` 改成对应命令路径。

## 使用

在 Agent 中直接描述你想找的岗位：

```text
帮我找 AI产品运营实习 岗位
```

也可以补充筛选条件：

```text
只看字节、腾讯、阿里等知名科技大厂和初创公司，最近3天，只查找一次。
```

Agent 会先确认岗位和限制条件，再开始搜索、筛选、结构化提取，并把结果写入飞书多维表格。

如果你需要直接运行脚本，可以使用：

```bash
source .env.local
python3 scripts/run_search_sync.py \
  --config config.local.yaml \
  --keyword "<你的岗位关键词>" \
  --auto-table \
  --login-if-needed \
  --json
```

首次搜索默认在去重、过滤后最多写入 50 条。只有需要覆盖默认值时，再传 `--limit <数量>`。

## 支持的能力

| 能力 | Agent 怎么做 |
| ---- | ------------ |
| 约束收集 | 在搜索前询问公司、地点、岗位类型、时间范围、更新周期等偏好 |
| 关键词扩写 | 把用户输入的岗位扩写成更适合小红书搜索的关键词集合 |
| 小红书搜索 | 按关键词和时间窗口搜索招聘相关笔记 |
| 帖子读取 | 读取标题、正文、图片 OCR 文本和首条评论 |
| 招聘帖判定 | 用 LLM 过滤面经、求职广告、中介引流、泛化内推帖和岗位不匹配内容 |
| 信息结构化 | 提取公司、岗位、城市、职责、要求、联系方式、发布时间和原帖链接 |
| 飞书同步 | 按 `note_id` 去重并写入飞书多维表格 |
| 定时更新 | 按用户设置或默认周期继续搜索新的招聘帖 |

## License

MIT

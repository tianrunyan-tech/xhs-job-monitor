# XHS Job Monitor

中文 | [English](README.md)

一个 Codex 和 Claude Code skill: 用于自动化监控小红书招聘帖、实时提取目标岗位帖子，并将非结构化岗位信息提炼同步至飞书多维表格

## 适合谁？

正在寻找实习、校招机会的学生和社招机会的求职者

在常规的招聘软件与企业官网之外，小红书实际上隐藏着一座 **“求职金矿”**。作为一个高活跃度的社区，它具备传统招聘渠道无法比拟的优势：
- **触达一线的扁平链路**：这里有大量来自业务团队一线员工、离职实习生发出的“直招”或“找继任”贴。相比于传统 HR 漫长的简历漏斗，这里的链路极其扁平。
- **信息更透明、沟通更直接**：帖子往往真实还原团队氛围与工作日常，并附带业务线的直投邮箱，支持私信直接对话，省去了大量中间环节和信息损耗
- **信息源愈发丰富**：得益于触达目标人群更准、响应速度更快的优势，越来越多的用人团队习惯在小红书发布招聘需求

但小红书招聘信息存在碎片化、噪声多的问题：

- **时效性低**：需要求职者手动刷新，频繁打开小红书查看主页推送，极易错过优质岗位发布后的最佳投递窗口
- **搜索效率低**：不管是默认排序还是最新排序，搜索结果中总是混杂着大量过期旧帖、个人面经、培训广告和中介引流贴。在海量信息中筛选极其耗时。
- **提取成本高**：有效信息分散在标题、正文、图片 OCR、首条评论里，手动整理到表格很低效，邮箱投递后容易忘记投递的岗位信息，帖子也有被删去的风险

## 它能做什么？

目标是把 **搜索 -> 筛选 -> 结构化提取 -> 飞书多维表格同步** 的全链路自动化，生成一个时效性更高、信息更干净、更可投递的招聘信息看板。

- 将用户输入的目标岗位扩写成更适合小红书搜索的关键词集合，提高召回率。
- 按时间窗口搜索小红书笔记，并读取帖子详情、图片 OCR 文本和首条评论。
- 使用 LLM 判断帖子是否是真实、具体的招聘帖。
- 提取公司、岗位、城市、职责、要求、联系方式、发布时间、原帖链接等结构化字段。
- 在写入前过滤流量型内推广告、中介帖、非招聘帖和岗位不匹配内容。
- 按 `note_id` 去重并同步到飞书多维表格，优先保留发布时间更新、岗位匹配度更高的记录。

## 安装

把这个仓库放到你的 agent 的 skill/command 目录下。

**Codex：**

如果直接从 GitHub 安装：

```bash
mkdir -p ~/.codex/skills
git clone https://github.com/tianrunyan-tech/xhs-job-monitor.git ~/.codex/skills/xhs-job-monitor
```

如果你已经下载了这个仓库，并且当前就在仓库根目录：

```bash
mkdir -p ~/.codex/skills/xhs-job-monitor
cp -R SKILL.md README.md README_CN.md LICENSE .env.local.example references scripts tests ~/.codex/skills/xhs-job-monitor/
```

**Claude Code：**

如果直接从 GitHub 安装：

```bash
mkdir -p ~/.claude/skills
git clone https://github.com/tianrunyan-tech/xhs-job-monitor.git ~/.claude/skills/xhs-job-monitor
```

如果你已经下载了这个仓库，并且当前就在仓库根目录：

```bash
mkdir -p ~/.claude/skills/xhs-job-monitor
cp -R SKILL.md README.md README_CN.md LICENSE references scripts tests ~/.claude/skills/xhs-job-monitor/
```

`SKILL.md` 的 frontmatter 格式（`name`/`description`）和 Claude Code 的 skill 格式完全一致，不需要额外改动即可被识别。建议把凭据文件（`.env.local`、`config.local.yaml`）保留在你的工作项目目录下，而不是放进 `~/.claude/skills/`，运行时用 `--config` 指向该路径即可。

**其他 Agent：**

放到你的 agent 读取 skill/command 定义的目录下即可。

## 前置条件

- 安装并配置好 [Xhs CLI](https://github.com/jackwener/xiaohongshu-cli)
- 创建飞书开放平台应用，并配置多维表格读写权限
- 准备 LLM API Key，用于关键词扩写和招聘帖结构化提取
- 复制示例配置并填写本地凭据：

```bash
cp .env.local.example .env.local
cp references/config.example.yaml config.local.yaml
```

```bash
LLM_API_KEY="your_openai_compatible_api_key"
```

## 使用

在 Agent 中直接描述你想找的岗位：

```text
帮我找AI产品运营的实习岗位
```

也可以补充筛选条件：

```text
只看字节、腾讯、阿里等知名科技大厂和初创公司，最近3天。
```

Agent 会先确认岗位和限制条件，再开始搜索、筛选、结构化提取，并把结果写入飞书多维表格。

## 飞书 Bot 交互

如果你希望用户直接在飞书里和一个 bot 对话，可以使用项目内置的长连接 bot：

1. 在飞书开放平台创建企业自建应用，开启机器人能力和事件订阅。
2. 订阅 `接收消息 v2` 事件。
3. 准备本地配置：

```bash
cp .env.local.example .env.local
cp references/config.example.yaml config.local.yaml
python3 -m pip install --user lark-oapi
```

4. 在 `config.local.yaml` 中填写：
   - `feishu.app_id`
   - `feishu.app_secret`
   - `feishu.app_token`
   - `feishu.table_id` 可以先填一个已有表，bot 运行时也会按关键词自动建表

5. 启动 bot：

```bash
./scripts/start_bot_ws.sh
```

启动后，用户可以直接在飞书里给 bot 发消息：

```text
帮我找 AI产品经理实习
```

bot 会：
- 先追问公司、城市、时间窗口、更新周期等限制条件
- 自动执行搜索、筛选、结构化提取、写入飞书多维表格
- 在聊天窗口直接返回岗位摘要
- 附上完整结果表格链接，方便继续查看

还支持这些基础命令：

```text
/help
/jobs
/rerun
/stop
```

## 支持的能力

| 能力 | Agent 怎么做 |
| ---- | ------------ |
| 约束收集 | 在搜索前询问公司、地点、岗位类型、时间范围、更新周期等偏好 |
| 关键词扩写 | 把用户输入的岗位扩写成更适合小红书搜索的关键词集合 |
| 小红书搜索 | 按关键词和时间窗口搜索招聘相关笔记 |
| 帖子读取 | 读取标题、正文、图片 OCR 文本和首条评论 |
| 招聘帖判定 | 用 LLM 过滤面经、求职广告、中介引流、泛化内推帖和岗位不匹配内容 |
| 信息结构化 | 提取公司、岗位、城市、职责、要求、联系方式、发布时间和原帖链接 |
| 飞书同步 | 去重并写入飞书多维表格 |
| 定时更新 | 按用户设置或默认周期继续搜索新的招聘帖 |

## License

MIT

# XHS Job Monitor

中文 | [English](README.md)

XHS Job Monitor 是一个 Codex skill，用于监控小红书招聘帖、过滤噪声内容、用 LLM 提取结构化岗位信息，并同步到飞书多维表格。

## 适合谁？

适合正在通过小红书寻找实习、校招机会的学生和求职者。

小红书是一个有价值的招聘信息源，因为很多招聘帖来自团队成员。对实习岗位，尤其是实习继任岗位来说，帖子里经常会包含直投邮箱、内推路径或私信沟通方式。相比标准招聘网站，这条链路更短，也可能不需要经过完整的 HR 筛选流程。

但小红书招聘信息也很碎片化、噪声多：

- **时效性低**：手动刷新频率低，容易错过岗位发布后的黄金 1 小时。
- **搜索效率低**：默认排序或 latest 排序会混入旧帖、广告、流量型内推帖、中介帖和岗位不匹配内容。
- **提取成本高**：有效信息分散在标题、正文、图片 OCR、首条评论里，手动整理到表格很低效。

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

```bash
mkdir -p ~/.codex/skills
git clone https://github.com/tianrunyan-tech/xhs-job-monitor.git ~/.codex/skills/xhs-job-monitor
```

如果你已经下载了这个仓库，并且当前就在仓库根目录：

```bash
mkdir -p ~/.codex/skills/xhs-job-monitor
cp -R SKILL.md README.md README_CN.md LICENSE .env.local.example references scripts tests ~/.codex/skills/xhs-job-monitor/
```

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

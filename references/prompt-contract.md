# Prompt Contract

The extraction adapter must request strict JSON only. The output schema is:

```json
{
  "is_job_post": true,
  "judgment_reason": "该帖详细列出了腾讯CSIG的AI产品经理工作内容及投递邮箱，为真实招聘",
  "data": {
    "company": "腾讯CSIG",
    "job_title": "AI产品经理实习生",
    "location": "北京",
    "position_info": "1. 负责需求调研\n2. 完成原型设计",
    "requirements": "1. 本科及以上学历\n2. 每周出勤4天",
    "contact_info": "hr@example.com"
  }
}
```

For non-job posts:

```json
{
  "is_job_post": false,
  "judgment_reason": "该帖核心内容为面试经历分享，属于面经分享",
  "data": null
}
```

Rules:

- Return valid JSON only.
- Use the note title, body, image OCR text, and first comment as extraction sources.
- Give image OCR text high weight because many JDs are embedded in images.
- Treat first comment as an important source for delivery email, referral code, WeChat ID, or private-message delivery instructions.
- Classify interview experiences, training or agency marketing, personal job-seeking posts, and generic ads without a concrete JD as non-job posts.
- Classify traffic-oriented referral or intermediary recruiting ads as non-job posts when they only list many broad role categories and lack a concrete team, role responsibility, JD, and business context, even if they mention major companies, referrals, internships, or successor interns.
- If `company`, `location`, or `contact_info` is unavailable, return `null`.
- `job_title` must be a clean role name, without company, department, verbs, or modifiers.
- `position_info` records role information and must be summarized as numbered lines.
- `requirements` records role requirements and must be summarized as numbered lines ordered by priority.
- If `is_job_post` is `false`, return `data: null`; the sync flow discards the note and does not upsert it to Feishu.
- Never include Markdown code fences in the model output.

Compatibility notes:

- The Feishu table still uses the historical field name `requirement`; the adapter maps model output `data.requirements` to `JobExtraction.requirement`.
- The adapter also accepts the previous flat schema and optional `confidence` field for backward compatibility.

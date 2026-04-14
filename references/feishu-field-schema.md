# Feishu Bitable Field Contract

Create only these fields in the target table. The skill upserts by `note_id`.

Required fields:

- `note_id`
- `company`
- `job_title`
- `position_info`
- `requirement`
- `location`
- `publish_time`
- `contact_info`
- `note_url`

Extraction semantics:

- `company`: extract from note body, image OCR text, and the first comment; use `None` if unavailable.
- `job_title`: extract from note body, image OCR text, and the first comment.
- `position_info`: summarize the role information from note body, image OCR text, and the first comment.
- `requirement`: summarize the role requirements from note body, image OCR text, and the first comment.
- `location`: extract from note body, image OCR text, and the first comment; use `None` if unavailable.
- `publish_time`: use the note publish or latest update time from Xiaohongshu.
- `contact_info`: extract the resume delivery email address from note body, image OCR text, and the first comment.
- `note_url`: store the Xiaohongshu note URL.

Recommended table settings:

- Keep `note_id` unique in business logic even if the table does not enforce a unique index.
- Keep every field name exactly as written above; Feishu field names are case-sensitive.

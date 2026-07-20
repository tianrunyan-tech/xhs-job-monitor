import json
import os
import re
import socket
import threading
import time
from typing import Any, Dict, Optional, Tuple
from urllib import request

try:
    from schemas import JobExtraction, NoteDetail
except ModuleNotFoundError:
    from scripts.schemas import JobExtraction, NoteDetail


class LlmExtractError(Exception):
    pass

EXTRACTION_PROMPT = """
# Role
你是一个资深的 HR 专家与 AI 数据结构化工程师。你的任务是先判断一条小红书帖子是否是一个真实、具体的招聘/岗位帖；如果是，再提取高纯度的结构化招聘数据。

# Input Data
你将接收到 NoteDetail JSON，其中包含以下信息：
1. 帖子标题：title
2. 帖子正文：raw_text
3. 评论区首条评论：first_comment。用户常在首评补充投递邮箱或状态。

# Rules
第一步：判断是否为真实招聘帖。

【真实招聘帖】的典型特征：
1. 明确的具体岗位：有清晰、单一或高度聚焦的岗位名称，而非宽泛的职能大类
2. 完整的 JD 结构：包含具体的“工作内容/职责”以及硬性的“任职要求”
3. 明确的雇主信息：有明确的公司名称或业务线提及，如“腾讯CSIG”、“抖音电商”、“淘宝天猫”

【非招聘帖】的典型特征，若命中以下任意一点，请判定为 false：
- 面经/进度分享：属于个人经历记录，常见特征词：“一面”、“二面”、“挂了”、“被鸽”、“求职记录”、“秋招/春招总结”、“面试经历”等。
- 辅导/中介/卖资料：属于营销引流或培训，常见特征词：“求职陪跑”、“付费带教”、“大厂直通车”、“整理好的资料”、“戳我领取”等。
- 流量型内推/中介型招聘广告：虽然出现“内推”、“实习继任”、“急招”、“大厂实习”等招聘词，但没有具体单一岗位，只泛泛罗列多个岗位类别或方向，例如“内容运营、用户增长、前端、后端、HR助理、行政助理”等；没有团队名称、明确岗位职责、具体 JD 或实际业务上下文。此类必须判定为 false。
- 个人求职：属于个人找工作，常见特征词：“求捞”、“帮看简历”、“听劝”。
- 泛泛的广告/水帖：没有明确的单一/具体岗位 JD，只有企业宣传。

第二步：如果第一步判定为真实招聘帖，再提取以下字段，并严格遵循清洗规则：
1. job_title：必须是绝对纯净的岗位名词，如“AI产品经理实习生”、“大模型算法工程师”。绝对禁止包含公司名称、部门名称、动词或修饰语，如“腾讯招AI产品”、“急招产品经理”、“AI产品实习生（留用机会大）”。
2. company：提取真实雇主的名称。如果标题或正文中提到了具体的业务线，如“淘天”、“腾讯CSIG”，请合并输出，例如“淘宝天猫”、“腾讯CSIG”、“抖音电商”。如果是未知公司，输出 null。
3. position_info：必须对大段文字进行语义理解和归纳。强制拆分成带数字序号的条目，每一点换行，格式如“1. 负责XXX产品的调研...\n2. 独立完成XXX的原型设计...”。
4. requirements：必须对大段要求进行提炼，强制分点输出并按优先级排序，格式如“1. 25届或26届本科及以上学历...\n2. 熟练使用Axure、Figma等工具...\n3. 每周出勤4天，实习3个月以上...”。
5. contact_info：优先从首条评论中寻找邮箱地址、内推码、微信号或“私信投递”等字眼。

# Output
请务必严格按照以下 JSON 格式输出结果，不要输出任何额外的解释性文字。不要输出 Markdown 代码块。未知值使用 null。JSON 中不要包含注释。
{
  "is_job_post": true,
  "confidence": 0.0,
  "judgment_reason": "简短理由",
  "data": {
    "company": "提取的公司名称",
    "job_title": "纯净的岗位名称",
    "location": "工作城市，未提及则为null",
    "position_info": "1. xxx\\n2. xxx\\n3. xxx",
    "requirements": "1. xxx\\n2. xxx\\n3. xxx",
    "contact_info": "提取到的投递方式"
  }
}
如果 is_job_post 为 false，请输出 "data": null。
"""

def _default_payload(note: NoteDetail) -> JobExtraction:
    text = f"{note.title}\n{note.raw_text}\n{note.first_comment}".lower()
    hiring_signal = any(word in text for word in ["招聘", "招募", "实习", "岗位", "hc", "投递"])
    concrete_signal = any(word in text for word in ["岗位职责", "工作职责", "职位描述", "任职要求", "工作内容", "你将负责", "base", "团队"])
    hint = hiring_signal and concrete_signal
    title = note.title or "招聘信息"
    return JobExtraction(
        is_job_post=hint,
        confidence=0.55 if hint else 0.2,
        judgment_reason="fallback_heuristic",
        job_title=title if hint else None,
        position_info=note.raw_text[:200] if note.raw_text else None,
        requirement=note.raw_text[:200] if note.raw_text else None,
    )


class OpenAICompatibleExtractor:
    def __init__(self, llm_config: Dict[str, Any]):
        self.config = llm_config
        self.last_trace: Dict[str, Any] = {}

    def _api_key(self) -> str:
        literal_key = self.config.get("api_key")
        if literal_key:
            return literal_key
        env_name = self.config.get("api_key_env", "OPENAI_API_KEY")
        if isinstance(env_name, str) and env_name.startswith("sk-"):
            return env_name
        api_key = os.getenv(env_name, "")
        if not api_key:
            raise LlmExtractError(f"Missing LLM API key in environment variable {env_name}")
        return api_key

    def extract(self, note: NoteDetail) -> JobExtraction:
        extraction, trace = self.extract_with_trace(note)
        self.last_trace = trace
        return extraction

    def extract_with_trace(self, note: NoteDetail) -> Tuple[JobExtraction, Dict[str, Any]]:
        trace: Dict[str, Any] = {}
        timings: Dict[str, int] = {}
        if self.config.get("provider") == "mock":
            extraction = _default_payload(note)
            trace["classification"] = _serialize_job_extraction(extraction)
            trace["extraction"] = _serialize_job_extraction(extraction)
            trace["final"] = _serialize_job_extraction(extraction)
            trace["timings"] = timings
            return extraction, trace
        extract_started_at = time.perf_counter()
        payload = self._chat_completion(
            EXTRACTION_PROMPT,
            {
                "title": note.title,
                "raw_text": note.raw_text,
                "first_comment": note.first_comment,
            },
        )
        extraction = parse_llm_response(payload, note)
        total_elapsed_ms = int((time.perf_counter() - extract_started_at) * 1000)
        timings["classify_elapsed_ms"] = total_elapsed_ms
        timings["extract_elapsed_ms"] = total_elapsed_ms
        trace["classification"] = _serialize_job_extraction(extraction)
        trace["extraction"] = _serialize_job_extraction(extraction)
        trace["final"] = _serialize_job_extraction(extraction)
        trace["timings"] = timings
        return extraction, trace

    def _chat_completion(self, system_prompt: str, user_payload: Dict[str, Any]) -> Dict[str, Any]:
        body = {
            "model": self.config["model"],
            "temperature": self.config.get("temperature", 0),
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
            ],
        }
        url = self.config.get("api_base", "https://api.openai.com/v1").rstrip("/") + "/chat/completions"
        req = request.Request(
            url,
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._api_key()}",
            },
            method="POST",
        )
        timeout_seconds = int(self.config.get("timeout_seconds", 60))
        max_attempts = int(self.config.get("max_retries", 1)) + 1
        last_exc = None
        for attempt in range(max_attempts):
            try:
                payload = self._request_with_deadline(req, timeout_seconds)
                break
            except Exception as exc:
                last_exc = exc
                if attempt >= max_attempts - 1 or not _is_retryable_error(exc):
                    raise LlmExtractError(str(exc)) from exc
                time.sleep(1.0 + attempt)
        if last_exc is not None and "payload" not in locals():
            raise LlmExtractError(str(last_exc)) from last_exc
        return payload

    def _request_with_deadline(self, req: request.Request, timeout_seconds: int) -> Dict[str, Any]:
        result: Dict[str, Any] = {}
        error: Dict[str, Exception] = {}

        def worker() -> None:
            try:
                with request.urlopen(req, timeout=timeout_seconds) as response:
                    result["payload"] = json.loads(response.read().decode("utf-8"))
            except Exception as exc:
                error["exc"] = exc

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        # Give the underlying socket timeout some headroom but enforce a hard deadline.
        thread.join(timeout_seconds + 5)
        if thread.is_alive():
            raise LlmExtractError(f"LLM request exceeded hard deadline of {timeout_seconds + 5} seconds")
        if "exc" in error:
            raise error["exc"]
        return result["payload"]


def parse_llm_response(payload: Dict[str, Any], note: Optional[NoteDetail] = None) -> JobExtraction:
    try:
        content = payload["choices"][0]["message"]["content"]
    except Exception as exc:
        raise LlmExtractError(f"Invalid LLM response payload shape: {exc}; top-level keys={list(payload.keys())}") from exc
    try:
        data = json.loads(content)
    except Exception as exc:
        extracted = _extract_json_object(content) if isinstance(content, str) else None
        if extracted:
            try:
                data = json.loads(extracted)
            except Exception:
                data = None
        else:
            data = None
        if data is None:
            preview = content[:500] if isinstance(content, str) else repr(content)
            if note is not None:
                return JobExtraction.empty_failure()
            raise LlmExtractError(f"LLM response content is not valid JSON: {exc}; content_preview={preview!r}") from exc
    try:
        normalized = _normalize_llm_data(data)
        return JobExtraction(
            is_job_post=normalized["is_job_post"],
            confidence=normalized["confidence"],
            judgment_reason=normalized.get("judgment_reason"),
            company=normalized.get("company"),
            job_title=normalized.get("job_title"),
            position_info=normalized.get("position_info"),
            location=normalized.get("location"),
            requirement=normalized.get("requirement"),
            contact_info=normalized.get("contact_info"),
        )
    except Exception as exc:
        if note is not None:
            return JobExtraction.empty_failure()
        raise LlmExtractError(f"Invalid extraction schema: {exc}") from exc


def _extract_json_object(text: str) -> Optional[str]:
    cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    return cleaned[start : end + 1]
def _is_retryable_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return isinstance(exc, socket.timeout) or "timed out" in text or "tempor" in text or "reset by peer" in text


def _normalize_llm_data(data: Dict[str, Any]) -> Dict[str, Any]:
    is_job_post = bool(data["is_job_post"])
    if not is_job_post:
        return {
            "is_job_post": False,
            "confidence": float(data.get("confidence", 0.1)),
            "judgment_reason": data.get("judgment_reason"),
            "company": None,
            "job_title": None,
            "position_info": None,
            "location": None,
            "requirement": None,
            "contact_info": None,
        }
    source = data.get("data") if isinstance(data.get("data"), dict) else data
    return {
        "is_job_post": True,
        "confidence": float(data.get("confidence", 0.9)),
        "judgment_reason": data.get("judgment_reason"),
        "company": source.get("company"),
        "job_title": source.get("job_title"),
        "position_info": source.get("position_info"),
        "location": source.get("location"),
        "requirement": source.get("requirement", source.get("requirements")),
        "contact_info": source.get("contact_info"),
    }
def _serialize_job_extraction(extraction: JobExtraction) -> Dict[str, Any]:
    return {
        "is_job_post": extraction.is_job_post,
        "confidence": extraction.confidence,
        "judgment_reason": extraction.judgment_reason,
        "company": extraction.company,
        "job_title": extraction.job_title,
        "location": extraction.location,
        "position_info": extraction.position_info,
        "requirement": extraction.requirement,
        "contact_info": extraction.contact_info,
    }

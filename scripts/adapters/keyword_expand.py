import json
import os
import re
from typing import Any, Dict, List
from urllib import request

try:
    from bot_logic import expand_search_keywords
except ModuleNotFoundError:
    from scripts.bot_logic import expand_search_keywords


class KeywordExpandError(Exception):
    pass


SYSTEM_PROMPT = """你是一个熟悉小红书求职招聘语境的搜索关键词扩写专家。
你的任务是把用户输入的目标岗位扩写成更适合小红书搜索的关键词集合，以提高相关招聘帖召回率。

扩写时优先考虑：
1. 岗位名称的常见近义表达。
2. 小红书求职场景中的高频说法。
3. 与实习、校招、继任、日常实习相关的后缀补充。
4. 更细分但仍与原岗位高度相关的岗位方向词。

严格要求：
- 扩写结果必须与原岗位高度相关，不要扩写出无关岗位
- 如果是实习岗位的搜索，输出必须要有加上“继任”的后缀
- 不要跨岗位族扩写。例如算法岗位不要扩写为产品岗位，产品岗位不要扩写为运营岗位。
- 优先选择能提升小红书招聘帖召回率的短关键词。
- 保留用户原始关键词作为第一个结果。
- 输出不要超过5个关键词。
- 只输出 JSON，不要 Markdown，不要解释。

输出格式：
{"keywords": ["原始关键词", "扩写关键词1", "扩写关键词2"]}"""


class OpenAICompatibleKeywordExpander:
    def __init__(self, llm_config: Dict[str, Any]):
        self.config = llm_config

    def _api_key(self) -> str:
        literal_key = self.config.get("api_key")
        if literal_key:
            return literal_key
        env_name = self.config.get("api_key_env", "OPENAI_API_KEY")
        if isinstance(env_name, str) and env_name.startswith("sk-"):
            return env_name
        api_key = os.getenv(env_name, "")
        if not api_key:
            raise KeywordExpandError(f"Missing LLM API key in environment variable {env_name}")
        return api_key

    def expand(self, keyword: str) -> List[str]:
        if self.config.get("provider") == "mock":
            return expand_search_keywords(keyword)
        body = {
            "model": self.config["model"],
            "temperature": self.config.get("temperature", 0),
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps({"keyword": keyword}, ensure_ascii=False)},
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
        try:
            with request.urlopen(req, timeout=int(self.config.get("timeout_seconds", 20))) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            raise KeywordExpandError(str(exc)) from exc
        return parse_keyword_expand_response(payload, keyword)


def parse_keyword_expand_response(payload: Dict[str, Any], original_keyword: str) -> List[str]:
    try:
        content = payload["choices"][0]["message"]["content"]
    except Exception as exc:
        raise KeywordExpandError(f"Invalid LLM response payload shape: {exc}; top-level keys={list(payload.keys())}") from exc
    try:
        data = json.loads(content)
    except Exception as exc:
        extracted = _extract_json_object(content) if isinstance(content, str) else None
        if not extracted:
            raise KeywordExpandError(f"LLM response content is not valid JSON: {exc}") from exc
        data = json.loads(extracted)
    if not isinstance(data, dict) or not isinstance(data.get("keywords"), list):
        raise KeywordExpandError("LLM keyword expansion must return a JSON object with a keywords list")
    return normalize_keywords(data["keywords"], original_keyword)


def normalize_keywords(values: List[Any], original_keyword: str, max_keywords: int = 10) -> List[str]:
    keywords: List[str] = []

    def add(value: Any) -> None:
        text = re.sub(r"\s+", "", str(value or "")).strip()
        if text and text not in keywords and len(keywords) < max_keywords:
            keywords.append(text)

    add(original_keyword)
    for value in values:
        add(value)
    return keywords


def _extract_json_object(text: str) -> str:
    cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return ""
    return cleaned[start : end + 1]

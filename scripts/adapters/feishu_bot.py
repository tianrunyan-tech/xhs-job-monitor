import json
from typing import Any, Dict, Optional
from urllib import parse, request
from urllib.error import HTTPError


class FeishuBotError(Exception):
    pass


class FeishuBotAdapter:
    def __init__(self, app_id: str, app_secret: str):
        self.app_id = app_id
        self.app_secret = app_secret
        self.base_url = "https://open.feishu.cn/open-apis"
        self._tenant_access_token = ""

    def _request(self, method: str, path: str, payload: Dict[str, Any], query: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        url = self.base_url + path
        if query:
            url += "?" + parse.urlencode(query)
        headers = {"Content-Type": "application/json"}
        if path != "/auth/v3/tenant_access_token/internal":
            headers["Authorization"] = f"Bearer {self.tenant_access_token()}"
        req = request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers, method=method)
        try:
            with request.urlopen(req, timeout=30) as response:
                body = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise FeishuBotError(f"HTTP Error {exc.code}: {detail}") from exc
        except Exception as exc:
            raise FeishuBotError(str(exc)) from exc
        if body.get("code", 0) != 0:
            raise FeishuBotError(body.get("msg", "Feishu bot API error"))
        if path == "/auth/v3/tenant_access_token/internal":
            return body
        return body.get("data", {})

    def tenant_access_token(self) -> str:
        if self._tenant_access_token:
            return self._tenant_access_token
        data = self._request(
            "POST",
            "/auth/v3/tenant_access_token/internal",
            {"app_id": self.app_id, "app_secret": self.app_secret},
        )
        token = data.get("tenant_access_token")
        if not token:
            raise FeishuBotError("Feishu auth response did not include tenant_access_token")
        self._tenant_access_token = token
        return token

    def send_text(self, chat_id: str, text: str) -> None:
        self._request(
            "POST",
            "/im/v1/messages",
            {
                "receive_id": chat_id,
                "msg_type": "text",
                "content": json.dumps({"text": text}, ensure_ascii=False),
            },
            query={"receive_id_type": "chat_id"},
        )

    def reply_text(self, message_id: str, text: str) -> None:
        self._request(
            "POST",
            f"/im/v1/messages/{message_id}/reply",
            {
                "msg_type": "text",
                "content": json.dumps({"text": text}, ensure_ascii=False),
            },
        )

    @staticmethod
    def _card_content(markdown_text: str) -> str:
        return json.dumps(
            {
                "config": {"wide_screen_mode": True},
                "elements": [
                    {"tag": "div", "text": {"tag": "lark_md", "content": markdown_text}}
                ],
            },
            ensure_ascii=False,
        )

    def send_card(self, chat_id: str, markdown_text: str) -> None:
        self._request(
            "POST",
            "/im/v1/messages",
            {
                "receive_id": chat_id,
                "msg_type": "interactive",
                "content": self._card_content(markdown_text),
            },
            query={"receive_id_type": "chat_id"},
        )

    def reply_card(self, message_id: str, markdown_text: str) -> None:
        self._request(
            "POST",
            f"/im/v1/messages/{message_id}/reply",
            {
                "msg_type": "interactive",
                "content": self._card_content(markdown_text),
            },
        )

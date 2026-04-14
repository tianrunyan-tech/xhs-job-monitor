import json
from typing import Any, Dict, List, Optional
from urllib.error import HTTPError
from urllib import parse, request


class FeishuError(Exception):
    pass


class FeishuBitableAdapter:
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.base_url = "https://open.feishu.cn/open-apis"
        self._tenant_access_token: Optional[str] = None

    def _request(self, method: str, path: str, payload: Optional[Dict[str, Any]] = None, query: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        url = self.base_url + path
        if query:
            url += "?" + parse.urlencode(query)
        headers = {"Content-Type": "application/json"}
        if path != "/auth/v3/tenant_access_token/internal":
            headers["Authorization"] = f"Bearer {self.tenant_access_token()}"
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        req = request.Request(url, data=data, headers=headers, method=method)
        try:
            with request.urlopen(req, timeout=60) as response:
                body = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise FeishuError(f"HTTP Error {exc.code}: {body}") from exc
        except Exception as exc:
            raise FeishuError(str(exc)) from exc
        if body.get("code", 0) != 0:
            message = body.get("msg", "Feishu API error")
            if body.get("code") == 99991672:
                message += " Ensure the app has bitable/base scopes approved, the app version is published, and tenant authorization is refreshed."
            raise FeishuError(message)
        if path == "/auth/v3/tenant_access_token/internal":
            return body
        return body.get("data", {})

    def tenant_access_token(self) -> str:
        if self._tenant_access_token:
            return self._tenant_access_token
        data = self._request(
            "POST",
            "/auth/v3/tenant_access_token/internal",
            payload={"app_id": self.config["app_id"], "app_secret": self.config["app_secret"]},
        )
        token = data.get("tenant_access_token")
        if not token:
            raise FeishuError("Feishu auth response did not include tenant_access_token")
        self._tenant_access_token = token
        return self._tenant_access_token

    def list_records(self, filter_expr: Optional[str] = None) -> List[Dict[str, Any]]:
        path = f"/bitable/v1/apps/{self.config['app_token']}/tables/{self.config['table_id']}/records"
        query = {}
        if filter_expr:
            query["filter"] = filter_expr
        data = self._request("GET", path, query=query)
        return data.get("items", [])

    def list_tables(self) -> List[Dict[str, Any]]:
        path = f"/bitable/v1/apps/{self.config['app_token']}/tables"
        data = self._request("GET", path)
        return data.get("items", [])

    def find_table_by_name(self, table_name: str) -> Optional[Dict[str, Any]]:
        for table in self.list_tables():
            if table.get("name") == table_name or table.get("table_name") == table_name:
                return table
        return None

    def create_table(self, table_name: str, fields: List[Dict[str, Any]]) -> Dict[str, Any]:
        path = f"/bitable/v1/apps/{self.config['app_token']}/tables"
        payload = {
            "table": {
                "name": table_name,
                "default_view_name": "默认视图",
                "fields": fields,
            }
        }
        return self._request("POST", path, payload=payload)

    def ensure_table(self, table_name: str, fields: List[Dict[str, Any]]) -> str:
        existing = self.find_table_by_name(table_name)
        if existing:
            table_id = existing.get("table_id")
            if table_id:
                return table_id
        created = self.create_table(table_name, fields)
        table = created.get("table") if isinstance(created.get("table"), dict) else created
        table_id = table.get("table_id") if isinstance(table, dict) else None
        if not table_id:
            raise FeishuError(f"Feishu create table response did not include table_id: {created}")
        return table_id

    def find_record_by_note_id(self, note_id: str) -> Optional[Dict[str, Any]]:
        records = self.list_records(f'CurrentValue.[note_id] = "{note_id}"')
        return records[0] if records else None

    def create_record(self, fields: Dict[str, Any]) -> Dict[str, Any]:
        path = f"/bitable/v1/apps/{self.config['app_token']}/tables/{self.config['table_id']}/records"
        return self._request("POST", path, payload={"fields": fields})

    def update_record(self, record_id: str, fields: Dict[str, Any]) -> Dict[str, Any]:
        path = f"/bitable/v1/apps/{self.config['app_token']}/tables/{self.config['table_id']}/records/{record_id}"
        return self._request("PUT", path, payload={"fields": fields})

    def delete_record(self, record_id: str) -> Dict[str, Any]:
        path = f"/bitable/v1/apps/{self.config['app_token']}/tables/{self.config['table_id']}/records/{record_id}"
        return self._request("DELETE", path)

    def upsert_by_note_id(self, note_id: str, fields: Dict[str, Any]) -> str:
        existing = self.find_record_by_note_id(note_id)
        if existing:
            self.update_record(existing["record_id"], fields)
            return "updated"
        self.create_record(fields)
        return "created"

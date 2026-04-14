from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Tuple


class ConfigError(Exception):
    pass


@dataclass
class LoadedConfig:
    raw: Dict[str, Any]

    @property
    def keywords(self) -> List[str]:
        return self.raw["keywords"]


def _parse_scalar(token: str) -> Any:
    token = token.strip()
    if token == "":
        return ""
    if token in {"null", "Null", "NULL", "~"}:
        return None
    if token in {"true", "True"}:
        return True
    if token in {"false", "False"}:
        return False
    if (token.startswith('"') and token.endswith('"')) or (token.startswith("'") and token.endswith("'")):
        return token[1:-1]
    if token.lstrip("-").isdigit():
        return int(token)
    try:
        return float(token)
    except ValueError:
        return token


def _strip_comment(line: str) -> str:
    in_quote = False
    quote_char = ""
    result = []
    for char in line:
        if char in {"'", '"'}:
            if not in_quote:
                in_quote = True
                quote_char = char
            elif quote_char == char:
                in_quote = False
        if char == "#" and not in_quote:
            break
        result.append(char)
    return "".join(result).rstrip()


def _next_non_empty(lines: List[Tuple[int, str]], index: int):
    for idx in range(index + 1, len(lines)):
        indent, text = lines[idx]
        if text.strip():
            return indent, text.strip()
    return None


def _parse_block(lines: List[Tuple[int, str]], start: int, indent: int):
    data: Dict[str, Any] = {}
    items = []
    mode = None
    index = start
    while index < len(lines):
        line_indent, text = lines[index]
        if not text.strip():
            index += 1
            continue
        if line_indent < indent:
            break
        if line_indent > indent:
            raise ConfigError(f"Unexpected indentation near line: {text}")
        stripped = text.strip()
        if stripped.startswith("- "):
            if mode == "dict":
                raise ConfigError("Cannot mix mapping and list items at the same indentation level")
            mode = "list"
            value_text = stripped[2:].strip()
            if value_text == "":
                next_line = _next_non_empty(lines, index)
                if next_line is None or next_line[0] <= indent:
                    items.append(None)
                    index += 1
                    continue
                value, index = _parse_block(lines, index + 1, next_line[0])
                items.append(value)
                continue
            items.append(_parse_scalar(value_text))
            index += 1
            continue
        if ":" not in stripped:
            raise ConfigError(f"Invalid config line: {stripped}")
        if mode == "list":
            raise ConfigError("Cannot mix list and mapping items at the same indentation level")
        mode = "dict"
        key, value_text = stripped.split(":", 1)
        key = key.strip()
        value_text = value_text.strip()
        if value_text == "":
            next_line = _next_non_empty(lines, index)
            if next_line is None or next_line[0] <= indent:
                data[key] = {}
                index += 1
                continue
            value, index = _parse_block(lines, index + 1, next_line[0])
            data[key] = value
            continue
        data[key] = _parse_scalar(value_text)
        index += 1
    return (items if mode == "list" else data), index


def parse_simple_yaml(text: str) -> Dict[str, Any]:
    lines = []
    for raw_line in text.splitlines():
        clean = _strip_comment(raw_line)
        if not clean.strip():
            continue
        indent = len(clean) - len(clean.lstrip(" "))
        lines.append((indent, clean))
    if not lines:
        return {}
    parsed, index = _parse_block(lines, 0, lines[0][0])
    if index != len(lines):
        raise ConfigError("Failed to consume the full config")
    if not isinstance(parsed, dict):
        raise ConfigError("Top-level config must be a mapping")
    return parsed


def _require(mapping: Dict[str, Any], key: str, expected_type, path: str):
    if key not in mapping:
        raise ConfigError(f"Missing required config key: {path}{key}")
    value = mapping[key]
    if not isinstance(value, expected_type):
        raise ConfigError(f"Config key {path}{key} must be {expected_type}, got {type(value)}")
    return value


def validate_config(data: Dict[str, Any]) -> LoadedConfig:
    keywords = _require(data, "keywords", list, "")
    if not keywords or not all(isinstance(item, str) and item.strip() for item in keywords):
        raise ConfigError("keywords must be a non-empty string list")
    search = _require(data, "search", dict, "")
    llm = _require(data, "llm", dict, "")
    feishu = _require(data, "feishu", dict, "")
    runtime = _require(data, "runtime", dict, "")

    _require(search, "sort", str, "search.")
    _require(search, "max_pages", int, "search.")
    _require(search, "note_type", str, "search.")
    _require(search, "lookback_hours", int, "search.")

    _require(llm, "provider", str, "llm.")
    _require(llm, "model", str, "llm.")
    _require(llm, "temperature", (int, float), "llm.")
    if "timeout_seconds" in llm and not isinstance(llm["timeout_seconds"], int):
        raise ConfigError("Config key llm.timeout_seconds must be int")

    _require(feishu, "app_id", str, "feishu.")
    _require(feishu, "app_secret", str, "feishu.")
    _require(feishu, "app_token", str, "feishu.")
    _require(feishu, "table_id", str, "feishu.")

    _require(runtime, "output_format", str, "runtime.")
    _require(runtime, "cache_dir", str, "runtime.")
    _require(runtime, "xhs_command", str, "runtime.")

    return LoadedConfig(data)


def load_config(path: str) -> LoadedConfig:
    data = parse_simple_yaml(Path(path).read_text(encoding="utf-8"))
    return validate_config(data)

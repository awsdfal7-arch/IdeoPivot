from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any

import requests


@dataclass(frozen=True)
class LlmConfig:
    base_url: str
    api_key: str
    model: str
    timeout_s: float = 60.0
    max_retries: int = 2
    retry_backoff_s: float = 1.0


class LlmClient:
    def __init__(self, config: LlmConfig) -> None:
        self._config = config
        self._session = requests.Session()

    def chat_json(self, *, system: str, user: str) -> Any:
        content = self.chat_text(system=system, user=user)
        try:
            return json.loads(content)
        except Exception:
            extracted = _extract_json(content)
            return json.loads(extracted)

    def chat_text(self, *, system: str, user: str) -> str:
        data = self._post_chat(system=system, user=user)
        return data["choices"][0]["message"]["content"]

    def _post_chat(self, *, system: str, user: str) -> Any:
        url = _build_chat_completions_url(self._config.base_url)
        headers = {"Authorization": f"Bearer {self._config.api_key}"}
        temperature = _pick_temperature(self._config.model)
        payload = {
            "model": self._config.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
            "stream": False,
        }

        last_err: Exception | None = None
        attempts = max(1, int(self._config.max_retries) + 1)
        for i in range(attempts):
            try:
                resp = self._session.post(
                    url,
                    headers=headers,
                    json=payload,
                    timeout=self._config.timeout_s,
                )
                resp.raise_for_status()
                return resp.json()
            except requests.exceptions.Timeout as e:
                last_err = e
            except requests.exceptions.ConnectionError as e:
                last_err = e
            except requests.exceptions.HTTPError as e:
                last_err = e
                status = getattr(e.response, "status_code", None)
                body = ""
                try:
                    body = (e.response.text or "").strip() if e.response is not None else ""
                except Exception:
                    body = ""
                if status is not None and status < 500:
                    if body:
                        raise RuntimeError(f"HTTP {status}：{body}") from e
                    raise

            if i < attempts - 1:
                time.sleep(self._config.retry_backoff_s * (2**i))

        assert last_err is not None
        raise RuntimeError(f"请求失败：{last_err}") from last_err


def _extract_json(text: str) -> str:
    s = text.strip()
    if not s:
        return s

    starts = []
    for i, ch in enumerate(s):
        if ch in "[{":
            starts.append(i)
            break
    if not starts:
        return s

    start = starts[0]
    stack: list[str] = []
    for i in range(start, len(s)):
        ch = s[i]
        if ch in "[{":
            stack.append(ch)
        elif ch == "]":
            if stack and stack[-1] == "[":
                stack.pop()
                if not stack:
                    return s[start : i + 1]
        elif ch == "}":
            if stack and stack[-1] == "{":
                stack.pop()
                if not stack:
                    return s[start : i + 1]
    return s[start:]


def _build_chat_completions_url(base_url: str) -> str:
    base = (base_url or "").strip().rstrip("/")
    if base.endswith("/chat/completions"):
        return base
    if base.endswith("/v1"):
        return base + "/chat/completions"
    return base + "/v1/chat/completions"


def _pick_temperature(model: str) -> float:
    m = (model or "").strip().lower()
    if m.startswith("kimi-k2.6") or m.startswith("kimi-k2.5"):
        return 1.0
    return 0.0

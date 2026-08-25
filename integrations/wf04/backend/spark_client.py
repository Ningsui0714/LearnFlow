"""标准库 urllib 实现的讯飞星火 OpenAI 兼容聊天客户端（零第三方依赖）。

讲解正文本地化后，后端直接用 ``urllib`` 直连星火 OpenAI 兼容端点
（``spark-api-open.xf-yun.com/v1/chat/completions``），不再依赖星辰画布工作流。
本模块只负责 chat completion 请求/响应；检索侧（本地 FTS5 知识库 + Bing RSS
联网证据）均不需要 embedding，因此不提供 embeddings 调用。

凭据注意：这里的 ``api_key`` 是星火大模型 API 的 APIPassword，与星辰工作流
网关的 ``api_key:api_secret`` 是两套独立的凭据，不能混用。
"""

from __future__ import annotations

import json
import socket
import urllib.error
import urllib.request
from contextlib import closing
from dataclasses import dataclass
from typing import Any

SPARK_DEFAULT_API_BASE = "https://spark-api-open.xf-yun.com/v1/chat/completions"
SPARK_DEFAULT_MODEL = "lite"


class SparkError(Exception):
    """星火直连调用失败。

    ``kind`` 用于让上层决定降级策略：
    - ``timeout`` / ``network``：可重试（引擎至多重试 1 次）
    - ``auth`` / ``refused``：不重试（配错或限流，重试无意义）
    - ``parse`` / ``empty``：响应异常，走模板降级
    - ``http``：服务端错误
    """

    def __init__(self, kind: str, message: str) -> None:
        super().__init__(message)
        self.kind = kind
        self.message = message


@dataclass(frozen=True)
class SparkConfig:
    api_base: str = SPARK_DEFAULT_API_BASE
    api_key: str = ""
    model: str = SPARK_DEFAULT_MODEL
    timeout: float = 60.0
    max_tokens: int = 1600
    temperature: float = 0.4

    @property
    def configured(self) -> bool:
        return bool(self.api_key.strip())


class SparkClient:
    def __init__(self, config: SparkConfig) -> None:
        self.config = config

    @property
    def configured(self) -> bool:
        return self.config.configured

    def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        """POST 到 OpenAI 兼容端点，返回 ``choices[0].message.content``。

        恒为 ``stream:false``；底层不重试，重试/降级由调用方决定。
        """
        if not self.config.configured:
            raise SparkError("auth", "未配置星火 API 密钥（SPARK_API_KEY）")
        body: dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "temperature": (
                self.config.temperature if temperature is None else temperature
            ),
            "max_tokens": (
                self.config.max_tokens if max_tokens is None else max_tokens
            ),
            "stream": False,
        }
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            self.config.api_base,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.config.api_key.strip()}",
            },
            method="POST",
        )
        try:
            response = urllib.request.urlopen(request, timeout=self.config.timeout)
        except urllib.error.HTTPError as error:
            status = int(getattr(error, "code", 0) or 0)
            reason = str(getattr(error, "reason", "") or "")
            if status in (401, 403):
                raise SparkError("auth", f"星火鉴权失败（HTTP {status}）") from error
            if status == 429:
                raise SparkError("refused", "星火请求过于频繁（HTTP 429）") from error
            if status >= 500:
                raise SparkError("http", f"星火服务端错误（HTTP {status}）") from error
            raise SparkError("http", f"星火请求失败（HTTP {status}）：{reason}") from error
        except (socket.timeout, TimeoutError) as error:
            raise SparkError("timeout", "星火请求超时") from error
        except urllib.error.URLError as error:
            raise SparkError(
                "network", f"星火网络错误：{getattr(error, 'reason', error)}"
            ) from error
        try:
            with closing(response):
                raw = response.read().decode("utf-8", errors="replace")
        except Exception as error:
            raise SparkError("network", f"读取星火响应失败：{error}") from error
        try:
            data = json.loads(raw)
        except (ValueError, TypeError) as error:
            raise SparkError(
                "parse", f"星火响应不是合法 JSON：{str(error)[:160]}"
            ) from error
        choices = data.get("choices") if isinstance(data, dict) else None
        if not isinstance(choices, list) or not choices:
            raise SparkError("empty", "星火响应没有 choices")
        content = ""
        for choice in choices:
            if not isinstance(choice, dict):
                continue
            message = choice.get("message")
            if isinstance(message, dict) and isinstance(message.get("content"), str):
                content = message["content"]
                break
        if not content.strip():
            raise SparkError("empty", "星火响应正文为空")
        return content.strip()

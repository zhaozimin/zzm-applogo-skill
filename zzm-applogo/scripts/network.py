#!/usr/bin/env python3
"""
[INPUT]: 依赖 urllib 的 HTTPS 能力与 Apple 搜索接口的限速约束。
[OUTPUT]: 提供 HttpClient 与 SourceError。
[POS]: scripts 的网络边界。供图源适配器复用。
[PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

MAX_BYTES = 25 * 1024 * 1024
APPLE_INTERVAL = 3.1
USER_AGENT = "zzm-applogo/1.0 (+https://github.com/zhaozimin/zzm-applogo-skill)"


class SourceError(RuntimeError):
    """网络或远端数据失败。与搜索无结果区分。"""


class HttpClient:
    def __init__(self, timeout: float = 15, retries: int = 2):
        self.timeout = timeout
        self.retries = retries
        self._cache: dict[tuple[str, bytes | None], bytes] = {}
        self._apple_last = 0.0

    def get(self, url: str) -> bytes:
        return self._request(url)

    def json(self, url: str, payload: dict[str, Any] | None = None) -> dict:
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        try:
            result = json.loads(self._request(url, data))
        except (ValueError, UnicodeError) as exc:
            raise SourceError("图源返回了无效 JSON") from exc
        if not isinstance(result, dict):
            raise SourceError("图源返回的数据结构无效")
        return result

    def _request(self, url: str, data: bytes | None = None) -> bytes:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username:
            raise SourceError("图源必须使用不含凭证的 HTTPS 地址")
        key = (url, data)
        if key in self._cache:
            return self._cache[key]
        for attempt in range(self.retries):
            if parsed.hostname == "itunes.apple.com":
                delay = APPLE_INTERVAL - (time.monotonic() - self._apple_last)
                if delay > 0:
                    time.sleep(delay)
                self._apple_last = time.monotonic()
            request = urllib.request.Request(url, data=data, headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/json, image/*;q=0.9, */*;q=0.5",
                "Content-Type": "application/json",
            })
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    if urllib.parse.urlparse(response.url).scheme != "https":
                        raise SourceError("图源重定向到非 HTTPS 地址")
                    raw = response.read(MAX_BYTES + 1)
                    if len(raw) > MAX_BYTES:
                        raise SourceError("图源文件超过 25 MiB")
                self._cache[key] = raw
                return raw
            except urllib.error.HTTPError as exc:
                if exc.code not in {429, 500, 502, 503, 504} or attempt + 1 >= self.retries:
                    raise SourceError(f"{parsed.hostname} 返回 HTTP {exc.code}") from exc
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                if attempt + 1 >= self.retries:
                    raise SourceError(f"无法连接 {parsed.hostname}: {type(exc).__name__}") from exc
            time.sleep(0.6 * (attempt + 1))
        raise SourceError(f"无法连接 {parsed.hostname}")

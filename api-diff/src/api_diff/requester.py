"""
HTTP 请求模块：向两端发送 raw POST 请求，不做任何内容解析
"""
from __future__ import annotations

from typing import Any

import httpx


DEFAULT_TIMEOUT = 60.0


def post_raw(
    url: str,
    api_key: str,
    payload: dict[str, Any],
    extra_headers: dict[str, str] | None = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> tuple[int, dict[str, Any]]:
    """
    向指定 URL 发送 POST 请求，返回 (status_code, response_json)。
    出错时返回 (status_code, {"error": "..."})。
    """
    headers: dict[str, str] = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    if extra_headers:
        headers.update(extra_headers)

    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(url, json=payload, headers=headers)
            status_code = resp.status_code
            try:
                body = resp.json()
            except Exception:
                body = {"error": f"Non-JSON response: {resp.text[:500]}"}
            return status_code, body
    except httpx.TimeoutException as e:
        return 0, {"error": f"Timeout: {e}"}
    except httpx.RequestError as e:
        return 0, {"error": f"Request error: {e}"}
    except Exception as e:
        return 0, {"error": f"Unexpected error: {e}"}

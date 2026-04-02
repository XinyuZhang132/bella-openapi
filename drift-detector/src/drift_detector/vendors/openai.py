"""
OpenAI 文档适配器
OpenAI 提供标准 OpenAPI YAML spec，可直接使用 DocSnapshotter 处理。
此模块提供额外的辅助功能：解析模型列表、提取模型能力等。
"""
from __future__ import annotations

from typing import Any

import httpx
import yaml


OPENAI_OPENAPI_SPEC_URL = (
    "https://raw.githubusercontent.com/openai/openai-openapi/master/openapi.yaml"
)


def fetch_openai_models(api_key: str, base_url: str = "https://api.openai.com") -> list[dict]:
    """从 OpenAI /v1/models 接口获取模型列表"""
    with httpx.Client(timeout=15) as client:
        resp = client.get(
            f"{base_url}/v1/models",
            headers={"Authorization": f"Bearer {api_key}"},
        )
        resp.raise_for_status()
        return resp.json().get("data", [])


def extract_model_capabilities(spec: dict, model_id: str) -> dict[str, Any]:
    """
    从 OpenAPI spec 提取指定模型的能力标注（如 max_tokens、supported_features）。
    OpenAI spec 通常用 enum/anyOf 描述模型列表。
    """
    # 在 spec 中搜索 model 参数的 enum 列表
    paths = spec.get("paths", {})
    chat_op = paths.get("/chat/completions", {}).get("post", {})
    req_body = chat_op.get("requestBody", {})
    model_schema = (
        req_body
        .get("content", {})
        .get("application/json", {})
        .get("schema", {})
        .get("properties", {})
        .get("model", {})
    )
    return model_schema

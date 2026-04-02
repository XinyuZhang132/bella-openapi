"""
AWS Bedrock 适配器
AWS Bedrock 使用 botocore service model JSON 定义 API schema。
需要安装 boto3: pip install boto3
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_botocore_service_model(service_name: str = "bedrock-runtime") -> dict:
    """
    从本地 botocore 安装路径加载 service model JSON。
    需要 boto3 已安装。
    """
    try:
        import botocore
        data_path = Path(botocore.__file__).parent / "data" / service_name
        if not data_path.exists():
            raise FileNotFoundError(f"botocore service model not found: {data_path}")
        # 取最新版本目录
        versions = sorted(data_path.iterdir(), reverse=True)
        for v_dir in versions:
            model_file = v_dir / "service-2.json"
            if model_file.exists():
                return json.loads(model_file.read_text())
        raise FileNotFoundError(f"No service-2.json found in {data_path}")
    except ImportError:
        raise ImportError("boto3/botocore is not installed. Run: pip install boto3")


def extract_converse_schema(service_model: dict) -> tuple[dict, dict]:
    """
    从 botocore service model 提取 Converse API 的 input/output shape。
    """
    shapes = service_model.get("shapes", {})
    operations = service_model.get("operations", {})

    converse_op = operations.get("Converse", {})
    input_shape_name = converse_op.get("input", {}).get("shape")
    output_shape_name = converse_op.get("output", {}).get("shape")

    def resolve_shape(name: str, depth: int = 0) -> dict:
        if depth > 5 or not name:
            return {}
        shape = shapes.get(name, {})
        shape_type = shape.get("type", "")
        if shape_type == "structure":
            members = {}
            for member_name, member_def in shape.get("members", {}).items():
                members[member_name] = resolve_shape(member_def.get("shape"), depth + 1)
            return {"type": "object", "properties": members}
        elif shape_type == "list":
            item_shape = resolve_shape(shape.get("member", {}).get("shape"), depth + 1)
            return {"type": "array", "items": item_shape}
        elif shape_type == "map":
            return {"type": "object", "additionalProperties": True}
        elif shape_type in ("string", "integer", "boolean", "long", "float", "double", "blob", "timestamp"):
            return {"type": shape_type}
        return {"shape": name}

    req_schema = resolve_shape(input_shape_name) if input_shape_name else {}
    resp_schema = resolve_shape(output_shape_name) if output_shape_name else {}
    return req_schema, resp_schema

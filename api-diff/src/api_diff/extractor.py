"""
响应结构提取：将 raw response dict 转换为字段名→类型的结构 dict。
逻辑直接复制自 drift-detector 的 _extract_structure。
"""
from __future__ import annotations

from typing import Any


def extract_structure(obj: Any, depth: int = 0, max_depth: int = 8) -> Any:
    """
    提取 JSON 对象的结构（字段名 → 类型），值用类型名替换。
    数组取第一个元素作为代表。
    """
    if depth > max_depth:
        return "<truncated>"
    if obj is None:
        return "null"
    if isinstance(obj, bool):
        return "boolean"
    if isinstance(obj, int):
        return "integer"
    if isinstance(obj, float):
        return "number"
    if isinstance(obj, str):
        return "string"
    if isinstance(obj, list):
        if not obj:
            return []
        return [extract_structure(obj[0], depth + 1, max_depth)]
    if isinstance(obj, dict):
        return {k: extract_structure(v, depth + 1, max_depth) for k, v in obj.items()}
    return type(obj).__name__

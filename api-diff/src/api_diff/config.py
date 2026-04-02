"""
配置加载：读取 config/endpoints.yaml 和 config/models.yaml，以及 prompts/ 目录
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


# 默认配置目录（相对于本文件三层父目录，即 api-diff/）
_ROOT = Path(__file__).parent.parent.parent


@dataclass
class SideConfig:
    """单侧请求配置（某个 vendor 的官方端，或 bella 网关端）"""
    url: str
    auth_env: str
    extra_headers: dict[str, str] = field(default_factory=dict)

    @property
    def api_key(self) -> str:
        return os.environ.get(self.auth_env, "")


@dataclass
class EndpointConfig:
    """一个 endpoint 类型的完整配置：bella 侧 + 多个 vendor 官方侧"""
    name: str
    bella: SideConfig
    # vendor_name -> 官方侧配置
    vendors: dict[str, SideConfig] = field(default_factory=dict)


@dataclass
class PromptConfig:
    """一个 prompt 场景的配置"""
    name: str
    description: str
    # endpoint_type -> payload dict（不含 model 字段）
    payloads: dict[str, dict[str, Any]] = field(default_factory=dict)


def load_endpoints(config_dir: Path | None = None) -> dict[str, EndpointConfig]:
    """
    加载 endpoints.yaml。
    返回: {endpoint_type: EndpointConfig}
    """
    config_dir = config_dir or _ROOT / "config"
    path = config_dir / "endpoints.yaml"
    raw = yaml.safe_load(path.read_text())

    result: dict[str, EndpointConfig] = {}
    for ep_name, ep_data in raw.get("endpoints", {}).items():
        bella_data = ep_data["bella"]
        bella = SideConfig(
            url=bella_data["url"],
            auth_env=bella_data["auth_env"],
            extra_headers=bella_data.get("extra_headers", {}),
        )
        vendors: dict[str, SideConfig] = {}
        for vendor_name, vendor_data in ep_data.get("vendors", {}).items():
            vendors[vendor_name] = SideConfig(
                url=vendor_data.get("url", ""),
                auth_env=vendor_data.get("auth_env", ""),
                extra_headers=vendor_data.get("extra_headers", {}),
            )
        result[ep_name] = EndpointConfig(name=ep_name, bella=bella, vendors=vendors)
    return result


def load_models(config_dir: Path | None = None) -> dict[str, dict[str, list[str]]]:
    """
    加载 models.yaml。
    返回: {vendor: {endpoint_type: [model_id, ...]}}
    """
    config_dir = config_dir or _ROOT / "config"
    path = config_dir / "models.yaml"
    raw = yaml.safe_load(path.read_text())
    # 过滤掉非字符串的模型 ID（如占位符 []）
    result: dict[str, dict[str, list[str]]] = {}
    for vendor, ep_map in raw.get("models", {}).items():
        result[vendor] = {}
        for ep_type, model_ids in ep_map.items():
            if isinstance(model_ids, list):
                result[vendor][ep_type] = [m for m in model_ids if isinstance(m, str)]
            else:
                result[vendor][ep_type] = []
    return result


def load_prompts(prompts_dir: Path | None = None) -> dict[str, PromptConfig]:
    """
    加载 prompts/ 目录下的所有 YAML 文件。
    返回: {prompt_name: PromptConfig}
    """
    prompts_dir = prompts_dir or _ROOT / "prompts"
    result: dict[str, PromptConfig] = {}
    for yaml_file in sorted(prompts_dir.glob("*.yaml")):
        raw = yaml.safe_load(yaml_file.read_text())
        name = raw["name"]
        description = raw.get("description", "")
        payloads = {
            k: v
            for k, v in raw.items()
            if k not in ("name", "description") and isinstance(v, dict)
        }
        result[name] = PromptConfig(name=name, description=description, payloads=payloads)
    return result


def find_vendor_models(
    models: dict[str, dict[str, list[str]]],
    endpoint_type: str,
    vendor: str | None = None,
) -> list[tuple[str, str]]:
    """
    返回 (vendor, model_id) 列表。
    - vendor 指定时：只返回该 vendor 下的模型
    - vendor 为 None 时：返回所有 vendor 的模型
    """
    pairs: list[tuple[str, str]] = []
    for v, ep_map in models.items():
        if vendor and v != vendor:
            continue
        for model_id in ep_map.get(endpoint_type, []):
            pairs.append((v, model_id))
    return pairs

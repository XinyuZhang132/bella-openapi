"""
配置加载：从 YAML 文件读取厂商和探针配置，支持环境变量替换
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


# 环境变量替换模式：${VAR_NAME} 或 ${VAR_NAME:-default_value}
_ENV_PATTERN = re.compile(r"\$\{([^}:]+)(?::-(.*?))?\}")


def _expand_env(value: str) -> str:
    """替换字符串中的环境变量引用"""
    def replace(m: re.Match) -> str:
        var_name = m.group(1)
        default = m.group(2) if m.group(2) is not None else ""
        return os.environ.get(var_name, default)
    return _ENV_PATTERN.sub(replace, value)


def _expand_env_recursive(obj: Any) -> Any:
    """递归替换字典/列表中所有字符串的环境变量"""
    if isinstance(obj, str):
        return _expand_env(obj)
    elif isinstance(obj, dict):
        return {k: _expand_env_recursive(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_expand_env_recursive(item) for item in obj]
    return obj


@dataclass
class TestApiConfig:
    base_url: str
    api_key: str
    timeout: int = 30


@dataclass
class EndpointConfig:
    name: str
    path: str
    probe_model: str = ""


@dataclass
class VendorConfig:
    name: str  # vendor key，如 "openai"
    display_name: str
    adapter_class: str
    enabled: bool
    doc_spec_url: str | None
    doc_spec_format: str
    test_api: TestApiConfig
    endpoints: list[EndpointConfig]

    @classmethod
    def from_dict(cls, name: str, d: dict) -> "VendorConfig":
        d = _expand_env_recursive(d)
        ta = d.get("test_api", {})
        endpoints = [
            EndpointConfig(**ep)
            for ep in d.get("endpoints", [])
        ]
        return cls(
            name=name,
            display_name=d.get("display_name", name),
            adapter_class=d.get("adapter_class", name),
            enabled=d.get("enabled", True),
            doc_spec_url=d.get("doc_spec_url"),
            doc_spec_format=d.get("doc_spec_format", "none"),
            test_api=TestApiConfig(
                base_url=ta.get("base_url", "http://localhost:8080"),
                api_key=ta.get("api_key", ""),
                timeout=int(ta.get("timeout", 30)),
            ),
            endpoints=endpoints,
        )


@dataclass
class ProbeConfig:
    name: str
    description: str
    payload: dict[str, Any]
    skip: bool = False


@dataclass
class AppConfig:
    vendors: dict[str, VendorConfig] = field(default_factory=dict)
    probes: dict[str, ProbeConfig] = field(default_factory=dict)
    ignore_fields: list[str] = field(default_factory=list)
    snapshots_dir: Path = Path("snapshots")


def load_config(
    vendors_path: Path | None = None,
    probes_path: Path | None = None,
    snapshots_dir: Path | None = None,
) -> AppConfig:
    """加载配置文件，返回 AppConfig"""
    config_dir = Path(__file__).parent.parent.parent / "config"

    vendors_path = vendors_path or config_dir / "vendors.yaml"
    probes_path = probes_path or config_dir / "probes.yaml"

    vendors: dict[str, VendorConfig] = {}
    if vendors_path.exists():
        raw = yaml.safe_load(vendors_path.read_text())
        for name, data in raw.get("vendors", {}).items():
            vendors[name] = VendorConfig.from_dict(name, data)

    probes: dict[str, ProbeConfig] = {}
    ignore_fields: list[str] = []
    if probes_path.exists():
        raw = yaml.safe_load(probes_path.read_text())
        for name, data in raw.get("probes", {}).items():
            probes[name] = ProbeConfig(
                name=name,
                description=data.get("description", ""),
                payload=_expand_env_recursive(data.get("payload", {})),
                skip=data.get("skip", False),
            )
        ignore_fields = raw.get("ignore_fields", [])

    return AppConfig(
        vendors=vendors,
        probes=probes,
        ignore_fields=ignore_fields,
        snapshots_dir=snapshots_dir or Path("snapshots"),
    )

"""
Layer 1 快照采集：从官方文档 spec（OpenAPI YAML/JSON）提取 request/response schema
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import yaml

from drift_detector.config import AppConfig, VendorConfig
from drift_detector.models import Snapshot, SnapshotSource
from drift_detector.snapshotter.base import BaseSnapshotter

# endpoint name → 对应 OpenAPI path 的映射
_ENDPOINT_PATH_MAP: dict[str, list[str]] = {
    "chat_completions": ["/chat/completions", "/v1/chat/completions"],
    "messages": ["/messages", "/v1/messages"],
    "embeddings": ["/embeddings", "/v1/embeddings"],
    "tts": ["/audio/speech", "/v1/audio/speech"],
    "asr_flash": ["/audio/transcriptions", "/v1/audio/transcriptions"],
    "images_generations": ["/images/generations", "/v1/images/generations"],
}


def _fetch_spec(url: str) -> dict:
    """从 URL 获取 OpenAPI spec（支持 YAML 和 JSON）"""
    with httpx.Client(timeout=30, follow_redirects=True) as client:
        resp = client.get(url)
        resp.raise_for_status()
        content = resp.text
        if url.endswith(".yaml") or url.endswith(".yml") or "yaml" in resp.headers.get("content-type", ""):
            return yaml.safe_load(content)
        return resp.json()


def _resolve_ref(spec: dict, ref: str) -> dict:
    """解析 $ref 引用（仅支持本地 #/components/... 格式）"""
    if not ref.startswith("#/"):
        return {}
    parts = ref.lstrip("#/").split("/")
    obj = spec
    for part in parts:
        obj = obj.get(part, {})
    return obj


def _inline_refs(spec: dict, schema: Any, depth: int = 0) -> Any:
    """递归展开 $ref，最多展开 5 层"""
    if depth > 5 or not isinstance(schema, dict):
        return schema
    if "$ref" in schema:
        resolved = _resolve_ref(spec, schema["$ref"])
        return _inline_refs(spec, resolved, depth + 1)
    result = {}
    for k, v in schema.items():
        if isinstance(v, dict):
            result[k] = _inline_refs(spec, v, depth + 1)
        elif isinstance(v, list):
            result[k] = [_inline_refs(spec, item, depth + 1) if isinstance(item, dict) else item for item in v]
        else:
            result[k] = v
    return result


def _extract_endpoint_schema(
    spec: dict, endpoint_name: str
) -> tuple[dict, dict]:
    """从 OpenAPI spec 中提取指定 endpoint 的 request/response schema"""
    paths = spec.get("paths", {})
    candidate_paths = _ENDPOINT_PATH_MAP.get(endpoint_name, [f"/{endpoint_name}"])

    for candidate in candidate_paths:
        path_item = paths.get(candidate, {})
        if not path_item:
            continue
        # 通常是 POST
        operation = path_item.get("post", path_item.get("get", {}))
        if not operation:
            continue

        # Request schema
        req_schema: dict = {}
        req_body = operation.get("requestBody", {})
        if req_body:
            content = req_body.get("content", {})
            json_content = content.get("application/json", content.get("*/*", {}))
            req_schema = _inline_refs(spec, json_content.get("schema", {}))

        # Response schema（取 200 或 2xx）
        resp_schema: dict = {}
        responses = operation.get("responses", {})
        resp_200 = responses.get("200", responses.get("2XX", responses.get("default", {})))
        if resp_200:
            content = resp_200.get("content", {})
            json_content = content.get("application/json", content.get("text/event-stream", {}))
            resp_schema = _inline_refs(spec, json_content.get("schema", {}))

        return req_schema, resp_schema

    return {}, {}


class DocSnapshotter(BaseSnapshotter):
    """从官方文档 OpenAPI spec 采集 schema 快照（Layer 1）"""

    def __init__(self, config: AppConfig):
        super().__init__(config)

    def capture(self, vendor: str, endpoint_name: str) -> Snapshot:
        vendor_cfg = self.config.vendors.get(vendor)
        if not vendor_cfg:
            raise ValueError(f"Vendor '{vendor}' not found in config")

        if not vendor_cfg.doc_spec_url or vendor_cfg.doc_spec_format == "none":
            return Snapshot(
                vendor=vendor,
                endpoint=endpoint_name,
                source=SnapshotSource.DOC,
                captured_at=Snapshot.now_iso(),
                error=f"Vendor '{vendor}' has no doc spec configured (format: {vendor_cfg.doc_spec_format})",
            )

        captured_at = Snapshot.now_iso()
        error = ""
        req_schema: dict = {}
        resp_schema: dict = {}
        spec_version = ""

        try:
            if vendor_cfg.doc_spec_format in ("openapi_yaml", "openapi_json"):
                spec = _fetch_spec(vendor_cfg.doc_spec_url)
                spec_version = (
                    spec.get("info", {}).get("version", "")
                    or spec.get("openapi", "")
                )
                req_schema, resp_schema = _extract_endpoint_schema(spec, endpoint_name)
            else:
                error = f"Unsupported doc format: {vendor_cfg.doc_spec_format}"
        except Exception as e:
            error = str(e)

        return Snapshot(
            vendor=vendor,
            endpoint=endpoint_name,
            source=SnapshotSource.DOC,
            captured_at=captured_at,
            request_schema=req_schema,
            response_schema=resp_schema,
            spec_version=spec_version,
            error=error,
        )

    def capture_all(self) -> list[Snapshot]:
        snapshots = []
        for vendor_name, vendor_cfg in self.config.vendors.items():
            if not vendor_cfg.enabled:
                continue
            for ep in vendor_cfg.endpoints:
                snap = self.capture(vendor_name, ep.name)
                self.save_snapshot(snap)
                snapshots.append(snap)
        return snapshots

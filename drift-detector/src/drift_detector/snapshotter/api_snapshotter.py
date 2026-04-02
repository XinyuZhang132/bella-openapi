"""
Layer 2 快照采集：向私有测试 API 发送 probe 请求，记录实际响应结构
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx

from drift_detector.config import AppConfig, VendorConfig, EndpointConfig
from drift_detector.models import Snapshot, SnapshotSource
from drift_detector.snapshotter.base import BaseSnapshotter


def _extract_structure(obj: Any, depth: int = 0, max_depth: int = 8) -> Any:
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
        return [_extract_structure(obj[0], depth + 1, max_depth)]
    if isinstance(obj, dict):
        return {k: _extract_structure(v, depth + 1, max_depth) for k, v in obj.items()}
    return type(obj).__name__


class ApiSnapshotter(BaseSnapshotter):
    """向私有测试 API 发送 probe 请求，采集实际响应结构快照"""

    def __init__(self, config: AppConfig):
        super().__init__(config)

    def capture(self, vendor: str, endpoint_name: str) -> Snapshot:
        vendor_cfg = self.config.vendors.get(vendor)
        if not vendor_cfg:
            raise ValueError(f"Vendor '{vendor}' not found in config")

        ep = next((e for e in vendor_cfg.endpoints if e.name == endpoint_name), None)
        if not ep:
            raise ValueError(f"Endpoint '{endpoint_name}' not found for vendor '{vendor}'")

        probe_cfg = self.config.probes.get(endpoint_name)
        if probe_cfg and probe_cfg.skip:
            snapshot = Snapshot(
                vendor=vendor,
                endpoint=endpoint_name,
                source=SnapshotSource.API,
                captured_at=Snapshot.now_iso(),
                error=f"Probe '{endpoint_name}' is marked as skip",
            )
            return snapshot

        payload = self._build_payload(ep, endpoint_name)
        return self._do_probe(vendor_cfg, ep, payload)

    def _build_payload(self, ep: EndpointConfig, endpoint_name: str) -> dict:
        """合并探针 payload 和模型配置"""
        probe_cfg = self.config.probes.get(endpoint_name)
        payload = dict(probe_cfg.payload) if probe_cfg else {}
        if ep.probe_model and "model" not in payload:
            payload["model"] = ep.probe_model
        return payload

    def _do_probe(
        self,
        vendor_cfg: VendorConfig,
        ep: EndpointConfig,
        payload: dict,
    ) -> Snapshot:
        """执行实际 HTTP 请求"""
        url = vendor_cfg.test_api.base_url.rstrip("/") + ep.path
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {vendor_cfg.test_api.api_key}",
        }

        captured_at = Snapshot.now_iso()
        http_status = 0
        error = ""
        response_structure: dict = {}
        raw_response: dict = {}

        try:
            with httpx.Client(timeout=vendor_cfg.test_api.timeout) as client:
                resp = client.post(url, json=payload, headers=headers)
                http_status = resp.status_code

                if resp.status_code == 200:
                    raw_response = resp.json()
                    response_structure = _extract_structure(raw_response)
                else:
                    error = f"HTTP {resp.status_code}: {resp.text[:500]}"

        except httpx.TimeoutException as e:
            error = f"Timeout: {e}"
        except httpx.RequestError as e:
            error = f"Request error: {e}"
        except Exception as e:
            error = f"Unexpected error: {e}"

        return Snapshot(
            vendor=vendor_cfg.name,
            endpoint=ep.name,
            source=SnapshotSource.API,
            captured_at=captured_at,
            response_structure=response_structure,
            probe_request=payload,
            http_status=http_status,
            error=error,
        )

    def capture_all(self) -> list[Snapshot]:
        """采集所有启用厂商的所有 endpoint"""
        snapshots = []
        for vendor_name, vendor_cfg in self.config.vendors.items():
            if not vendor_cfg.enabled:
                continue
            for ep in vendor_cfg.endpoints:
                snap = self.capture(vendor_name, ep.name)
                saved_path = self.save_snapshot(snap)
                snapshots.append(snap)
        return snapshots

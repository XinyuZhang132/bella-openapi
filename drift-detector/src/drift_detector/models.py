"""
核心数据模型：Snapshot、DiffItem、DriftReport
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any


class ChangeType(str, Enum):
    ADDED = "added"
    REMOVED = "removed"
    MODIFIED = "modified"
    TYPE_CHANGED = "type_changed"


class Severity(str, Enum):
    BREAKING = "breaking"       # 破坏性变更（移除字段、类型变更）
    NON_BREAKING = "non_breaking"  # 非破坏性（新增可选字段）
    INFO = "info"               # 信息性（description 变更等）


class SnapshotSource(str, Enum):
    DOC = "doc"     # 来自官方文档 spec
    API = "api"     # 来自实际 API 响应


@dataclass
class Snapshot:
    """某时刻某厂商某接口的状态快照"""
    vendor: str
    endpoint: str
    source: SnapshotSource
    captured_at: str  # ISO datetime string
    # 文档来源时：提取的 request/response JSON Schema
    request_schema: dict[str, Any] = field(default_factory=dict)
    response_schema: dict[str, Any] = field(default_factory=dict)
    # API 来源时：实际响应的结构（字段名 → 类型，值已脱敏）
    response_structure: dict[str, Any] = field(default_factory=dict)
    # 文档版本（如有）
    spec_version: str = ""
    # 原始 probe 请求（API source）
    probe_request: dict[str, Any] = field(default_factory=dict)
    # HTTP 状态码（API source）
    http_status: int = 0
    # 错误信息（采集失败时）
    error: str = ""

    @classmethod
    def now_iso(cls) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    def to_dict(self) -> dict:
        d = asdict(self)
        d["source"] = self.source.value
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Snapshot":
        d = d.copy()
        d["source"] = SnapshotSource(d["source"])
        return cls(**d)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2))

    @classmethod
    def load(cls, path: Path) -> "Snapshot":
        return cls.from_dict(json.loads(path.read_text()))


@dataclass
class DiffItem:
    """单个字段/路径级别的差异"""
    path: str               # JSON path，如 "response.choices[].message.content"
    change_type: ChangeType
    before: Any = None
    after: Any = None
    severity: Severity = Severity.INFO
    note: str = ""          # 可读描述

    def to_dict(self) -> dict:
        d = asdict(self)
        d["change_type"] = self.change_type.value
        d["severity"] = self.severity.value
        return d

    @property
    def symbol(self) -> str:
        return {
            ChangeType.ADDED: "+",
            ChangeType.REMOVED: "-",
            ChangeType.MODIFIED: "~",
            ChangeType.TYPE_CHANGED: "!",
        }[self.change_type]


@dataclass
class DriftReport:
    """两个快照之间的完整差异报告"""
    vendor: str
    endpoint: str
    source: SnapshotSource
    baseline_snapshot_path: str
    current_snapshot_path: str
    baseline_captured_at: str
    current_captured_at: str
    diffs: list[DiffItem] = field(default_factory=list)
    generated_at: str = field(default_factory=Snapshot.now_iso)

    @property
    def has_changes(self) -> bool:
        return len(self.diffs) > 0

    @property
    def breaking_count(self) -> int:
        return sum(1 for d in self.diffs if d.severity == Severity.BREAKING)

    @property
    def summary(self) -> str:
        if not self.has_changes:
            return f"[{self.vendor}/{self.endpoint}] No changes detected."
        parts = []
        added = [d for d in self.diffs if d.change_type == ChangeType.ADDED]
        removed = [d for d in self.diffs if d.change_type == ChangeType.REMOVED]
        modified = [d for d in self.diffs if d.change_type in (ChangeType.MODIFIED, ChangeType.TYPE_CHANGED)]
        if added:
            parts.append(f"+{len(added)} added")
        if removed:
            parts.append(f"-{len(removed)} removed")
        if modified:
            parts.append(f"~{len(modified)} modified")
        breaking = self.breaking_count
        suffix = f" [{breaking} BREAKING]" if breaking else ""
        return f"[{self.vendor}/{self.endpoint}] {', '.join(parts)}{suffix}"

    def to_dict(self) -> dict:
        return {
            "vendor": self.vendor,
            "endpoint": self.endpoint,
            "source": self.source.value,
            "baseline_snapshot_path": self.baseline_snapshot_path,
            "current_snapshot_path": self.current_snapshot_path,
            "baseline_captured_at": self.baseline_captured_at,
            "current_captured_at": self.current_captured_at,
            "diffs": [d.to_dict() for d in self.diffs],
            "generated_at": self.generated_at,
        }

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2))

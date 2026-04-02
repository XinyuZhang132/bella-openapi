"""
Diff 引擎：对比两个快照，生成 DriftReport
"""
from __future__ import annotations

from typing import Any

from deepdiff import DeepDiff

from drift_detector.models import (
    DiffItem, DriftReport, Snapshot, SnapshotSource,
    ChangeType, Severity
)


# 字段路径 → Severity 规则（包含任意关键字则判定为 BREAKING）
_BREAKING_KEYWORDS = {"required", "type"}
_NON_BREAKING_KEYWORDS = {"description", "example", "default", "deprecated"}


def _infer_severity(path: str, change_type: ChangeType, before: Any, after: Any) -> Severity:
    """根据 path 和变更类型推断严重程度"""
    if change_type == ChangeType.REMOVED:
        return Severity.BREAKING
    if change_type == ChangeType.TYPE_CHANGED:
        return Severity.BREAKING
    if change_type == ChangeType.MODIFIED:
        path_lower = path.lower()
        if any(kw in path_lower for kw in _BREAKING_KEYWORDS):
            return Severity.BREAKING
        if any(kw in path_lower for kw in _NON_BREAKING_KEYWORDS):
            return Severity.INFO
        return Severity.NON_BREAKING
    if change_type == ChangeType.ADDED:
        return Severity.NON_BREAKING
    return Severity.INFO


def _normalize_deepdiff_path(path: str) -> str:
    """将 deepdiff 的 root['key']['sub'] 格式转换为 key.sub 格式"""
    import re
    path = path.replace("root", "")
    path = re.sub(r"\['([^']+)'\]", r".\1", path)
    path = re.sub(r"\[(\d+)\]", r"[\1]", path)
    return path.lstrip(".")


def diff_dicts(
    baseline: dict,
    current: dict,
    prefix: str = "",
    ignore_fields: list[str] | None = None,
) -> list[DiffItem]:
    """使用 deepdiff 对比两个字典，返回 DiffItem 列表"""
    exclude_paths = set()
    if ignore_fields:
        for f in ignore_fields:
            if f.startswith("$."):
                # JSONPath 格式转 deepdiff 格式（简单处理）
                exclude_paths.add(f"root{f[1:].replace('.', \"['\"].replace('[', '['\").replace(']', \"']\")}")

    dd = DeepDiff(
        baseline,
        current,
        ignore_order=True,
        exclude_paths=exclude_paths if exclude_paths else None,
        verbose_level=2,
    )

    items: list[DiffItem] = []

    # 新增的 key
    for raw_path, value in dd.get("dictionary_item_added", {}).items():
        path = _normalize_deepdiff_path(str(raw_path))
        if prefix:
            path = f"{prefix}.{path}"
        items.append(DiffItem(
            path=path,
            change_type=ChangeType.ADDED,
            before=None,
            after=value,
            severity=_infer_severity(path, ChangeType.ADDED, None, value),
        ))

    # 删除的 key
    for raw_path, value in dd.get("dictionary_item_removed", {}).items():
        path = _normalize_deepdiff_path(str(raw_path))
        if prefix:
            path = f"{prefix}.{path}"
        items.append(DiffItem(
            path=path,
            change_type=ChangeType.REMOVED,
            before=value,
            after=None,
            severity=_infer_severity(path, ChangeType.REMOVED, value, None),
        ))

    # 值变更
    for raw_path, change in dd.get("values_changed", {}).items():
        path = _normalize_deepdiff_path(str(raw_path))
        if prefix:
            path = f"{prefix}.{path}"
        before = change.get("old_value")
        after = change.get("new_value")
        items.append(DiffItem(
            path=path,
            change_type=ChangeType.MODIFIED,
            before=before,
            after=after,
            severity=_infer_severity(path, ChangeType.MODIFIED, before, after),
        ))

    # 类型变更
    for raw_path, change in dd.get("type_changes", {}).items():
        path = _normalize_deepdiff_path(str(raw_path))
        if prefix:
            path = f"{prefix}.{path}"
        before = f"{type(change.get('old_value')).__name__}: {change.get('old_value')}"
        after = f"{type(change.get('new_value')).__name__}: {change.get('new_value')}"
        items.append(DiffItem(
            path=path,
            change_type=ChangeType.TYPE_CHANGED,
            before=before,
            after=after,
            severity=Severity.BREAKING,
        ))

    return items


class DiffEngine:
    """对比两个快照，生成 DriftReport"""

    def __init__(self, ignore_fields: list[str] | None = None):
        self.ignore_fields = ignore_fields or []

    def compare(self, baseline: Snapshot, current: Snapshot) -> DriftReport:
        """对比两个快照"""
        assert baseline.vendor == current.vendor
        assert baseline.endpoint == current.endpoint
        assert baseline.source == current.source

        diffs: list[DiffItem] = []

        if baseline.source == SnapshotSource.DOC:
            # 对比 request schema 和 response schema
            diffs.extend(diff_dicts(
                baseline.request_schema,
                current.request_schema,
                prefix="request",
                ignore_fields=self.ignore_fields,
            ))
            diffs.extend(diff_dicts(
                baseline.response_schema,
                current.response_schema,
                prefix="response",
                ignore_fields=self.ignore_fields,
            ))
        else:
            # 对比 response_structure
            diffs.extend(diff_dicts(
                baseline.response_structure,
                current.response_structure,
                prefix="response_structure",
                ignore_fields=self.ignore_fields,
            ))

        return DriftReport(
            vendor=baseline.vendor,
            endpoint=baseline.endpoint,
            source=baseline.source,
            baseline_snapshot_path=str(baseline.vendor),
            current_snapshot_path=str(current.vendor),
            baseline_captured_at=baseline.captured_at,
            current_captured_at=current.captured_at,
            diffs=diffs,
        )

"""
对比 + 输出模块：对比两端响应结构，生成并打印差异报告。
核心逻辑（diff_dicts、DiffItem、DriftReport）直接内联，不依赖 drift-detector。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from io import StringIO
from typing import Any

from deepdiff import DeepDiff
from rich.console import Console
from rich.panel import Panel
from rich.text import Text


# ---------------------------------------------------------------------------
# 数据模型（精简版，不含 Snapshot 和持久化）
# ---------------------------------------------------------------------------

class ChangeType(str, Enum):
    ADDED = "added"
    REMOVED = "removed"
    MODIFIED = "modified"
    TYPE_CHANGED = "type_changed"


class Severity(str, Enum):
    BREAKING = "breaking"
    NON_BREAKING = "non_breaking"
    INFO = "info"


@dataclass
class DiffItem:
    path: str
    change_type: ChangeType
    before: Any = None
    after: Any = None
    severity: Severity = Severity.INFO

    @property
    def symbol(self) -> str:
        return {
            ChangeType.ADDED: "+",
            ChangeType.REMOVED: "-",
            ChangeType.MODIFIED: "~",
            ChangeType.TYPE_CHANGED: "!",
        }[self.change_type]


@dataclass
class CompareReport:
    """两端响应结构的比较报告（无快照持久化）"""
    endpoint: str
    vendor: str
    model: str
    prompt_name: str
    official_status: int
    bella_status: int
    captured_at: str
    diffs: list[DiffItem] = field(default_factory=list)
    official_error: str = ""
    bella_error: str = ""

    @property
    def has_changes(self) -> bool:
        return len(self.diffs) > 0

    @property
    def breaking_count(self) -> int:
        return sum(1 for d in self.diffs if d.severity == Severity.BREAKING)

    @property
    def has_errors(self) -> bool:
        return bool(self.official_error or self.bella_error)


# ---------------------------------------------------------------------------
# Diff 引擎（复用 drift-detector 的 diff_dicts 逻辑）
# ---------------------------------------------------------------------------

_BREAKING_KEYWORDS = {"required", "type"}
_NON_BREAKING_KEYWORDS = {"description", "example", "default", "deprecated"}


def _infer_severity(path: str, change_type: ChangeType, before: Any, after: Any) -> Severity:
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


def _normalize_path(path: str) -> str:
    import re
    path = path.replace("root", "")
    path = re.sub(r"\['([^']+)'\]", r".\1", path)
    path = re.sub(r"\[(\d+)\]", r"[\1]", path)
    return path.lstrip(".")


def diff_dicts(baseline: dict, current: dict) -> list[DiffItem]:
    """对比两个结构 dict，返回 DiffItem 列表"""
    dd = DeepDiff(baseline, current, ignore_order=True, verbose_level=2)
    items: list[DiffItem] = []

    for raw_path, value in dd.get("dictionary_item_added", {}).items():
        path = _normalize_path(str(raw_path))
        items.append(DiffItem(
            path=path,
            change_type=ChangeType.ADDED,
            before=None,
            after=value,
            severity=_infer_severity(path, ChangeType.ADDED, None, value),
        ))

    for raw_path, value in dd.get("dictionary_item_removed", {}).items():
        path = _normalize_path(str(raw_path))
        items.append(DiffItem(
            path=path,
            change_type=ChangeType.REMOVED,
            before=value,
            after=None,
            severity=_infer_severity(path, ChangeType.REMOVED, value, None),
        ))

    for raw_path, change in dd.get("values_changed", {}).items():
        path = _normalize_path(str(raw_path))
        before = change.get("old_value")
        after = change.get("new_value")
        items.append(DiffItem(
            path=path,
            change_type=ChangeType.MODIFIED,
            before=before,
            after=after,
            severity=_infer_severity(path, ChangeType.MODIFIED, before, after),
        ))

    for raw_path, change in dd.get("type_changes", {}).items():
        path = _normalize_path(str(raw_path))
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


# ---------------------------------------------------------------------------
# Rich 输出（复用 drift-detector 的 formatter 逻辑）
# ---------------------------------------------------------------------------

_CHANGE_COLORS = {
    ChangeType.ADDED: "green",
    ChangeType.REMOVED: "red",
    ChangeType.MODIFIED: "yellow",
    ChangeType.TYPE_CHANGED: "bright_red",
}

_SEVERITY_COLORS = {
    Severity.BREAKING: "red",
    Severity.NON_BREAKING: "yellow",
    Severity.INFO: "dim",
}

_SEVERITY_LABELS = {
    Severity.BREAKING: "BREAKING",
    Severity.NON_BREAKING: "non-breaking",
    Severity.INFO: "info",
}


def _format_diff_item(item: DiffItem) -> Text:
    color = _CHANGE_COLORS[item.change_type]
    sev_color = _SEVERITY_COLORS[item.severity]
    sev_label = _SEVERITY_LABELS[item.severity]

    t = Text()
    t.append(f"{item.symbol} ", style=f"bold {color}")
    t.append(item.path, style="bold")
    t.append(f"  [{sev_label}]", style=sev_color)

    if item.change_type == ChangeType.ADDED:
        t.append(f"\n  + {json.dumps(item.after, ensure_ascii=False)}", style=color)
    elif item.change_type == ChangeType.REMOVED:
        t.append(f"\n  - {json.dumps(item.before, ensure_ascii=False)}", style=color)
    elif item.change_type in (ChangeType.MODIFIED, ChangeType.TYPE_CHANGED):
        t.append(f"\n  - {json.dumps(item.before, ensure_ascii=False)}", style="red")
        t.append(f"\n  + {json.dumps(item.after, ensure_ascii=False)}", style="green")

    return t


def print_report(report: CompareReport, console: Console | None = None) -> None:
    """打印 CompareReport 到终端（git diff 风格）"""
    if console is None:
        console = Console()

    title = (
        f"[bold]{report.endpoint}[/bold]  "
        f"vendor=[cyan]{report.vendor}[/cyan]  "
        f"model=[cyan]{report.model}[/cyan]  "
        f"prompt=[magenta]{report.prompt_name}[/magenta]"
    )
    time_info = f"captured: {report.captured_at}"

    # 错误情况
    if report.has_errors:
        error_lines = []
        if report.official_error:
            error_lines.append(f"[red]official ({report.official_status}): {report.official_error}[/red]")
        if report.bella_error:
            error_lines.append(f"[red]bella ({report.bella_status}): {report.bella_error}[/red]")
        console.print(Panel(
            "\n".join(error_lines) + f"\n{time_info}",
            title=title,
            border_style="red",
        ))
        return

    if not report.has_changes:
        console.print(Panel(
            f"[green]✓ No structural differences[/green]\n{time_info}",
            title=title,
            border_style="green",
        ))
        return

    # 统计摘要
    added = sum(1 for d in report.diffs if d.change_type == ChangeType.ADDED)
    removed = sum(1 for d in report.diffs if d.change_type == ChangeType.REMOVED)
    modified = sum(1 for d in report.diffs if d.change_type in (ChangeType.MODIFIED, ChangeType.TYPE_CHANGED))
    breaking = report.breaking_count

    summary_parts = []
    if added:
        summary_parts.append(f"[green]+{added} added[/green]")
    if removed:
        summary_parts.append(f"[red]-{removed} removed[/red]")
    if modified:
        summary_parts.append(f"[yellow]~{modified} modified[/yellow]")
    if breaking:
        summary_parts.append(f"[bold red]⚠ {breaking} BREAKING[/bold red]")
    summary_line = "  ".join(summary_parts)

    # 按 severity 排序
    sorted_diffs = sorted(report.diffs, key=lambda d: (d.severity.value, d.path))

    content = StringIO()
    sub_console = Console(file=content, highlight=False)
    sub_console.print(f"official HTTP {report.official_status}  vs  bella HTTP {report.bella_status}")
    sub_console.print(f"{summary_line}\n{time_info}\n")

    for item in sorted_diffs:
        sub_console.print(_format_diff_item(item))
        sub_console.print()

    border_style = "red" if breaking else "yellow"
    console.print(Panel(content.getvalue(), title=title, border_style=border_style))


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

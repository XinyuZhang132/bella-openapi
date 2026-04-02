"""
git diff 风格格式化输出（使用 rich 库）
"""
from __future__ import annotations

import json
from io import StringIO

from rich.console import Console
from rich.text import Text
from rich.panel import Panel
from rich.table import Table
from rich import box

from drift_detector.models import DriftReport, DiffItem, ChangeType, Severity


# 颜色映射
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


def format_diff_item(item: DiffItem) -> Text:
    """格式化单个 DiffItem 为 rich Text"""
    color = _CHANGE_COLORS[item.change_type]
    sev_color = _SEVERITY_COLORS[item.severity]
    sev_label = _SEVERITY_LABELS[item.severity]

    t = Text()
    t.append(f"{item.symbol} ", style=f"bold {color}")
    t.append(item.path, style="bold")
    t.append(f"  [{sev_label}]", style=sev_color)

    if item.change_type == ChangeType.ADDED:
        t.append(f"\n  + {json.dumps(item.after, ensure_ascii=False)}", style=f"{color}")
    elif item.change_type == ChangeType.REMOVED:
        t.append(f"\n  - {json.dumps(item.before, ensure_ascii=False)}", style=f"{color}")
    elif item.change_type in (ChangeType.MODIFIED, ChangeType.TYPE_CHANGED):
        t.append(f"\n  - {json.dumps(item.before, ensure_ascii=False)}", style="red")
        t.append(f"\n  + {json.dumps(item.after, ensure_ascii=False)}", style="green")

    return t


def print_report(report: DriftReport, console: Console | None = None) -> None:
    """打印 DriftReport 到终端（git diff 风格）"""
    if console is None:
        console = Console()

    title = f"[bold]{report.vendor}[/bold] / [cyan]{report.endpoint}[/cyan]  [{report.source.value}]"
    time_info = f"baseline: {report.baseline_captured_at}  →  current: {report.current_captured_at}"

    if not report.has_changes:
        console.print(Panel(
            f"[green]✓ No changes detected[/green]\n{time_info}",
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

    # 按 severity 排序：BREAKING 优先
    sorted_diffs = sorted(
        report.diffs,
        key=lambda d: (d.severity.value, d.path),
    )

    content = StringIO()
    sub_console = Console(file=content, highlight=False)
    sub_console.print(f"{summary_line}\n{time_info}\n")

    for item in sorted_diffs:
        sub_console.print(format_diff_item(item))
        sub_console.print()

    border_style = "red" if breaking else "yellow"
    console.print(Panel(content.getvalue(), title=title, border_style=border_style))


def report_to_markdown(report: DriftReport) -> str:
    """将 DriftReport 转换为 Markdown 格式（用于通知）"""
    lines = [
        f"## API Drift: `{report.vendor}` / `{report.endpoint}` [{report.source.value}]",
        "",
        f"- **Baseline**: {report.baseline_captured_at}",
        f"- **Current**: {report.current_captured_at}",
        f"- **Generated**: {report.generated_at}",
        "",
    ]

    if not report.has_changes:
        lines.append("✅ No changes detected.")
        return "\n".join(lines)

    lines.append(f"### Summary: {report.summary}")
    lines.append("")

    if report.breaking_count:
        lines.append(f"> ⚠️ **{report.breaking_count} BREAKING changes detected!**")
        lines.append("")

    # 按 severity 分组
    breaking_items = [d for d in report.diffs if d.severity == Severity.BREAKING]
    other_items = [d for d in report.diffs if d.severity != Severity.BREAKING]

    if breaking_items:
        lines.append("#### 🔴 Breaking Changes")
        lines.append("```diff")
        for item in breaking_items:
            if item.change_type == ChangeType.REMOVED:
                lines.append(f"- {item.path}")
                lines.append(f"-   was: {json.dumps(item.before, ensure_ascii=False)}")
            elif item.change_type == ChangeType.TYPE_CHANGED:
                lines.append(f"! {item.path}")
                lines.append(f"-   {item.before}")
                lines.append(f"+   {item.after}")
        lines.append("```")
        lines.append("")

    if other_items:
        lines.append("#### 🟡 Other Changes")
        lines.append("```diff")
        for item in other_items:
            symbol = item.symbol
            if item.change_type == ChangeType.ADDED:
                lines.append(f"+ {item.path}")
                lines.append(f"+   {json.dumps(item.after, ensure_ascii=False)}")
            elif item.change_type == ChangeType.MODIFIED:
                lines.append(f"~ {item.path}")
                lines.append(f"-   {json.dumps(item.before, ensure_ascii=False)}")
                lines.append(f"+   {json.dumps(item.after, ensure_ascii=False)}")
        lines.append("```")

    return "\n".join(lines)

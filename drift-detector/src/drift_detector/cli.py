"""
CLI 入口：drift-detector 命令行工具
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table
from rich import box

from drift_detector.config import load_config
from drift_detector.models import SnapshotSource, Snapshot
from drift_detector.snapshotter.api_snapshotter import ApiSnapshotter
from drift_detector.snapshotter.doc_snapshotter import DocSnapshotter
from drift_detector.snapshotter.base import BaseSnapshotter
from drift_detector.differ.engine import DiffEngine
from drift_detector.differ.formatter import print_report, report_to_markdown

console = Console()


def _get_config_and_snapshots_dir(ctx_obj: dict) -> tuple:
    config_dir = ctx_obj.get("config_dir", Path("config"))
    snapshots_dir = ctx_obj.get("snapshots_dir", Path("snapshots"))
    cfg = load_config(
        vendors_path=Path(config_dir) / "vendors.yaml",
        probes_path=Path(config_dir) / "probes.yaml",
        snapshots_dir=Path(snapshots_dir),
    )
    return cfg, Path(snapshots_dir)


@click.group()
@click.option("--config-dir", default="config", show_default=True, help="配置目录路径")
@click.option("--snapshots-dir", default="snapshots", show_default=True, help="快照存储目录")
@click.pass_context
def main(ctx: click.Context, config_dir: str, snapshots_dir: str):
    """AI vendor API drift detection tool for bella-openapi"""
    ctx.ensure_object(dict)
    ctx.obj["config_dir"] = config_dir
    ctx.obj["snapshots_dir"] = snapshots_dir


@main.command()
@click.option("--vendor", "-v", default=None, help="厂商名称（不指定则处理所有启用的厂商）")
@click.option("--endpoint", "-e", default=None, help="接口名称（不指定则处理所有配置的接口）")
@click.option("--source", "-s",
              type=click.Choice(["api", "doc", "both"]),
              default="api",
              show_default=True,
              help="快照来源：api（实际响应）/ doc（官方文档）/ both")
@click.pass_obj
def snapshot(obj: dict, vendor: str | None, endpoint: str | None, source: str):
    """采集 API 快照"""
    cfg, _ = _get_config_and_snapshots_dir(obj)

    vendors_to_process = [vendor] if vendor else [
        k for k, v in cfg.vendors.items() if v.enabled
    ]

    sources = []
    if source in ("api", "both"):
        sources.append(SnapshotSource.API)
    if source in ("doc", "both"):
        sources.append(SnapshotSource.DOC)

    api_snapper = ApiSnapshotter(cfg)
    doc_snapper = DocSnapshotter(cfg)

    results: list[tuple[str, str, str, bool, str]] = []  # vendor, ep, source, ok, msg

    for v in vendors_to_process:
        vendor_cfg = cfg.vendors.get(v)
        if not vendor_cfg:
            console.print(f"[red]Unknown vendor: {v}[/red]")
            continue

        endpoints = [endpoint] if endpoint else [ep.name for ep in vendor_cfg.endpoints]

        for ep_name in endpoints:
            for src in sources:
                snapper: BaseSnapshotter = api_snapper if src == SnapshotSource.API else doc_snapper
                try:
                    snap = snapper.capture(v, ep_name)
                    if snap.error:
                        results.append((v, ep_name, src.value, False, snap.error))
                    else:
                        saved_path = snapper.save_snapshot(snap)
                        results.append((v, ep_name, src.value, True, str(saved_path)))
                except Exception as e:
                    results.append((v, ep_name, src.value, False, str(e)))

    # 打印结果表格
    table = Table(title="Snapshot Results", box=box.ROUNDED)
    table.add_column("Vendor", style="cyan")
    table.add_column("Endpoint", style="blue")
    table.add_column("Source")
    table.add_column("Status")
    table.add_column("Path/Error", max_width=60)

    for v, ep, src, ok, msg in results:
        status = "[green]✓ OK[/green]" if ok else "[red]✗ FAIL[/red]"
        table.add_row(v, ep, src, status, msg)

    console.print(table)


@main.command()
@click.option("--vendor", "-v", required=True, help="厂商名称")
@click.option("--endpoint", "-e", required=True, help="接口名称")
@click.option("--source", "-s",
              type=click.Choice(["api", "doc"]),
              default="api",
              show_default=True,
              help="快照来源")
@click.option("--baseline", default=None, help="基准快照路径（不指定则用倒数第二个）")
@click.option("--current", default=None, help="当前快照路径（不指定则用最新的）")
@click.option("--notify-feishu", default=None, envvar="FEISHU_WEBHOOK_URL",
              help="飞书 Webhook URL（有变更时发送通知）")
@click.option("--notify-slack", default=None, envvar="SLACK_WEBHOOK_URL",
              help="Slack Webhook URL")
@click.option("--report-file", default=None, help="输出报告文件路径（JSON）")
@click.pass_obj
def diff(
    obj: dict,
    vendor: str,
    endpoint: str,
    source: str,
    baseline: str | None,
    current: str | None,
    notify_feishu: str | None,
    notify_slack: str | None,
    report_file: str | None,
):
    """对比两个快照，展示 API 变更"""
    cfg, _ = _get_config_and_snapshots_dir(obj)
    src = SnapshotSource(source)
    api_snapper = ApiSnapshotter(cfg)

    # 加载快照
    if baseline:
        baseline_snap = Snapshot.load(Path(baseline))
    else:
        baseline_snap = api_snapper.load_previous(vendor, endpoint, src)
        if not baseline_snap:
            console.print(f"[yellow]No baseline snapshot found for {vendor}/{endpoint} [{source}].[/yellow]")
            console.print("Run [bold]drift-detector snapshot[/bold] at least twice to compare.")
            sys.exit(1)

    if current:
        current_snap = Snapshot.load(Path(current))
    else:
        current_snap = api_snapper.load_latest(vendor, endpoint, src)
        if not current_snap:
            console.print(f"[yellow]No current snapshot found for {vendor}/{endpoint} [{source}].[/yellow]")
            console.print("Run [bold]drift-detector snapshot[/bold] first.")
            sys.exit(1)

    # 执行 diff
    engine = DiffEngine(ignore_fields=cfg.ignore_fields)
    report = engine.compare(baseline_snap, current_snap)

    # 打印到终端
    print_report(report, console)

    # 保存报告文件
    if report_file:
        Path(report_file).write_text(
            __import__("json").dumps(report.to_dict(), ensure_ascii=False, indent=2)
        )
        console.print(f"[dim]Report saved to: {report_file}[/dim]")

    # 发送通知
    if notify_feishu and report.has_changes:
        from drift_detector.notifier.feishu import send_feishu
        ok = send_feishu(notify_feishu, report)
        console.print(f"[dim]Feishu notification: {'✓ sent' if ok else '✗ failed'}[/dim]")

    if notify_slack and report.has_changes:
        from drift_detector.notifier.slack import send_slack
        ok = send_slack(notify_slack, report)
        console.print(f"[dim]Slack notification: {'✓ sent' if ok else '✗ failed'}[/dim]")

    # 有破坏性变更时返回非零退出码
    if report.breaking_count:
        sys.exit(2)


@main.command()
@click.option("--vendor", "-v", default=None, help="厂商名称（不指定则处理所有）")
@click.option("--endpoint", "-e", default=None, help="接口名称（不指定则处理所有）")
@click.option("--source", "-s",
              type=click.Choice(["api", "doc", "both"]),
              default="api",
              show_default=True)
@click.option("--notify-feishu", default=None, envvar="FEISHU_WEBHOOK_URL")
@click.option("--notify-slack", default=None, envvar="SLACK_WEBHOOK_URL")
@click.pass_context
def watch(
    ctx: click.Context,
    vendor: str | None,
    endpoint: str | None,
    source: str,
    notify_feishu: str | None,
    notify_slack: str | None,
):
    """一次性执行：采集 + 对比 + 通知（适合 cron 调度）"""
    obj = ctx.obj
    cfg, _ = _get_config_and_snapshots_dir(obj)

    vendors_to_process = [vendor] if vendor else [
        k for k, v in cfg.vendors.items() if v.enabled
    ]
    sources_map = {
        "api": [SnapshotSource.API],
        "doc": [SnapshotSource.DOC],
        "both": [SnapshotSource.API, SnapshotSource.DOC],
    }
    sources = sources_map[source]

    api_snapper = ApiSnapshotter(cfg)
    doc_snapper = DocSnapshotter(cfg)
    engine = DiffEngine(ignore_fields=cfg.ignore_fields)

    has_breaking = False

    for v in vendors_to_process:
        vendor_cfg = cfg.vendors.get(v)
        if not vendor_cfg:
            continue
        endpoints = [endpoint] if endpoint else [ep.name for ep in vendor_cfg.endpoints]

        for ep_name in endpoints:
            for src in sources:
                snapper = api_snapper if src == SnapshotSource.API else doc_snapper

                # 获取上一个快照作为基准
                baseline_snap = snapper.load_latest(v, ep_name, src)

                # 采集新快照
                try:
                    new_snap = snapper.capture(v, ep_name)
                    snapper.save_snapshot(new_snap)
                except Exception as e:
                    console.print(f"[red]Failed to capture {v}/{ep_name} [{src.value}]: {e}[/red]")
                    continue

                if baseline_snap is None:
                    console.print(f"[dim]First snapshot for {v}/{ep_name} [{src.value}] — no diff yet.[/dim]")
                    continue

                # 计算 diff
                report = engine.compare(baseline_snap, new_snap)
                print_report(report, console)

                if report.has_changes:
                    if notify_feishu:
                        from drift_detector.notifier.feishu import send_feishu
                        send_feishu(notify_feishu, report)
                    if notify_slack:
                        from drift_detector.notifier.slack import send_slack
                        send_slack(notify_slack, report)

                if report.breaking_count:
                    has_breaking = True

    if has_breaking:
        sys.exit(2)


@main.command()
@click.pass_obj
def list_vendors(obj: dict):
    """列出所有配置的厂商及状态"""
    cfg, _ = _get_config_and_snapshots_dir(obj)

    table = Table(title="Configured Vendors", box=box.ROUNDED)
    table.add_column("Vendor", style="cyan")
    table.add_column("Display Name")
    table.add_column("Enabled")
    table.add_column("Doc Format")
    table.add_column("Endpoints")

    for name, v in cfg.vendors.items():
        enabled_str = "[green]✓[/green]" if v.enabled else "[dim]✗[/dim]"
        ep_list = ", ".join(ep.name for ep in v.endpoints)
        table.add_row(name, v.display_name, enabled_str, v.doc_spec_format, ep_list)

    console.print(table)


if __name__ == "__main__":
    main()

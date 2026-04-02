"""
CLI 入口：api-diff run / list-prompts / list-models / list-vendors
"""
from __future__ import annotations

import sys
from typing import Any

import click
from rich.console import Console
from rich.table import Table
from rich import box

from api_diff.config import (
    load_endpoints,
    load_models,
    load_prompts,
    find_vendor_models,
)
from api_diff.extractor import extract_structure
from api_diff.requester import post_raw
from api_diff.reporter import (
    CompareReport,
    diff_dicts,
    print_report,
    now_iso,
)


console = Console()


@click.group()
def main():
    """api-diff：对比官方 AI 厂商 API 与 bella-openapi 网关的响应结构差异"""


@main.command("list-prompts")
def list_prompts():
    """列出所有可用的 prompt 场景"""
    prompts = load_prompts()
    table = Table(title="Available Prompts", box=box.SIMPLE_HEAVY)
    table.add_column("Name", style="cyan bold")
    table.add_column("Description")
    table.add_column("Endpoint Types", style="dim")

    for name, p in prompts.items():
        ep_types = ", ".join(p.payloads.keys())
        table.add_row(name, p.description, ep_types)

    console.print(table)


@main.command("list-models")
def list_models():
    """列出所有配置的模型"""
    models = load_models()
    table = Table(title="Configured Models", box=box.SIMPLE_HEAVY)
    table.add_column("Vendor", style="cyan bold")
    table.add_column("Endpoint Type", style="green")
    table.add_column("Model ID")

    for vendor, ep_map in models.items():
        rows = [
            (ep_type, model_id)
            for ep_type, model_ids in ep_map.items()
            for model_id in model_ids
        ]
        for i, (ep_type, model_id) in enumerate(rows):
            table.add_row(vendor if i == 0 else "", ep_type, model_id)

    console.print(table)


@main.command("list-vendors")
@click.option("--endpoint", "-e", default=None, help="只显示指定 endpoint 类型下的供应商")
def list_vendors(endpoint: str | None):
    """列出所有配置的供应商及其官方 API 地址"""
    endpoints = load_endpoints()
    table = Table(title="Configured Vendors", box=box.SIMPLE_HEAVY)
    table.add_column("Endpoint Type", style="green")
    table.add_column("Vendor", style="cyan bold")
    table.add_column("URL")
    table.add_column("Auth Env", style="dim")

    for ep_type, ep_cfg in endpoints.items():
        if endpoint and ep_type != endpoint:
            continue
        for i, (vendor_name, vcfg) in enumerate(ep_cfg.vendors.items()):
            url_display = vcfg.url if vcfg.url else "[dim](未配置)[/dim]"
            table.add_row(ep_type if i == 0 else "", vendor_name, url_display, vcfg.auth_env)

    console.print(table)


@main.command("run")
@click.option("--endpoint", "-e", required=True, help="Endpoint 类型，如 chat_completions / messages")
@click.option("--vendor", "-v", default=None, help="供应商名称，如 openai / anthropic / glm；不指定时跑所有已配置供应商")
@click.option("--prompt", "-p", required=True, help="Prompt 名称，如 thinking / image / reading；或 all 跑全部")
@click.option("--model", "-m", default=None, help="模型 ID；不指定时跑该 vendor+endpoint 下所有配置模型")
@click.option("--timeout", default=60.0, show_default=True, help="请求超时秒数")
def run(endpoint: str, vendor: str | None, prompt: str, model: str | None, timeout: float):
    """
    对同一 prompt，向指定供应商的官方 API 和 bella-openapi 各发一次请求，对比响应结构差异。

    示例：\n
      api-diff run -e chat_completions -v openai -p thinking -m gpt-4o-mini\n
      api-diff run -e messages -v anthropic -p thinking -m claude-haiku-4-5-20251001\n
      api-diff run -e chat_completions -v openai -p all\n
      api-diff run -e chat_completions -p thinking   # 跑所有供应商
    """
    endpoints = load_endpoints()
    models = load_models()
    prompts = load_prompts()

    # 验证 endpoint
    if endpoint not in endpoints:
        console.print(f"[red]Unknown endpoint: {endpoint}[/red]")
        console.print(f"Available: {', '.join(endpoints.keys())}")
        sys.exit(1)

    ep_cfg = endpoints[endpoint]

    # 验证 vendor（如果指定）
    if vendor and vendor not in ep_cfg.vendors:
        console.print(f"[red]Unknown vendor '{vendor}' for endpoint '{endpoint}'[/red]")
        console.print(f"Available: {', '.join(ep_cfg.vendors.keys())}")
        sys.exit(1)

    # 展开 prompt
    if prompt == "all":
        prompt_names = list(prompts.keys())
    else:
        if prompt not in prompts:
            console.print(f"[red]Unknown prompt: {prompt}[/red]")
            console.print(f"Available: {', '.join(prompts.keys())}")
            sys.exit(1)
        prompt_names = [prompt]

    # 展开 (vendor, model_id) 组合
    if model is not None:
        # 指定了 model，vendor 必须同时指定
        if not vendor:
            console.print("[red]--model 需要同时指定 --vendor[/red]")
            sys.exit(1)
        run_pairs = [(vendor, model)]
    else:
        run_pairs = find_vendor_models(models, endpoint, vendor)
        if not run_pairs:
            scope = f"vendor={vendor}, " if vendor else ""
            console.print(f"[red]No models configured for {scope}endpoint={endpoint}[/red]")
            sys.exit(1)

    # 过滤掉 url 未配置的 vendor
    skipped = [v for v, _ in run_pairs if not ep_cfg.vendors.get(v, None) or not ep_cfg.vendors[v].url]
    run_pairs = [(v, m) for v, m in run_pairs if ep_cfg.vendors.get(v) and ep_cfg.vendors[v].url]
    if skipped:
        console.print(f"[yellow]Skipping vendors with no URL configured: {', '.join(set(skipped))}[/yellow]")
    if not run_pairs:
        console.print("[red]No runnable vendor+model pairs remaining.[/red]")
        sys.exit(1)

    # 逐组合跑
    for prompt_name in prompt_names:
        prompt_cfg = prompts[prompt_name]
        if endpoint not in prompt_cfg.payloads:
            console.print(
                f"[yellow]Prompt '{prompt_name}' has no payload for endpoint '{endpoint}', skipping.[/yellow]"
            )
            continue

        base_payload: dict[str, Any] = dict(prompt_cfg.payloads[endpoint])

        for vendor_name, model_id in run_pairs:
            vendor_cfg = ep_cfg.vendors[vendor_name]
            payload = {**base_payload, "model": model_id}

            console.print(
                f"\n[dim]→ vendor=[cyan]{vendor_name}[/cyan] "
                f"endpoint=[cyan]{endpoint}[/cyan] "
                f"model=[cyan]{model_id}[/cyan] "
                f"prompt=[magenta]{prompt_name}[/magenta][/dim]"
            )

            # 官方端
            official_key = vendor_cfg.api_key
            if not official_key:
                official_status = 0
                official_body: dict = {"error": f"Missing env var: {vendor_cfg.auth_env}"}
            else:
                official_status, official_body = post_raw(
                    url=vendor_cfg.url,
                    api_key=official_key,
                    payload=payload,
                    extra_headers=vendor_cfg.extra_headers or None,
                    timeout=timeout,
                )

            # bella 端
            bella_key = ep_cfg.bella.api_key
            if not bella_key:
                bella_status = 0
                bella_body: dict = {"error": f"Missing env var: {ep_cfg.bella.auth_env}"}
            else:
                bella_status, bella_body = post_raw(
                    url=ep_cfg.bella.url,
                    api_key=bella_key,
                    payload=payload,
                    extra_headers=ep_cfg.bella.extra_headers or None,
                    timeout=timeout,
                )

            # 提取错误
            official_error = ""
            bella_error = ""
            if official_status != 200:
                official_error = official_body.get("error") or str(official_body)
            if bella_status != 200:
                bella_error = bella_body.get("error") or str(bella_body)

            # 提取结构并对比
            diffs = []
            if not official_error and not bella_error:
                official_structure = extract_structure(official_body)
                bella_structure = extract_structure(bella_body)
                diffs = diff_dicts(official_structure, bella_structure)

            report = CompareReport(
                endpoint=endpoint,
                vendor=vendor_name,
                model=model_id,
                prompt_name=prompt_name,
                official_status=official_status,
                bella_status=bella_status,
                captured_at=now_iso(),
                diffs=diffs,
                official_error=official_error,
                bella_error=bella_error,
            )
            print_report(report, console=console)

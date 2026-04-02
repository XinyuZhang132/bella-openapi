"""
飞书 Webhook 通知
"""
from __future__ import annotations

import httpx

from drift_detector.models import DriftReport
from drift_detector.differ.formatter import report_to_markdown


def send_feishu(webhook_url: str, report: DriftReport) -> bool:
    """
    发送飞书卡片消息。
    仅在有变更时发送（无变更则跳过）。
    返回是否发送成功。
    """
    if not report.has_changes:
        return True  # 无变更，不发送

    md_text = report_to_markdown(report)
    color = "red" if report.breaking_count else "yellow"

    # 飞书交互卡片消息（card format）
    payload = {
        "msg_type": "interactive",
        "card": {
            "header": {
                "title": {
                    "tag": "plain_text",
                    "content": f"🚨 API Drift: {report.vendor}/{report.endpoint}",
                },
                "template": color,
            },
            "elements": [
                {
                    "tag": "markdown",
                    "content": md_text[:3000],  # 飞书卡片有字符限制
                }
            ],
        },
    }

    try:
        with httpx.Client(timeout=10) as client:
            resp = client.post(webhook_url, json=payload)
            resp.raise_for_status()
            result = resp.json()
            return result.get("StatusCode") == 0 or result.get("code") == 0
    except Exception as e:
        print(f"[feishu] Failed to send notification: {e}")
        return False


def send_feishu_text(webhook_url: str, text: str) -> bool:
    """发送简单文本消息到飞书"""
    payload = {
        "msg_type": "text",
        "content": {"text": text},
    }
    try:
        with httpx.Client(timeout=10) as client:
            resp = client.post(webhook_url, json=payload)
            resp.raise_for_status()
            return True
    except Exception:
        return False

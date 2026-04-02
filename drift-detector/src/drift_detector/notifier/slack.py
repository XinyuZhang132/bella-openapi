"""
Slack Webhook 通知
"""
from __future__ import annotations

import httpx

from drift_detector.models import DriftReport
from drift_detector.differ.formatter import report_to_markdown


def send_slack(webhook_url: str, report: DriftReport) -> bool:
    """
    发送 Slack Block Kit 消息。
    仅在有变更时发送。
    """
    if not report.has_changes:
        return True

    md_text = report_to_markdown(report)
    icon = "🚨" if report.breaking_count else "⚠️"

    payload = {
        "text": f"{icon} API Drift detected: {report.vendor}/{report.endpoint}",
        "blocks": [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"{icon} API Drift: {report.vendor}/{report.endpoint}",
                },
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": md_text[:3000],
                },
            },
        ],
    }

    try:
        with httpx.Client(timeout=10) as client:
            resp = client.post(webhook_url, json=payload)
            resp.raise_for_status()
            return resp.text == "ok"
    except Exception as e:
        print(f"[slack] Failed to send notification: {e}")
        return False

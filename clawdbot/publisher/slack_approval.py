"""
ClawdBot Slack Approval — Send interactive messages to Slack for HITL review.

Sends drafts to a designated Slack channel with Block Kit UI containing
Approve, Reject, and Edit buttons. These buttons trigger webhooks
handled by webhook_receiver.py.

Usage:
    from slack_approval import send_approval_request
    send_approval_request("/data/drafts/2026-01-15_abc123.json")
"""

import json
import os
import sys
import logging
from pathlib import Path
from typing import Optional

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

# ── Logging ──────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [SLACK] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("slack_approval")

# ── Configuration ────────────────────────────────────
SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN", "")
SLACK_CHANNEL = os.getenv("SLACK_APPROVAL_CHANNEL", "#clawdbot-approvals")

client = WebClient(token=SLACK_BOT_TOKEN) if SLACK_BOT_TOKEN else None


def send_approval_request(draft_file: str | Path) -> Optional[str]:
    """
    Send a draft to Slack with interactive Approve/Reject/Edit buttons.

    Args:
        draft_file: Path to the draft JSON file

    Returns:
        Message timestamp (ts) for tracking, or None on failure
    """
    draft_path = Path(draft_file)

    if not draft_path.exists():
        log.error(f"Draft file not found: {draft_path}")
        return None

    with open(draft_path) as f:
        draft = json.load(f)

    draft_text = draft.get("text", "")
    news_source = draft.get("news_source", "N/A")
    created_at = draft.get("created_at", "N/A")
    word_count = draft.get("word_count", len(draft_text.split()))
    model = draft.get("model", "N/A")
    attempt = draft.get("attempt", "N/A")

    if not client:
        log.warning("Slack client not configured — printing draft to console")
        print("\n" + "=" * 60)
        print("📝 DRAFT FOR APPROVAL (Slack not configured)")
        print("=" * 60)
        print(draft_text)
        print(f"\nSource: {news_source}")
        print(f"Words: {word_count} | Model: {model} | Attempt: {attempt}")
        print("=" * 60)
        return None

    try:
        # Truncate draft for Slack display (3000 char limit for section blocks)
        display_text = draft_text[:2800] + ("..." if len(draft_text) > 2800 else "")

        response = client.chat_postMessage(
            channel=SLACK_CHANNEL,
            text=f"New ClawdBot draft ready for review ({word_count} words)",
            blocks=[
                # ── Header ───────────────────────────
                {
                    "type": "header",
                    "text": {
                        "type": "plain_text",
                        "text": "📝 New ClawdBot Draft Ready for Review",
                    },
                },
                # ── Divider ──────────────────────────
                {"type": "divider"},
                # ── Draft Text ───────────────────────
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*Draft Post:*\n\n{display_text}",
                    },
                },
                # ── Divider ──────────────────────────
                {"type": "divider"},
                # ── Metadata ─────────────────────────
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "mrkdwn",
                            "text": f"📰 *Source:* {news_source}",
                        },
                        {
                            "type": "mrkdwn",
                            "text": f"🕐 *Generated:* {created_at}",
                        },
                        {
                            "type": "mrkdwn",
                            "text": f"📊 *Words:* {word_count} | *Model:* {model} | *Attempt:* {attempt}",
                        },
                    ],
                },
                # ── Action Buttons ───────────────────
                {
                    "type": "actions",
                    "block_id": "approval_actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {
                                "type": "plain_text",
                                "text": "✅ Approve & Post",
                            },
                            "style": "primary",
                            "value": draft_path.name,
                            "action_id": "approve_post",
                            "confirm": {
                                "title": {"type": "plain_text", "text": "Confirm Approval"},
                                "text": {
                                    "type": "plain_text",
                                    "text": "This will post the draft to Twitter and LinkedIn. Are you sure?",
                                },
                                "confirm": {"type": "plain_text", "text": "Yes, Post It"},
                                "deny": {"type": "plain_text", "text": "Wait, Let Me Review"},
                            },
                        },
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "❌ Reject"},
                            "style": "danger",
                            "value": draft_path.name,
                            "action_id": "reject_post",
                        },
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "✏️ Edit & Approve"},
                            "value": draft_path.name,
                            "action_id": "edit_post",
                        },
                    ],
                },
            ],
        )

        message_ts = response["ts"]
        log.info(f"✅ Approval request sent to {SLACK_CHANNEL} (ts: {message_ts})")
        return message_ts

    except SlackApiError as e:
        log.error(f"Failed to send Slack message: {e.response['error']}")
        return None


def notify_posting_result(
    channel: str,
    thread_ts: str,
    success: bool,
    platforms: list[str],
    error: str = "",
):
    """
    Send a follow-up message in the approval thread with posting results.
    """
    if not client:
        return

    if success:
        text = f"✅ *Posted successfully* to: {', '.join(platforms)}"
    else:
        text = f"⚠️ *Posting failed*: {error}"

    try:
        client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text=text,
        )
    except SlackApiError as e:
        log.error(f"Failed to send posting result: {e.response['error']}")


# ── CLI for Testing ──────────────────────────────────
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python slack_approval.py <draft_file_path>")
        sys.exit(1)

    draft_file = sys.argv[1]
    result = send_approval_request(draft_file)

    if result:
        print(f"Approval request sent! Message TS: {result}")
    else:
        print("Failed to send approval request (check logs)")

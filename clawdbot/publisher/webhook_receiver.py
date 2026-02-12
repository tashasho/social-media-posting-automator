"""
ClawdBot Webhook Receiver — Flask app handling Slack interactive actions.

This is the core of the human-in-the-loop system. When the Writer generates
a draft, the Publisher sends it to Slack with Approve/Reject/Edit buttons.
When a human clicks a button, Slack sends a POST to this webhook.

Endpoints:
    POST /slack/actions  — Handle button clicks from Slack Block Kit
    POST /slack/events   — Handle Slack Events API (URL verification)
    GET  /health         — Health check
    GET  /drafts         — List pending drafts (debug endpoint)

Security:
    - All Slack requests are verified using the Signing Secret
    - Draft files are only moved to /data/approved/ on explicit approval
    - All actions are logged with user identity for audit trail
"""

import json
import os
import sys
import hmac
import hashlib
import shutil
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from flask import Flask, request, jsonify, abort
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

# ── Logging ──────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [PUBLISHER] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("publisher")

# ── Configuration ────────────────────────────────────
SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN", "")
SLACK_SIGNING_SECRET = os.getenv("SLACK_SIGNING_SECRET", "")
SLACK_APPROVAL_CHANNEL = os.getenv("SLACK_APPROVAL_CHANNEL", "#clawdbot-approvals")
FLASK_PORT = int(os.getenv("FLASK_PORT", "5000"))

# Paths
DRAFTS_PATH = Path(os.getenv("DRAFTS_PATH", "/data/drafts"))
APPROVED_PATH = Path(os.getenv("APPROVED_PATH", "/data/approved"))

# Ensure directories exist
DRAFTS_PATH.mkdir(parents=True, exist_ok=True)
APPROVED_PATH.mkdir(parents=True, exist_ok=True)

# Initialize Slack client
slack_client = WebClient(token=SLACK_BOT_TOKEN) if SLACK_BOT_TOKEN else None

# ── Flask App ────────────────────────────────────────
app = Flask(__name__)


def verify_slack_signature(req) -> bool:
    """
    Verify that the incoming request is genuinely from Slack
    using the Signing Secret (HMAC-SHA256).

    See: https://api.slack.com/authentication/verifying-requests-from-slack
    """
    if not SLACK_SIGNING_SECRET:
        log.warning("SLACK_SIGNING_SECRET not set — skipping verification (DEV MODE)")
        return True

    timestamp = req.headers.get("X-Slack-Request-Timestamp", "")
    signature = req.headers.get("X-Slack-Signature", "")

    if not timestamp or not signature:
        log.warning("Missing Slack signature headers")
        return False

    # Reject requests older than 5 minutes (replay attack protection)
    try:
        if abs(time.time() - int(timestamp)) > 300:
            log.warning("Request timestamp too old — possible replay attack")
            return False
    except ValueError:
        return False

    # Compute expected signature
    body = req.get_data(as_text=True)
    sig_basestring = f"v0:{timestamp}:{body}"
    expected_sig = (
        "v0="
        + hmac.new(
            SLACK_SIGNING_SECRET.encode(),
            sig_basestring.encode(),
            hashlib.sha256,
        ).hexdigest()
    )

    return hmac.compare_digest(expected_sig, signature)


def load_draft(draft_filename: str) -> Optional[dict]:
    """Safely load a draft file by filename."""
    # Security: prevent path traversal
    safe_name = Path(draft_filename).name
    draft_path = DRAFTS_PATH / safe_name

    if not draft_path.exists():
        log.error(f"Draft not found: {draft_path}")
        return None

    try:
        with open(draft_path) as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        log.error(f"Failed to load draft {safe_name}: {e}")
        return None


def approve_draft(draft_filename: str, approver: str) -> Optional[Path]:
    """
    Move a draft from drafts/ to approved/ and update its status.
    Returns the path to the approved file.
    """
    safe_name = Path(draft_filename).name
    source = DRAFTS_PATH / safe_name
    destination = APPROVED_PATH / safe_name

    if not source.exists():
        log.error(f"Cannot approve — draft not found: {source}")
        return None

    try:
        # Load, update status, write to approved/
        with open(source) as f:
            draft = json.load(f)

        draft["status"] = "approved"
        draft["approved_at"] = datetime.utcnow().isoformat()
        draft["approved_by"] = approver

        with open(destination, "w") as f:
            json.dump(draft, f, indent=2)

        # Remove from drafts/
        source.unlink()

        log.info(f"✅ Draft approved: {safe_name} by {approver}")
        return destination

    except Exception as e:
        log.error(f"Failed to approve draft: {e}")
        return None


def reject_draft(draft_filename: str, rejector: str, reason: str = "") -> bool:
    """Mark a draft as rejected and archive it."""
    safe_name = Path(draft_filename).name
    source = DRAFTS_PATH / safe_name

    if not source.exists():
        log.error(f"Cannot reject — draft not found: {source}")
        return False

    try:
        with open(source) as f:
            draft = json.load(f)

        draft["status"] = "rejected"
        draft["rejected_at"] = datetime.utcnow().isoformat()
        draft["rejected_by"] = rejector
        draft["rejection_reason"] = reason

        # Write back (keep in drafts/ for audit)
        rejected_name = f"REJECTED_{safe_name}"
        with open(DRAFTS_PATH / rejected_name, "w") as f:
            json.dump(draft, f, indent=2)

        # Remove original
        source.unlink()

        log.info(f"❌ Draft rejected: {safe_name} by {rejector}")
        return True

    except Exception as e:
        log.error(f"Failed to reject draft: {e}")
        return False


def edit_draft(draft_filename: str, new_text: str, editor: str) -> bool:
    """Update draft text after human editing."""
    safe_name = Path(draft_filename).name
    draft_path = DRAFTS_PATH / safe_name

    if not draft_path.exists():
        log.error(f"Cannot edit — draft not found: {draft_path}")
        return False

    try:
        with open(draft_path) as f:
            draft = json.load(f)

        # Preserve original text for audit
        if "original_text" not in draft:
            draft["original_text"] = draft["text"]

        draft["text"] = new_text
        draft["edited_at"] = datetime.utcnow().isoformat()
        draft["edited_by"] = editor
        draft["word_count"] = len(new_text.split())

        with open(draft_path, "w") as f:
            json.dump(draft, f, indent=2)

        log.info(f"✏️ Draft edited: {safe_name} by {editor}")
        return True

    except Exception as e:
        log.error(f"Failed to edit draft: {e}")
        return False


def update_slack_message(channel: str, ts: str, text: str, status_emoji: str):
    """Update the original Slack approval message with result."""
    if not slack_client:
        log.warning("Slack client not initialized — skipping message update")
        return

    try:
        slack_client.chat_update(
            channel=channel,
            ts=ts,
            text=f"{status_emoji} {text}",
            blocks=[
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": f"{status_emoji} {text}"},
                }
            ],
        )
    except SlackApiError as e:
        log.error(f"Failed to update Slack message: {e.response['error']}")


# ═══════════════════════════════════════════════════════
# ROUTES
# ═══════════════════════════════════════════════════════


@app.route("/health", methods=["GET"])
def health():
    """Health check endpoint."""
    pending = list(DRAFTS_PATH.glob("*.json"))
    approved = list(APPROVED_PATH.glob("*.json"))
    return jsonify(
        {
            "status": "healthy",
            "timestamp": datetime.utcnow().isoformat(),
            "pending_drafts": len(pending),
            "approved_drafts": len(approved),
        }
    )


@app.route("/drafts", methods=["GET"])
def list_drafts():
    """Debug endpoint: list all pending drafts."""
    drafts = []
    for f in sorted(DRAFTS_PATH.glob("*.json")):
        try:
            with open(f) as fh:
                data = json.load(fh)
            drafts.append(
                {
                    "filename": f.name,
                    "status": data.get("status", "unknown"),
                    "created_at": data.get("created_at", ""),
                    "word_count": data.get("word_count", 0),
                    "preview": data.get("text", "")[:100] + "...",
                }
            )
        except Exception:
            continue
    return jsonify({"drafts": drafts, "count": len(drafts)})


@app.route("/slack/events", methods=["POST"])
def slack_events():
    """
    Handle Slack Events API.
    Required for URL verification during Slack app setup.
    """
    data = request.json

    # URL verification challenge
    if data and data.get("type") == "url_verification":
        return jsonify({"challenge": data["challenge"]})

    return jsonify({"ok": True})


@app.route("/slack/actions", methods=["POST"])
def slack_actions():
    """
    Handle Slack interactive message actions (button clicks).

    Slack sends the payload as form data with a 'payload' key
    containing a JSON string.

    Actions handled:
        - approve_post: Move draft to approved/, trigger social posting
        - reject_post: Mark draft as rejected, archive
        - edit_post: Open modal for inline text editing
        - submit_edit: Handle edited text submission
    """
    # ── Verify Slack Signature ───────────────────────
    if not verify_slack_signature(request):
        log.warning("❌ Invalid Slack signature — rejecting request")
        abort(401)

    # ── Parse Payload ────────────────────────────────
    try:
        # Slack sends payload as form-encoded 'payload' field
        raw_payload = request.form.get("payload")
        if raw_payload:
            payload = json.loads(raw_payload)
        else:
            # Fallback: try JSON body (for testing)
            payload = request.get_json(force=True) or {}
    except (json.JSONDecodeError, TypeError) as e:
        log.error(f"Failed to parse Slack payload: {e}")
        abort(400)

    payload_type = payload.get("type", "")
    log.info(f"Received Slack action: type={payload_type}")

    # ── Handle View Submission (Edit Modal) ──────────
    if payload_type == "view_submission":
        return handle_edit_submission(payload)

    # ── Handle Block Actions (Button Clicks) ─────────
    if payload_type == "block_actions":
        actions = payload.get("actions", [])
        if not actions:
            return jsonify({"ok": True})

        action = actions[0]
        action_id = action.get("action_id", "")
        draft_filename = action.get("value", "")

        # Get user info for audit trail
        user = payload.get("user", {})
        user_name = user.get("username", user.get("name", "unknown"))
        user_id = user.get("id", "unknown")
        approver = f"{user_name} ({user_id})"

        # Channel and message info for updating
        channel = payload.get("channel", {}).get("id", "")
        message_ts = payload.get("message", {}).get("ts", "")

        log.info(f"Action: {action_id} on '{draft_filename}' by {approver}")

        # ── APPROVE ──────────────────────────────────
        if action_id == "approve_post":
            approved_path = approve_draft(draft_filename, approver)
            if approved_path:
                # Trigger social posting
                try:
                    from social_poster import post_to_all_platforms
                    with open(approved_path) as f:
                        draft = json.load(f)
                    post_to_all_platforms(draft)
                except ImportError:
                    log.info("social_poster not available — draft approved but not posted")
                except Exception as e:
                    log.error(f"Posting failed: {e}")

                # Update Slack message
                update_slack_message(
                    channel, message_ts,
                    f"*Approved & posted* by <@{user_id}> ✅",
                    "✅"
                )
                return jsonify({"text": "✅ Draft approved and posted!"})
            else:
                return jsonify({"text": "❌ Failed to approve draft."})

        # ── REJECT ───────────────────────────────────
        elif action_id == "reject_post":
            if reject_draft(draft_filename, approver):
                update_slack_message(
                    channel, message_ts,
                    f"*Rejected* by <@{user_id}> ❌",
                    "❌"
                )
                return jsonify({"text": "❌ Draft rejected."})
            else:
                return jsonify({"text": "❌ Failed to reject draft."})

        # ── EDIT ─────────────────────────────────────
        elif action_id == "edit_post":
            return open_edit_modal(payload, draft_filename)

        else:
            log.warning(f"Unknown action_id: {action_id}")
            return jsonify({"ok": True})

    return jsonify({"ok": True})


def open_edit_modal(payload: dict, draft_filename: str):
    """
    Open a Slack modal dialog for inline text editing.
    The user can modify the draft text before approving.
    """
    if not slack_client:
        return jsonify({"text": "⚠️ Slack client not configured"})

    trigger_id = payload.get("trigger_id", "")
    if not trigger_id:
        return jsonify({"text": "⚠️ No trigger_id available"})

    # Load current draft text
    draft = load_draft(draft_filename)
    current_text = draft.get("text", "") if draft else ""

    try:
        slack_client.views_open(
            trigger_id=trigger_id,
            view={
                "type": "modal",
                "callback_id": "edit_draft_modal",
                "private_metadata": draft_filename,
                "title": {"type": "plain_text", "text": "Edit Draft"},
                "submit": {"type": "plain_text", "text": "Save & Approve"},
                "close": {"type": "plain_text", "text": "Cancel"},
                "blocks": [
                    {
                        "type": "input",
                        "block_id": "draft_text_block",
                        "label": {
                            "type": "plain_text",
                            "text": "Edit the post text below:",
                        },
                        "element": {
                            "type": "plain_text_input",
                            "action_id": "draft_text_input",
                            "multiline": True,
                            "initial_value": current_text,
                        },
                    },
                    {
                        "type": "context",
                        "elements": [
                            {
                                "type": "mrkdwn",
                                "text": f"📎 Draft file: `{draft_filename}`",
                            }
                        ],
                    },
                ],
            },
        )
        return jsonify({"ok": True})

    except SlackApiError as e:
        log.error(f"Failed to open edit modal: {e.response['error']}")
        return jsonify({"text": f"⚠️ Failed to open editor: {e.response['error']}"})


def handle_edit_submission(payload: dict):
    """Handle the modal submission after editing."""
    user = payload.get("user", {})
    user_name = user.get("username", user.get("name", "unknown"))
    user_id = user.get("id", "unknown")
    editor = f"{user_name} ({user_id})"

    # Extract draft filename from private_metadata
    view = payload.get("view", {})
    draft_filename = view.get("private_metadata", "")

    # Extract edited text from form values
    values = view.get("state", {}).get("values", {})
    text_block = values.get("draft_text_block", {})
    new_text = text_block.get("draft_text_input", {}).get("value", "")

    if not draft_filename or not new_text:
        log.error("Edit submission missing data")
        return jsonify({"response_action": "errors", "errors": {
            "draft_text_block": "Text cannot be empty"
        }})

    # Save the edit
    if edit_draft(draft_filename, new_text, editor):
        # Auto-approve after edit
        approved_path = approve_draft(draft_filename, editor)
        if approved_path:
            # Trigger posting
            try:
                from social_poster import post_to_all_platforms
                with open(approved_path) as f:
                    draft = json.load(f)
                post_to_all_platforms(draft)
            except ImportError:
                log.info("social_poster not available")
            except Exception as e:
                log.error(f"Posting failed after edit: {e}")

            log.info(f"✅ Draft edited and approved by {editor}")

    return jsonify({"response_action": "clear"})


# ═══════════════════════════════════════════════════════
# STARTUP
# ═══════════════════════════════════════════════════════

if __name__ == "__main__":
    log.info("=" * 60)
    log.info("ClawdBot Publisher — Slack Webhook Receiver")
    log.info(f"Listening on port {FLASK_PORT}")
    log.info(f"Drafts:   {DRAFTS_PATH}")
    log.info(f"Approved: {APPROVED_PATH}")
    log.info(f"Channel:  {SLACK_APPROVAL_CHANNEL}")
    log.info(f"Slack:    {'Connected' if slack_client else 'NOT CONFIGURED'}")
    log.info("=" * 60)

    app.run(host="0.0.0.0", port=FLASK_PORT, debug=False)

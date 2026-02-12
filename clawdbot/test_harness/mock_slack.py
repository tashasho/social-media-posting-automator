"""
ClawdBot Mock Slack Server — Simulates Slack API for local testing.

Provides a lightweight Flask server that mimics Slack's interactive
message API, allowing you to test the webhook_receiver without
a real Slack workspace.

Usage:
    # Start mock Slack server
    python test_harness/mock_slack.py

    # In another terminal, start the publisher
    SLACK_BOT_TOKEN=mock FLASK_PORT=5001 python publisher/webhook_receiver.py
"""

import json
import logging
from datetime import datetime
from flask import Flask, request, jsonify

# ── Logging ──────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [MOCK-SLACK] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("mock_slack")

app = Flask(__name__)

# Store all received messages for inspection
message_store = []


@app.route("/api/chat.postMessage", methods=["POST"])
def mock_post_message():
    """Mock Slack chat.postMessage API."""
    data = request.json or {}

    message = {
        "channel": data.get("channel", "#test"),
        "text": data.get("text", ""),
        "blocks": data.get("blocks", []),
        "ts": str(datetime.utcnow().timestamp()),
        "received_at": datetime.utcnow().isoformat(),
    }

    message_store.append(message)

    log.info(f"📨 Message received for channel: {message['channel']}")
    log.info(f"   Text: {message['text'][:100]}")

    # Print blocks for debugging
    if message["blocks"]:
        for block in message["blocks"]:
            block_type = block.get("type", "unknown")
            if block_type == "section":
                text = block.get("text", {}).get("text", "")[:100]
                log.info(f"   Block [section]: {text}")
            elif block_type == "actions":
                buttons = [e.get("text", {}).get("text", "") for e in block.get("elements", [])]
                log.info(f"   Block [actions]: {', '.join(buttons)}")

    return jsonify({
        "ok": True,
        "channel": message["channel"],
        "ts": message["ts"],
        "message": {
            "text": message["text"],
            "ts": message["ts"],
        },
    })


@app.route("/api/chat.update", methods=["POST"])
def mock_update_message():
    """Mock Slack chat.update API."""
    data = request.json or {}
    log.info(f"📝 Message updated: {data.get('text', '')[:100]}")
    return jsonify({"ok": True})


@app.route("/api/views.open", methods=["POST"])
def mock_views_open():
    """Mock Slack views.open API (modals)."""
    data = request.json or {}
    log.info(f"🪟 Modal opened: {json.dumps(data.get('view', {}).get('title', {}))}")
    return jsonify({"ok": True})


@app.route("/messages", methods=["GET"])
def list_messages():
    """Debug endpoint: list all received messages."""
    return jsonify({
        "messages": message_store,
        "count": len(message_store),
    })


@app.route("/simulate/approve", methods=["POST"])
def simulate_approve():
    """
    Simulate a user clicking the 'Approve' button.
    Sends a mock interactive payload to the webhook_receiver.

    Usage:
        curl -X POST http://localhost:5002/simulate/approve \
          -H "Content-Type: application/json" \
          -d '{"draft_filename": "test_draft.json", "webhook_url": "http://localhost:5000/slack/actions"}'
    """
    data = request.json or {}
    draft_filename = data.get("draft_filename", "test.json")
    webhook_url = data.get("webhook_url", "http://localhost:5000/slack/actions")

    import requests as req

    payload = {
        "type": "block_actions",
        "user": {
            "id": "U_MOCK_USER",
            "username": "test_user",
            "name": "Test User",
        },
        "channel": {"id": "C_MOCK_CHANNEL"},
        "message": {"ts": "1234567890.123456"},
        "trigger_id": "mock_trigger_12345",
        "actions": [
            {
                "action_id": "approve_post",
                "value": draft_filename,
                "type": "button",
            }
        ],
    }

    try:
        resp = req.post(
            webhook_url,
            data={"payload": json.dumps(payload)},
            timeout=10,
        )
        log.info(f"✅ Simulated approval sent: {resp.status_code}")
        return jsonify({
            "ok": True,
            "webhook_response": resp.json() if resp.headers.get("content-type", "").startswith("application/json") else resp.text,
        })
    except Exception as e:
        log.error(f"Failed to simulate approval: {e}")
        return jsonify({"ok": False, "error": str(e)})


@app.route("/simulate/reject", methods=["POST"])
def simulate_reject():
    """Simulate a user clicking the 'Reject' button."""
    data = request.json or {}
    draft_filename = data.get("draft_filename", "test.json")
    webhook_url = data.get("webhook_url", "http://localhost:5000/slack/actions")

    import requests as req

    payload = {
        "type": "block_actions",
        "user": {"id": "U_MOCK_USER", "username": "test_user"},
        "channel": {"id": "C_MOCK_CHANNEL"},
        "message": {"ts": "1234567890.123456"},
        "actions": [
            {
                "action_id": "reject_post",
                "value": draft_filename,
                "type": "button",
            }
        ],
    }

    try:
        resp = req.post(
            webhook_url,
            data={"payload": json.dumps(payload)},
            timeout=10,
        )
        return jsonify({"ok": True, "status": resp.status_code})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "healthy",
        "service": "mock-slack",
        "messages_received": len(message_store),
    })


if __name__ == "__main__":
    port = 5002
    log.info(f"🧪 Mock Slack server starting on port {port}")
    log.info(f"   Messages endpoint: http://localhost:{port}/messages")
    log.info(f"   Simulate approve: POST http://localhost:{port}/simulate/approve")
    log.info(f"   Simulate reject:  POST http://localhost:{port}/simulate/reject")
    app.run(host="0.0.0.0", port=port, debug=True)

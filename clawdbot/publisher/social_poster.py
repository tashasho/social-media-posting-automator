"""
ClawdBot Social Poster — Post approved drafts to Twitter/X and LinkedIn.

Called by the webhook_receiver after a human approves a draft via Slack.
This module has the ONLY social media API keys in the entire system.

Supported platforms:
    - Twitter/X (via tweepy v2 API)
    - LinkedIn (via Marketing API REST)
"""

import json
import os
import logging
from datetime import datetime
from typing import Optional

import tweepy
import requests

# ── Logging ──────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [POSTER] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("social_poster")


# ═══════════════════════════════════════════════════════
# TWITTER / X
# ═══════════════════════════════════════════════════════


def get_twitter_client() -> Optional[tweepy.Client]:
    """Initialize Twitter API v2 client."""
    api_key = os.getenv("TWITTER_API_KEY", "")
    api_secret = os.getenv("TWITTER_API_SECRET", "")
    access_token = os.getenv("TWITTER_ACCESS_TOKEN", "")
    access_secret = os.getenv("TWITTER_ACCESS_SECRET", "")

    if not all([api_key, api_secret, access_token, access_secret]):
        log.warning("Twitter credentials not fully configured")
        return None

    try:
        client = tweepy.Client(
            consumer_key=api_key,
            consumer_secret=api_secret,
            access_token=access_token,
            access_token_secret=access_secret,
        )
        return client
    except Exception as e:
        log.error(f"Failed to initialize Twitter client: {e}")
        return None


def post_to_twitter(text: str) -> Optional[str]:
    """
    Post a tweet. Truncates to 280 chars if needed (adds ellipsis).

    Returns:
        Tweet ID on success, None on failure.
    """
    client = get_twitter_client()
    if not client:
        log.warning("Twitter client not available — skipping")
        return None

    # Twitter character limit
    if len(text) > 280:
        text = text[:277] + "..."
        log.warning("Tweet truncated to 280 characters")

    try:
        response = client.create_tweet(text=text)
        tweet_id = response.data["id"]
        log.info(f"✅ Posted to Twitter: https://twitter.com/i/status/{tweet_id}")
        return tweet_id
    except tweepy.TweepyException as e:
        log.error(f"❌ Twitter posting failed: {e}")
        return None


# ═══════════════════════════════════════════════════════
# LINKEDIN
# ═══════════════════════════════════════════════════════


def post_to_linkedin(text: str) -> Optional[str]:
    """
    Post to LinkedIn organization page via Marketing API.

    Requires:
        - LINKEDIN_ACCESS_TOKEN (OAuth2 token with w_organization_social scope)
        - LINKEDIN_ORG_ID (Organization URN ID)

    Returns:
        Post URN on success, None on failure.
    """
    access_token = os.getenv("LINKEDIN_ACCESS_TOKEN", "")
    org_id = os.getenv("LINKEDIN_ORG_ID", "")

    if not access_token or not org_id:
        log.warning("LinkedIn credentials not configured — skipping")
        return None

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "X-Restli-Protocol-Version": "2.0.0",
    }

    # LinkedIn UGC Post API
    payload = {
        "author": f"urn:li:organization:{org_id}",
        "lifecycleState": "PUBLISHED",
        "specificContent": {
            "com.linkedin.ugc.ShareContent": {
                "shareCommentary": {"text": text},
                "shareMediaCategory": "NONE",
            }
        },
        "visibility": {
            "com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"
        },
    }

    try:
        response = requests.post(
            "https://api.linkedin.com/v2/ugcPosts",
            headers=headers,
            json=payload,
            timeout=15,
        )
        response.raise_for_status()

        post_id = response.headers.get("X-RestLi-Id", response.json().get("id", "unknown"))
        log.info(f"✅ Posted to LinkedIn: {post_id}")
        return post_id

    except requests.RequestException as e:
        log.error(f"❌ LinkedIn posting failed: {e}")
        if hasattr(e, "response") and e.response is not None:
            log.error(f"   Response: {e.response.text[:300]}")
        return None


# ═══════════════════════════════════════════════════════
# ORCHESTRATOR
# ═══════════════════════════════════════════════════════


def post_to_all_platforms(draft: dict, skip_platforms: list = None) -> dict:
    """
    Post an approved draft to all configured social platforms.

    Args:
        draft: Draft dict with at minimum 'text' key
        skip_platforms: List of platform names to skip (e.g. ['linkedin'])

    Returns:
        Results dict with platform names → post IDs/status
    """
    skip_platforms = [p.lower() for p in (skip_platforms or [])]
    text = draft.get("text", "")
    if not text:
        log.error("Cannot post — draft has no text")
        return {"error": "No text in draft"}

    log.info(f"Posting to all platforms ({len(text)} chars)...")
    if skip_platforms:
        log.info(f"Skipping: {', '.join(skip_platforms)}")
    results = {}

    # ── Twitter ──────────────────────────────────────
    if "twitter" in skip_platforms:
        results["twitter"] = {"success": False, "skipped": True}
        log.info("⏭️  Twitter: skipped")
    else:
        try:
            # For Twitter, we might want a shorter version
            twitter_text = text
            if len(text) > 280:
                # Try to find a natural break point
                sentences = text.split(". ")
                twitter_text = sentences[0] + "."
                for s in sentences[1:]:
                    if len(twitter_text + " " + s + ".") <= 275:
                        twitter_text += " " + s + "."
                    else:
                        break
                if len(twitter_text) > 280:
                    twitter_text = text[:277] + "..."

            tweet_id = post_to_twitter(twitter_text)
            results["twitter"] = {
                "success": bool(tweet_id),
                "post_id": tweet_id,
                "url": f"https://twitter.com/i/status/{tweet_id}" if tweet_id else None,
            }
        except Exception as e:
            results["twitter"] = {"success": False, "error": str(e)}

    # ── LinkedIn ─────────────────────────────────────
    if "linkedin" in skip_platforms:
        results["linkedin"] = {"success": False, "skipped": True}
        log.info("⏭️  LinkedIn: skipped")
    else:
        try:
            linkedin_id = post_to_linkedin(text)
            results["linkedin"] = {
                "success": bool(linkedin_id),
                "post_id": linkedin_id,
            }
        except Exception as e:
            results["linkedin"] = {"success": False, "error": str(e)}

    # ── Summary ──────────────────────────────────────
    successes = [p for p, r in results.items() if r.get("success")]
    failures = [p for p, r in results.items() if not r.get("success") and not r.get("skipped")]

    if successes:
        log.info(f"✅ Posted to: {', '.join(successes)}")
    if failures:
        log.warning(f"⚠️ Failed on: {', '.join(failures)}")

    return results


# ── CLI for Testing ──────────────────────────────────
if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python social_poster.py <approved_draft.json>")
        print("       python social_poster.py --test 'Hello World'")
        sys.exit(1)

    if sys.argv[1] == "--test":
        text = sys.argv[2] if len(sys.argv) > 2 else "ClawdBot test post 🤖"
        results = post_to_all_platforms({"text": text})
        print(json.dumps(results, indent=2))
    else:
        with open(sys.argv[1]) as f:
            draft = json.load(f)
        results = post_to_all_platforms(draft)
        print(json.dumps(results, indent=2))

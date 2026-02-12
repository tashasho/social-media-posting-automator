"""
ClawdBot Apify VC Scraper — Twitter/X content collector for RAG corpus.

Scrapes public tweets from prominent VC accounts using the Apify platform.
Filters for high-quality insights and outputs a structured corpus file
compatible with the Writer's RAG system.

Usage:
    # Via Apify API (requires APIFY_API_TOKEN env var)
    python apify_vc_scraper.py --mode apify --output data/rag/vc_corpus.json

    # Quick test with mock data
    python apify_vc_scraper.py --mode mock --output data/rag/vc_corpus.json
"""

import json
import os
import sys
import time
import argparse
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

import requests

# ── Logging ──────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [VC-SCRAPER] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("vc_scraper")

# ── Target VC Accounts ──────────────────────────────
VC_ACCOUNTS = [
    {"handle": "paulg", "name": "Paul Graham", "firm": "Y Combinator"},
    {"handle": "garrytan", "name": "Garry Tan", "firm": "Y Combinator"},
    {"handle": "jasonlk", "name": "Jason Lemkin", "firm": "SaaStr"},
    {"handle": "sarahtavel", "name": "Sarah Tavel", "firm": "Benchmark"},
    {"handle": "eladgil", "name": "Elad Gil", "firm": "Independent"},
    {"handle": "alexisohanian", "name": "Alexis Ohanian", "firm": "776"},
    {"handle": "naval", "name": "Naval Ravikant", "firm": "AngelList"},
    {"handle": "sama", "name": "Sam Altman", "firm": "OpenAI/YC"},
    {"handle": "benedictevans", "name": "Benedict Evans", "firm": "Independent"},
    {"handle": "andrewchen", "name": "Andrew Chen", "firm": "a16z"},
]

# ── Quality Filters ─────────────────────────────────
# Minimum engagement for inclusion
MIN_LIKES = 50
# Keywords that indicate promotional/low-quality content
PROMO_KEYWORDS = [
    "check out our portfolio",
    "we're hiring",
    "join us at",
    "register now",
    "link in bio",
    "giveaway",
    "discount code",
    "use my referral",
    "sponsored",
]

# Category classification keywords
CATEGORY_KEYWORDS = {
    "founder_advice": [
        "founders", "startup", "building", "PMF", "product-market fit",
        "hiring", "culture", "pivot", "customers", "users",
    ],
    "market_trends": [
        "market", "trend", "growth", "valuation", "IPO", "funding",
        "economy", "bubble", "correction", "cycle",
    ],
    "tech_analysis": [
        "AI", "artificial intelligence", "machine learning", "blockchain",
        "crypto", "SaaS", "cloud", "infrastructure", "API",
    ],
    "fundraising": [
        "raise", "round", "seed", "Series", "investors", "pitch",
        "term sheet", "valuation", "dilution", "cap table",
    ],
    "leadership": [
        "leadership", "management", "CEO", "decision", "strategy",
        "vision", "team", "execution", "discipline",
    ],
}


def classify_category(text: str) -> str:
    """Classify tweet into a category based on keyword matching."""
    text_lower = text.lower()
    scores = {}
    for category, keywords in CATEGORY_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw.lower() in text_lower)
        scores[category] = score

    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "general_insight"


def is_high_quality(tweet: dict) -> bool:
    """
    Filter for high-quality VC content.
    Rejects promotional, low-engagement, and short tweets.
    """
    text = tweet.get("text", "").lower()

    # Reject promotional content
    for promo in PROMO_KEYWORDS:
        if promo.lower() in text:
            return False

    # Reject very short tweets (unlikely to be insightful)
    if len(tweet.get("text", "")) < 50:
        return False

    # Reject retweets
    if tweet.get("text", "").startswith("RT @"):
        return False

    # Engagement threshold
    likes = tweet.get("likeCount", tweet.get("favorites", 0))
    if likes < MIN_LIKES:
        return False

    return True


def scrape_via_apify(accounts: list[dict], tweets_per_account: int = 100) -> list[dict]:
    """
    Scrape tweets using Apify Twitter Scraper actor.
    Requires APIFY_API_TOKEN environment variable.
    """
    token = os.getenv("APIFY_API_TOKEN")
    if not token or token.startswith("your_"):
        log.error("APIFY_API_TOKEN not set. Set it in .env or environment.")
        sys.exit(1)

    all_tweets = []
    actor_id = "apify~twitter-scraper"
    base_url = f"https://api.apify.com/v2/acts/{actor_id}"

    for account in accounts:
        handle = account["handle"]
        log.info(f"🔍 Scraping @{handle} ({account['name']})...")

        # Start the actor run
        run_input = {
            "handles": [handle],
            "tweetsDesired": tweets_per_account,
            "onlyTweets": True,  # Exclude retweets
            "proxyConfig": {"useApifyProxy": True},
        }

        try:
            # Trigger the run
            run_resp = requests.post(
                f"{base_url}/runs?token={token}",
                json=run_input,
                timeout=30,
            )
            run_resp.raise_for_status()
            run_data = run_resp.json()["data"]
            run_id = run_data["id"]
            log.info(f"  Started Apify run: {run_id}")

            # Poll for completion (max 5 minutes per account)
            dataset_id = None
            for _ in range(60):
                time.sleep(5)
                status_resp = requests.get(
                    f"https://api.apify.com/v2/actor-runs/{run_id}?token={token}",
                    timeout=15,
                )
                status_data = status_resp.json()["data"]
                status = status_data["status"]

                if status == "SUCCEEDED":
                    dataset_id = status_data["defaultDatasetId"]
                    break
                elif status in ("FAILED", "ABORTED", "TIMED-OUT"):
                    log.warning(f"  Run {run_id} ended with status: {status}")
                    break

            if not dataset_id:
                log.warning(f"  Skipping @{handle} — no dataset produced.")
                continue

            # Fetch results from dataset
            dataset_resp = requests.get(
                f"https://api.apify.com/v2/datasets/{dataset_id}/items?token={token}&format=json",
                timeout=30,
            )
            dataset_resp.raise_for_status()
            tweets = dataset_resp.json()

            for tweet in tweets:
                tweet["_account"] = account
            all_tweets.extend(tweets)

            log.info(f"  ✅ Got {len(tweets)} tweets from @{handle}")

            # Rate limiting: be respectful
            time.sleep(2)

        except requests.RequestException as e:
            log.error(f"  ❌ Failed to scrape @{handle}: {e}")
            continue

    return all_tweets


def generate_mock_corpus() -> list[dict]:
    """
    Generate a realistic mock corpus for testing without Apify.
    These are inspired by real VC writing patterns (not direct quotes).
    """
    return [
        {
            "text": "The best founders I've met share one trait: they're obsessed with the problem, not the solution. They'll pivot five times before finding product-market fit, and they won't lose sleep over it.",
            "author": "paulg",
            "author_name": "Paul Graham",
            "platform": "twitter",
            "engagement": 1523,
            "category": "founder_advice",
        },
        {
            "text": "We're seeing a fundamental shift from 'growth at all costs' to 'efficient growth.' Unit economics matter again. The best companies never forgot this.",
            "author": "jasonlk",
            "author_name": "Jason Lemkin",
            "platform": "twitter",
            "engagement": 847,
            "category": "market_trends",
        },
        {
            "text": "AI won't replace founders. But founders who use AI will replace those who don't. The leverage from intelligent tools is the biggest step change since cloud computing.",
            "author": "garrytan",
            "author_name": "Garry Tan",
            "platform": "twitter",
            "engagement": 2104,
            "category": "tech_analysis",
        },
        {
            "text": "The hardest thing about building a marketplace is that you need both sides to show up at the same time. The trick? Start with the supply side and give them a reason to stay before demand arrives.",
            "author": "sarahtavel",
            "author_name": "Sarah Tavel",
            "platform": "twitter",
            "engagement": 612,
            "category": "founder_advice",
        },
        {
            "text": "Seed-stage valuations have compressed 30-40% from 2021 peaks. This is healthy. The companies being built right now will be stronger for having raised at rational prices.",
            "author": "eladgil",
            "author_name": "Elad Gil",
            "platform": "twitter",
            "engagement": 934,
            "category": "market_trends",
        },
        {
            "text": "The internet made distribution free. AI is making creation free. The next wave of billion-dollar companies will be built by two-person teams.",
            "author": "alexisohanian",
            "author_name": "Alexis Ohanian",
            "platform": "twitter",
            "engagement": 3201,
            "category": "tech_analysis",
        },
        {
            "text": "Specific knowledge is found by pursuing your genuine curiosity and passion rather than whatever is hot right now. Building on the intersection of your unique skills is an unfair advantage.",
            "author": "naval",
            "author_name": "Naval Ravikant",
            "platform": "twitter",
            "engagement": 4500,
            "category": "leadership",
        },
        {
            "text": "The most underrated founder skill: the ability to write clearly. If you can't explain your product in one sentence, you don't understand it well enough.",
            "author": "paulg",
            "author_name": "Paul Graham",
            "platform": "twitter",
            "engagement": 2890,
            "category": "founder_advice",
        },
        {
            "text": "Enterprise SaaS is entering its third wave: Wave 1 was 'move to cloud.' Wave 2 was 'automate workflows.' Wave 3 is 'AI agents that replace workflows entirely.'",
            "author": "jasonlk",
            "author_name": "Jason Lemkin",
            "platform": "linkedin",
            "engagement": 1200,
            "category": "tech_analysis",
        },
        {
            "text": "90% of fundraising is done before the first meeting. Your warm intro, your traction, your story — the pitch deck is just the vehicle, not the engine.",
            "author": "garrytan",
            "author_name": "Garry Tan",
            "platform": "twitter",
            "engagement": 1750,
            "category": "fundraising",
        },
        {
            "text": "After a decade of investing, I've learned that the best metric for predicting startup success isn't revenue growth — it's the quality of the first 10 hires.",
            "author": "sarahtavel",
            "author_name": "Sarah Tavel",
            "platform": "linkedin",
            "engagement": 890,
            "category": "founder_advice",
        },
        {
            "text": "The 'AI wrapper' criticism misses the point entirely. Every great software company is a 'wrapper' around some technology. Salesforce wrapped databases. Stripe wrapped payments. The wrapper IS the product.",
            "author": "andrewchen",
            "author_name": "Andrew Chen",
            "platform": "twitter",
            "engagement": 3400,
            "category": "tech_analysis",
        },
        {
            "text": "B2B startups: your first 10 customers should feel like co-developers. If they're not on a Slack channel with your engineers, you're building in the dark.",
            "author": "jasonlk",
            "author_name": "Jason Lemkin",
            "platform": "twitter",
            "engagement": 670,
            "category": "founder_advice",
        },
        {
            "text": "Capital efficiency is back. The companies raising $3M to get to $1M ARR will outperform those who raised $30M to get to $5M ARR. The math just works.",
            "author": "eladgil",
            "author_name": "Elad Gil",
            "platform": "twitter",
            "engagement": 1100,
            "category": "fundraising",
        },
        {
            "text": "Mobile is mature. Cloud is mature. AI is the last major platform shift for a decade. The window for building generational companies is open NOW — and it will close faster than people think.",
            "author": "benedictevans",
            "author_name": "Benedict Evans",
            "platform": "twitter",
            "engagement": 2600,
            "category": "market_trends",
        },
    ]


def build_corpus(raw_tweets: list[dict]) -> dict:
    """
    Transform raw scraped tweets into the structured corpus format
    expected by the Writer's RAG system.
    """
    examples = []
    for tweet in raw_tweets:
        account = tweet.get("_account", {})
        text = tweet.get("full_text", tweet.get("text", ""))

        if not is_high_quality(tweet):
            continue

        likes = tweet.get("likeCount", tweet.get("favorites", 0))
        category = classify_category(text)

        examples.append(
            {
                "text": text,
                "author": account.get("handle", "unknown"),
                "author_name": account.get("name", "Unknown"),
                "platform": "twitter",
                "engagement": likes,
                "category": category,
            }
        )

    # Sort by engagement (highest first)
    examples.sort(key=lambda x: x["engagement"], reverse=True)

    return {
        "version": "1.0",
        "generated_at": datetime.utcnow().isoformat(),
        "total_examples": len(examples),
        "categories": list(set(ex["category"] for ex in examples)),
        "examples": examples,
    }


def main():
    parser = argparse.ArgumentParser(description="ClawdBot VC Twitter Scraper")
    parser.add_argument(
        "--mode",
        choices=["apify", "mock"],
        default="mock",
        help="Scraping mode: 'apify' uses Apify API, 'mock' generates sample data",
    )
    parser.add_argument(
        "--output",
        default="data/rag/vc_corpus.json",
        help="Output path for the corpus JSON",
    )
    parser.add_argument(
        "--tweets-per-account",
        type=int,
        default=100,
        help="Number of tweets to scrape per account (apify mode only)",
    )
    parser.add_argument(
        "--accounts",
        nargs="+",
        default=None,
        help="Specific account handles to scrape (default: all configured)",
    )
    args = parser.parse_args()

    output_path = Path(args.output)

    # Filter accounts if specified
    accounts = VC_ACCOUNTS
    if args.accounts:
        accounts = [a for a in VC_ACCOUNTS if a["handle"] in args.accounts]
        if not accounts:
            log.error(f"No matching accounts for: {args.accounts}")
            sys.exit(1)

    log.info(f"Mode: {args.mode}")
    log.info(f"Accounts: {[a['handle'] for a in accounts]}")
    log.info(f"Output: {output_path}")

    if args.mode == "apify":
        raw_tweets = scrape_via_apify(accounts, args.tweets_per_account)
        corpus = build_corpus(raw_tweets)
    else:
        log.info("Using mock corpus data for testing...")
        mock_examples = generate_mock_corpus()
        corpus = {
            "version": "1.0",
            "generated_at": datetime.utcnow().isoformat(),
            "total_examples": len(mock_examples),
            "categories": list(set(ex["category"] for ex in mock_examples)),
            "examples": mock_examples,
        }

    # Write output
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(corpus, f, indent=2)

    log.info(f"✅ Corpus written: {len(corpus['examples'])} examples → {output_path}")
    log.info(f"   Categories: {corpus['categories']}")


if __name__ == "__main__":
    main()

"""
ClawdBot Scraper — Multi-source news aggregator.

Fetches tech/VC news from NewsAPI and RSS feeds, writes structured
JSON to /data/latest.json for the Writer container to consume.

Security: This container has NO LLM access and NO write access to
anything except the /data volume.
"""

import json
import os
import sys
import time
import hashlib
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import yaml
import requests
import feedparser
from bs4 import BeautifulSoup

# ── Logging ──────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [SCRAPER] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("scraper")

# ── Configuration ────────────────────────────────────
CONFIG_PATH = Path("/app/config.yaml")
OUTPUT_PATH = Path("/data/latest.json")

# Allow overrides for local testing
if os.getenv("CLAWDBOT_LOCAL_TEST"):
    CONFIG_PATH = Path(os.getenv("CONFIG_PATH", "scraper/config.yaml"))
    OUTPUT_PATH = Path(os.getenv("OUTPUT_PATH", "data/news/latest.json"))


def load_config() -> dict:
    """Load scraper configuration from YAML."""
    if not CONFIG_PATH.exists():
        log.error(f"Config file not found: {CONFIG_PATH}")
        sys.exit(1)
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


def fetch_newsapi(config: dict) -> list[dict]:
    """
    Fetch articles from NewsAPI.org.
    Returns list of normalized article dicts.
    """
    api_config = config.get("news_api", {})
    if not api_config.get("enabled", False):
        log.info("NewsAPI disabled in config, skipping.")
        return []

    api_key = os.getenv("NEWS_API_KEY")
    if not api_key or api_key.startswith("your_"):
        log.warning("NEWS_API_KEY not set or invalid, skipping NewsAPI.")
        return []

    keywords = " OR ".join(api_config.get("keywords", ["venture capital"]))
    domains = ",".join(api_config.get("domains", []))

    params = {
        "q": keywords,
        "language": api_config.get("language", "en"),
        "sortBy": api_config.get("sort_by", "publishedAt"),
        "pageSize": api_config.get("page_size", 10),
        "apiKey": api_key,
    }
    if domains:
        params["domains"] = domains

    try:
        resp = requests.get(
            api_config.get("base_url", "https://newsapi.org/v2/everything"),
            params=params,
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()

        articles = []
        for art in data.get("articles", []):
            articles.append(
                {
                    "title": art.get("title", ""),
                    "description": art.get("description", ""),
                    "url": art.get("url", ""),
                    "source": art.get("source", {}).get("name", "Unknown"),
                    "published_at": art.get("publishedAt", ""),
                    "fetched_via": "newsapi",
                }
            )
        log.info(f"NewsAPI returned {len(articles)} articles.")
        return articles

    except requests.RequestException as e:
        log.error(f"NewsAPI request failed: {e}")
        return []


def fetch_rss_feeds(config: dict) -> list[dict]:
    """
    Fetch articles from configured RSS feeds.
    Free fallback that requires no API key.
    """
    rss_config = config.get("rss_feeds", {})
    if not rss_config.get("enabled", False):
        log.info("RSS feeds disabled in config, skipping.")
        return []

    articles = []
    for feed_conf in rss_config.get("feeds", []):
        feed_name = feed_conf.get("name", "Unknown")
        feed_url = feed_conf.get("url", "")

        if not feed_url:
            continue

        try:
            parsed = feedparser.parse(feed_url)
            for entry in parsed.entries[:5]:  # Top 5 per feed
                # Extract clean description
                desc = entry.get("summary", entry.get("description", ""))
                if desc:
                    desc = BeautifulSoup(desc, "html.parser").get_text()[:500]

                articles.append(
                    {
                        "title": entry.get("title", ""),
                        "description": desc,
                        "url": entry.get("link", ""),
                        "source": feed_name,
                        "published_at": entry.get("published", ""),
                        "fetched_via": "rss",
                    }
                )
            log.info(f"RSS [{feed_name}] returned {min(5, len(parsed.entries))} entries.")

        except Exception as e:
            log.warning(f"RSS [{feed_name}] failed: {e}")
            continue

    return articles


def deduplicate(articles: list[dict]) -> list[dict]:
    """Remove duplicate articles based on URL hash."""
    seen = set()
    unique = []
    for art in articles:
        url_hash = hashlib.md5(art["url"].encode()).hexdigest()
        if url_hash not in seen:
            seen.add(url_hash)
            unique.append(art)
    return unique


def build_summary(articles: list[dict]) -> str:
    """Build a text summary of top articles for the Writer."""
    lines = []
    for i, art in enumerate(articles[:10], 1):
        lines.append(f"{i}. [{art['source']}] {art['title']}")
        if art["description"]:
            lines.append(f"   {art['description'][:200]}")
        lines.append(f"   URL: {art['url']}")
        lines.append("")
    return "\n".join(lines)


def run_scraper():
    """Main scraper loop."""
    config = load_config()
    schedule_config = config.get("schedule", {})
    interval_hours = schedule_config.get("interval_hours", 6)
    max_articles = schedule_config.get("max_articles", 20)

    while True:
        log.info("=" * 50)
        log.info("Starting news scrape...")

        # Fetch from all sources
        all_articles = []
        all_articles.extend(fetch_newsapi(config))
        all_articles.extend(fetch_rss_feeds(config))

        # Deduplicate
        unique_articles = deduplicate(all_articles)[:max_articles]
        log.info(f"Total unique articles: {len(unique_articles)}")

        if not unique_articles:
            log.warning("No articles found! Check API keys and feed URLs.")
        else:
            # Build output
            output = {
                "scraped_at": datetime.utcnow().isoformat(),
                "article_count": len(unique_articles),
                "summary": build_summary(unique_articles),
                "articles": unique_articles,
            }

            # Ensure output directory exists
            OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

            # Write atomically (write to temp, then rename)
            tmp_path = OUTPUT_PATH.with_suffix(".tmp")
            with open(tmp_path, "w") as f:
                json.dump(output, f, indent=2, default=str)
            tmp_path.rename(OUTPUT_PATH)

            log.info(f"✅ Wrote {len(unique_articles)} articles to {OUTPUT_PATH}")

        # Sleep until next run
        log.info(f"Sleeping {interval_hours} hours until next scrape...")
        time.sleep(interval_hours * 3600)


if __name__ == "__main__":
    # If run with --once flag, do a single scrape and exit
    if "--once" in sys.argv:
        config = load_config()
        all_articles = []
        all_articles.extend(fetch_newsapi(config))
        all_articles.extend(fetch_rss_feeds(config))
        unique_articles = deduplicate(all_articles)[:20]

        output = {
            "scraped_at": datetime.utcnow().isoformat(),
            "article_count": len(unique_articles),
            "summary": build_summary(unique_articles),
            "articles": unique_articles,
        }

        OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(OUTPUT_PATH, "w") as f:
            json.dump(output, f, indent=2, default=str)

        log.info(f"✅ Single scrape complete: {len(unique_articles)} articles")
    else:
        run_scraper()

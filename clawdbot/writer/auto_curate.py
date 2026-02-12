"""
ClawdBot Auto-Curator — Claude-powered quality filter for RAG corpus ingestion.

Takes raw scraped tweets/posts and uses Claude to determine which are
high-quality VC insights worth including in the RAG corpus.

Usage:
    python auto_curate.py --input raw_tweets.json --output curated_corpus.json
"""

import json
import os
import sys
import argparse
import logging
from pathlib import Path
from typing import Optional

from anthropic import Anthropic

# ── Logging ──────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [CURATOR] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("curator")

# ── Client ───────────────────────────────────────────
ANTHROPIC_KEY = os.getenv("ANTHROPIC_API_KEY")
if not ANTHROPIC_KEY or len(ANTHROPIC_KEY) < 20:
    log.error("ANTHROPIC_API_KEY not set or invalid")
    sys.exit(1)

client = Anthropic(api_key=ANTHROPIC_KEY)
MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-20250514")

# ── Quality Assessment Prompt ────────────────────────
QUALITY_PROMPT = """You are evaluating whether a social media post from a VC/tech 
leader is high-quality enough to include in a training corpus for a social
media content generator.

CRITERIA for inclusion:
1. Provides actionable advice, market analysis, or genuine insight
2. Is NOT promotional or self-congratulatory ("I'm excited to announce...")
3. Has professional, measured tone (not hyperbolic)
4. Would inspire a thoughtful LinkedIn post if used as a style reference
5. Contains original thinking, not just links or retweets

POST TO EVALUATE:
Author: {author}
Text: {text}

Respond in EXACTLY this JSON format (no other text):
{{
  "include": true/false,
  "quality_score": 1-10,
  "category": "founder_advice" | "market_trends" | "tech_analysis" | "fundraising" | "leadership" | "general_insight",
  "reason": "one sentence explanation"
}}"""


def evaluate_post(text: str, author: str) -> Optional[dict]:
    """
    Use Claude to evaluate quality of a single post.
    Returns evaluation dict or None on failure.
    """
    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=200,
            temperature=0,
            messages=[
                {
                    "role": "user",
                    "content": QUALITY_PROMPT.format(author=author, text=text),
                }
            ],
        )

        result_text = response.content[0].text.strip()

        # Parse JSON response
        # Handle potential markdown code blocks
        if result_text.startswith("```"):
            result_text = result_text.split("```")[1]
            if result_text.startswith("json"):
                result_text = result_text[4:]

        return json.loads(result_text)

    except (json.JSONDecodeError, IndexError) as e:
        log.warning(f"Failed to parse Claude response for @{author}: {e}")
        return None
    except Exception as e:
        log.error(f"Claude API error: {e}")
        return None


def curate_corpus(
    input_path: Path,
    output_path: Path,
    min_quality: int = 6,
    batch_size: int = 10,
):
    """
    Process raw tweets through Claude quality filter.

    Args:
        input_path: Path to raw scraped data (JSON array of tweets)
        output_path: Path for filtered corpus output
        min_quality: Minimum quality_score for inclusion (1-10)
        batch_size: Number of posts to process (for API cost control)
    """
    # Load raw data
    with open(input_path) as f:
        raw_data = json.load(f)

    # Handle both array format and corpus format
    if isinstance(raw_data, list):
        posts = raw_data
    elif isinstance(raw_data, dict) and "examples" in raw_data:
        posts = raw_data["examples"]
    else:
        log.error("Unrecognized input format. Expected array or {examples: []}")
        sys.exit(1)

    log.info(f"Loaded {len(posts)} posts to evaluate")
    log.info(f"Processing first {batch_size} posts (min quality: {min_quality})")

    accepted = []
    rejected = 0

    for i, post in enumerate(posts[:batch_size]):
        text = post.get("text", post.get("full_text", ""))
        author = post.get("author", post.get("handle", "unknown"))

        if not text or len(text) < 30:
            rejected += 1
            continue

        log.info(f"  [{i+1}/{min(batch_size, len(posts))}] Evaluating @{author}...")

        evaluation = evaluate_post(text, author)

        if evaluation and evaluation.get("include") and evaluation.get("quality_score", 0) >= min_quality:
            accepted.append({
                "text": text,
                "author": author,
                "author_name": post.get("author_name", ""),
                "platform": post.get("platform", "twitter"),
                "engagement": post.get("engagement", 0),
                "category": evaluation["category"],
                "quality_score": evaluation["quality_score"],
            })
            log.info(f"    ✅ Accepted (score: {evaluation['quality_score']}, "
                     f"category: {evaluation['category']})")
        else:
            rejected += 1
            reason = evaluation.get("reason", "did not meet criteria") if evaluation else "evaluation failed"
            log.info(f"    ❌ Rejected: {reason}")

    # Build output corpus
    corpus = {
        "version": "1.0",
        "curated": True,
        "total_examples": len(accepted),
        "categories": list(set(ex["category"] for ex in accepted)),
        "examples": sorted(accepted, key=lambda x: x["quality_score"], reverse=True),
    }

    # Write output
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(corpus, f, indent=2)

    log.info(f"\n{'='*50}")
    log.info(f"Curation complete:")
    log.info(f"  Accepted: {len(accepted)}")
    log.info(f"  Rejected: {rejected}")
    log.info(f"  Output:   {output_path}")


def main():
    parser = argparse.ArgumentParser(description="ClawdBot RAG Corpus Curator")
    parser.add_argument(
        "--input",
        required=True,
        help="Path to raw scraped tweets (JSON)",
    )
    parser.add_argument(
        "--output",
        default="data/rag/vc_corpus.json",
        help="Output path for curated corpus",
    )
    parser.add_argument(
        "--min-quality",
        type=int,
        default=6,
        help="Minimum quality score (1-10) for inclusion",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=50,
        help="Max posts to process (controls API cost)",
    )
    args = parser.parse_args()

    curate_corpus(
        input_path=Path(args.input),
        output_path=Path(args.output),
        min_quality=args.min_quality,
        batch_size=args.batch_size,
    )


if __name__ == "__main__":
    main()

"""
ClawdBot Writer — Sandboxed AI content generation with constitutional critic.

This container runs in a hardened environment:
  - Read-only root filesystem
  - Network restricted to generativelanguage.googleapis.com only
  - Non-root user (UID 1000)
  - No access to social media APIs (physically impossible)

Flow:
  1. Read news from /data/news/latest.json (read-only mount)
  2. Load RAG examples from /app/rag/vc_corpus.json (read-only mount)
  3. Generate draft via Gemini with style-matching prompt
  4. Validate via constitutional critic pass (3 retry attempts)
  5. Write approved draft to /data/drafts/ (only writable mount)
"""

import json
import os
import sys
import hashlib
import random
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import google.generativeai as genai

# ── Logging ──────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [WRITER] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("writer")

# ── Environment Validation ───────────────────────────
GEMINI_KEY = os.getenv("GEMINI_API_KEY", "")
if not GEMINI_KEY or len(GEMINI_KEY) < 10:
    log.error("Invalid or missing GEMINI_API_KEY")
    raise ValueError("Invalid GEMINI_API_KEY — must be set in environment")

genai.configure(api_key=GEMINI_KEY)

# ── Paths ────────────────────────────────────────────
# In Docker: fixed paths from volume mounts
# Locally: use env overrides for testing
LOCAL_TEST = os.getenv("CLAWDBOT_LOCAL_TEST", "")

NEWS_PATH = Path(os.getenv("NEWS_PATH", "/data/news/latest.json"))
DRAFTS_PATH = Path(os.getenv("DRAFTS_PATH", "/data/drafts"))
RAG_PATH = Path(os.getenv("RAG_PATH", "/app/rag/vc_corpus.json"))

# ── Constants ────────────────────────────────────────
MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
MAX_RETRIES = 3
MAX_DRAFT_TOKENS = 500

# ── Constitutional Rules ─────────────────────────────
CONSTITUTION = """You are a content safety validator for a VC firm's social media.

Review this draft post and check ALL of the following rules:

1. **No financial advice**: Must NOT contain "buy", "invest in [specific company]",
   "guaranteed returns", "can't lose", or any language that could be construed
   as investment advice under SEC regulations.

2. **No political hot takes**: Must NOT contain partisan political statements,
   election commentary, or polarizing social issue opinions.

3. **No unverified claims**: Any factual claims must reference a news source.
   Opinions and analysis are acceptable.

4. **No profanity or offensive language**: Must be professional and suitable
   for LinkedIn.

5. **Appropriate tone**: Must be professional, insightful, and optimistic about
   technology. Should NOT be sycophantic, overly promotional, or hyperbolic.

6. **Reasonable length**: Must be between 50 and 300 words.

7. **No hallucinated data**: Must NOT cite specific statistics or numbers that
   weren't in the source material.

Answer with EXACTLY one of:
- "SAFE" — if the draft passes ALL checks
- "UNSAFE: <specific reason>" — if any check fails

Do NOT provide any other commentary."""


def load_rag_examples(n: int = 5) -> list[dict]:
    """
    Load curated VC writing samples from RAG corpus.
    Randomly samples N examples for diversity.
    """
    if not RAG_PATH.exists():
        log.warning(f"RAG corpus not found at {RAG_PATH}, using empty examples.")
        return []

    try:
        with open(RAG_PATH) as f:
            corpus = json.load(f)

        examples = corpus.get("examples", [])
        if not examples:
            log.warning("RAG corpus is empty.")
            return []

        sampled = random.sample(examples, min(n, len(examples)))
        log.info(f"Loaded {len(sampled)} RAG examples from {len(examples)} total.")
        return sampled

    except (json.JSONDecodeError, KeyError) as e:
        log.error(f"Failed to parse RAG corpus: {e}")
        return []


def load_news() -> dict:
    """Load the latest scraped news data."""
    if not NEWS_PATH.exists():
        log.error(f"News file not found at {NEWS_PATH}")
        raise FileNotFoundError(f"News file missing: {NEWS_PATH}")

    with open(NEWS_PATH) as f:
        news = json.load(f)

    log.info(
        f"Loaded news: {news.get('article_count', 0)} articles, "
        f"scraped at {news.get('scraped_at', 'unknown')}"
    )
    return news


def build_generation_prompt(news: dict, examples: list[dict]) -> str:
    """Build the generation prompt with news context and style examples."""
    examples_text = "\n".join(
        [f"- {ex['text']}" for ex in examples]
    ) if examples else "- [No examples available — use professional VC tone]"

    return f"""You are a VC associate at Z5 Capital writing a LinkedIn post.

TODAY'S NEWS:
{news.get('summary', 'No news summary available.')}

STYLE EXAMPLES (mimic this tone and approach):
{examples_text}

INSTRUCTIONS:
Write a 150-word LinkedIn post analyzing a trend from today's news. Guidelines:
- Be insightful but not preachy
- Be data-driven (cite the news source when referencing facts)
- Be optimistic about technology
- Be professional (no hype, no financial advice, no "invest in X")
- End with a forward-looking statement or question
- Do NOT use hashtags excessively (max 2-3 relevant ones)
- Do NOT start with "🚀" or similar emoji-heavy openings

Output ONLY the post text. No preamble, no "Here's a draft:", nothing except the post itself."""


def _call_gemini(prompt: str, temperature: float = 0.7, max_tokens: int = 500) -> str:
    """Call Gemini API and return the response text."""
    model = genai.GenerativeModel(MODEL)
    generation_config = genai.types.GenerationConfig(
        temperature=temperature,
        max_output_tokens=max_tokens,
    )
    response = model.generate_content(
        prompt,
        generation_config=generation_config,
    )
    return response.text.strip()


def critic_pass(draft_text: str) -> tuple[bool, str]:
    """
    Constitutional critic agent that validates draft against safety rules.
    Uses a separate Gemini call to ensure independence.

    Returns:
        (is_safe: bool, reason: str)
    """
    try:
        result = _call_gemini(
            f"{CONSTITUTION}\n\n---\n\nDRAFT TO REVIEW:\n{draft_text}",
            temperature=0,  # Deterministic for safety checks
            max_tokens=150,
        )

        if result.upper().startswith("SAFE"):
            return True, "Passed all constitutional checks"
        elif result.upper().startswith("UNSAFE"):
            reason = result.split(":", 1)[1].strip() if ":" in result else result
            return False, reason
        else:
            # Unexpected response — treat as unsafe
            log.warning(f"Unexpected critic response: {result[:100]}")
            return False, f"Critic gave ambiguous response: {result[:100]}"

    except Exception as e:
        log.error(f"Critic pass failed: {e}")
        return False, f"Critic error: {str(e)}"


def generate_post() -> Optional[Path]:
    """
    Main generation loop with retry logic.

    Flow:
        1. Load news + RAG examples
        2. Generate draft via Gemini
        3. Run constitutional critic
        4. Retry up to MAX_RETRIES if critic rejects
        5. Save approved draft to /data/drafts/

    Returns:
        Path to saved draft file, or None if all attempts failed.
    """
    # Load inputs
    news = load_news()
    examples = load_rag_examples(n=5)

    # Build prompt
    prompt = build_generation_prompt(news, examples)

    for attempt in range(1, MAX_RETRIES + 1):
        log.info(f"Generation attempt {attempt}/{MAX_RETRIES}...")

        try:
            # Generate draft
            draft = _call_gemini(prompt, temperature=0.7, max_tokens=MAX_DRAFT_TOKENS)
            word_count = len(draft.split())
            log.info(f"  Generated draft: {word_count} words")

            # Constitutional critic validation
            is_safe, reason = critic_pass(draft)

            if is_safe:
                # Save draft with metadata
                timestamp = datetime.now(timezone.utc).isoformat()
                draft_id = hashlib.md5(draft.encode()).hexdigest()[:8]
                draft_filename = f"{timestamp.replace(':', '-')}_{draft_id}.json"
                draft_file = DRAFTS_PATH / draft_filename

                # Ensure directory exists
                DRAFTS_PATH.mkdir(parents=True, exist_ok=True)

                draft_data = {
                    "text": draft,
                    "created_at": timestamp,
                    "draft_id": draft_id,
                    "word_count": word_count,
                    "news_source": news.get("articles", [{}])[0].get("url", ""),
                    "news_scraped_at": news.get("scraped_at", ""),
                    "model": MODEL,
                    "attempt": attempt,
                    "status": "pending_approval",
                    "critic_result": "SAFE",
                    "rag_examples_used": len(examples),
                }

                with open(draft_file, "w") as f:
                    json.dump(draft_data, f, indent=2)

                log.info(f"✅ Draft saved: {draft_file}")
                log.info(f"   Status: pending_approval")
                return draft_file

            else:
                log.warning(f"⚠️  Attempt {attempt} rejected by critic: {reason}")

                # Append feedback to prompt for retry
                prompt += f"\n\n[PREVIOUS DRAFT WAS REJECTED: {reason}. Please fix this issue.]"

        except Exception as e:
            log.error(f"❌ Attempt {attempt} failed with error: {e}")

    log.error(f"❌ Failed to generate safe draft after {MAX_RETRIES} attempts.")
    return None


if __name__ == "__main__":
    log.info("=" * 60)
    log.info("ClawdBot Writer starting...")
    log.info(f"Model: {MODEL}")
    log.info(f"News: {NEWS_PATH}")
    log.info(f"RAG: {RAG_PATH}")
    log.info(f"Drafts: {DRAFTS_PATH}")
    log.info("=" * 60)

    result = generate_post()

    if result:
        log.info(f"🎉 Success! Draft ready for human review: {result}")
        sys.exit(0)
    else:
        log.error("💀 All generation attempts failed.")
        sys.exit(1)

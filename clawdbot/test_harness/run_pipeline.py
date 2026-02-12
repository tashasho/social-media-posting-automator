"""
ClawdBot Test Harness — End-to-end pipeline simulation.

Simulates the full Scraper → Writer → Publisher pipeline locally
without requiring Docker, real API keys, or Slack integration.

Usage:
    # Full mock pipeline (no API keys needed)
    python test_harness/run_pipeline.py --mock

    # With real Claude API (needs ANTHROPIC_API_KEY)
    python test_harness/run_pipeline.py --live

    # Test specific stage
    python test_harness/run_pipeline.py --stage writer --mock
"""

import json
import os
import sys
import shutil
import tempfile
import hashlib
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Add parent directory to path for imports
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# ── Load .env file ───────────────────────────────────
def load_dotenv(env_path: Path):
    """Load environment variables from .env file."""
    if not env_path.exists():
        return
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()
            # Don't overwrite existing env vars
            if key and value and key not in os.environ:
                os.environ[key] = value

load_dotenv(PROJECT_ROOT / ".env")

# ── Logging ──────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("pipeline")

# ── ANSI Colors ──────────────────────────────────────
class C:
    HEADER = "\033[95m"
    BLUE = "\033[94m"
    CYAN = "\033[96m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    END = "\033[0m"


def banner(text: str, color: str = C.CYAN):
    """Print a colorized banner."""
    width = 60
    print(f"\n{color}{C.BOLD}{'═' * width}")
    print(f"  {text}")
    print(f"{'═' * width}{C.END}\n")


def step(num: int, text: str):
    """Print a pipeline step."""
    print(f"{C.BLUE}{C.BOLD}[Step {num}]{C.END} {text}")


def success(text: str):
    print(f"  {C.GREEN}✅ {text}{C.END}")


def warning(text: str):
    print(f"  {C.YELLOW}⚠️  {text}{C.END}")


def error(text: str):
    print(f"  {C.RED}❌ {text}{C.END}")


def info(text: str):
    print(f"  {C.DIM}{text}{C.END}")


# ═══════════════════════════════════════════════════════
# PIPELINE STAGES
# ═══════════════════════════════════════════════════════


def stage_scraper(work_dir: Path, mock: bool = True) -> Optional[Path]:
    """
    Stage 1: Scraper — Fetch or generate news data.
    """
    banner("STAGE 1: SCRAPER", C.CYAN)
    news_dir = work_dir / "data" / "news"
    news_dir.mkdir(parents=True, exist_ok=True)
    news_file = news_dir / "latest.json"

    if mock:
        step(1, "Using mock news data...")

        # Copy fixture if available, else generate
        fixture = Path(__file__).parent.parent / "data" / "news" / "latest.json"
        if fixture.exists():
            shutil.copy(fixture, news_file)
            success(f"Copied fixture: {fixture.name}")
        else:
            # Generate mock news inline
            news = {
                "scraped_at": datetime.utcnow().isoformat(),
                "article_count": 3,
                "summary": (
                    "1. [TechCrunch] AI Startup Funding Hits Record $120B\n"
                    "   Enterprise AI adoption accelerated across sectors.\n"
                    "   URL: https://techcrunch.com/ai-funding\n\n"
                    "2. [Bloomberg] YC W26 Batch 40% AI-Native\n"
                    "   Applications up 300% year over year.\n"
                    "   URL: https://bloomberg.com/yc-w26\n\n"
                    "3. [Reuters] European VC Recovery Underway\n"
                    "   Funding rose 25% YoY in Q4 2025.\n"
                    "   URL: https://reuters.com/eu-vc\n"
                ),
                "articles": [
                    {
                        "title": "AI Startup Funding Hits Record $120B",
                        "description": "Enterprise AI adoption accelerated.",
                        "url": "https://techcrunch.com/ai-funding",
                        "source": "TechCrunch",
                        "published_at": "2026-02-12T15:00:00Z",
                        "fetched_via": "mock",
                    }
                ],
            }
            with open(news_file, "w") as f:
                json.dump(news, f, indent=2)
            success("Generated mock news data")
    else:
        step(1, "Running live scraper...")
        os.environ["CLAWDBOT_LOCAL_TEST"] = "1"
        os.environ["CONFIG_PATH"] = str(Path(__file__).parent.parent / "scraper" / "config.yaml")
        os.environ["OUTPUT_PATH"] = str(news_file)

        try:
            from scraper.scraper import fetch_newsapi, fetch_rss_feeds, deduplicate, build_summary
            from scraper.scraper import load_config

            config = load_config()
            articles = []
            articles.extend(fetch_newsapi(config))
            articles.extend(fetch_rss_feeds(config))
            unique = deduplicate(articles)[:10]

            if unique:
                output = {
                    "scraped_at": datetime.utcnow().isoformat(),
                    "article_count": len(unique),
                    "summary": build_summary(unique),
                    "articles": unique,
                }
                with open(news_file, "w") as f:
                    json.dump(output, f, indent=2)
                success(f"Scraped {len(unique)} articles")
            else:
                warning("No articles scraped — falling back to mock")
                return stage_scraper(work_dir, mock=True)
        except Exception as e:
            error(f"Scraper failed: {e}")
            warning("Falling back to mock data")
            return stage_scraper(work_dir, mock=True)

    with open(news_file) as f:
        data = json.load(f)
    info(f"Articles: {data['article_count']}")
    info(f"Preview: {data['summary'][:150]}...")

    return news_file


def stage_writer(work_dir: Path, mock: bool = True) -> Optional[Path]:
    """
    Stage 2: Writer — Generate and validate a draft.
    """
    banner("STAGE 2: WRITER (Sandboxed)", C.YELLOW)
    drafts_dir = work_dir / "data" / "drafts"
    drafts_dir.mkdir(parents=True, exist_ok=True)

    news_file = work_dir / "data" / "news" / "latest.json"
    rag_file = Path(__file__).parent.parent / "data" / "rag" / "vc_corpus.json"

    if not news_file.exists():
        error("News file missing — run scraper stage first")
        return None

    if mock:
        step(2, "Generating mock draft (no Claude API call)...")

        # Load news for context
        with open(news_file) as f:
            news = json.load(f)

        # Generate a realistic mock draft
        mock_draft_text = (
            "The AI funding landscape continues to evolve rapidly. According to "
            "TechCrunch, startup funding in the AI sector hit $120B in 2025, driven "
            "largely by enterprise adoption across financial services and healthcare.\n\n"
            "What's particularly noteworthy isn't just the capital flowing in — it's "
            "the quality of companies being built. We're seeing a new generation of "
            "startups that are capital-efficient from day one, leveraging AI not just "
            "as a product feature but as a fundamental operating advantage.\n\n"
            "At Z5 Capital, we believe the most durable companies in this wave will "
            "be those solving genuine enterprise pain points rather than chasing "
            "the latest model release. The infrastructure layer is maturing, and "
            "the application layer opportunity is enormous.\n\n"
            "The question isn't whether AI will transform every industry — it's "
            "which founders will build the defining companies of this era."
        )

        timestamp = datetime.utcnow().isoformat()
        draft_id = hashlib.md5(mock_draft_text.encode()).hexdigest()[:8]

        draft_data = {
            "text": mock_draft_text,
            "created_at": timestamp,
            "draft_id": draft_id,
            "word_count": len(mock_draft_text.split()),
            "news_source": news.get("articles", [{}])[0].get("url", ""),
            "news_scraped_at": news.get("scraped_at", ""),
            "model": "mock-model",
            "attempt": 1,
            "status": "pending_approval",
            "critic_result": "SAFE (mock)",
            "rag_examples_used": 5,
        }

        draft_file = drafts_dir / f"{timestamp.replace(':', '-')}_{draft_id}.json"
        with open(draft_file, "w") as f:
            json.dump(draft_data, f, indent=2)

        success(f"Mock draft generated: {draft_data['word_count']} words")
        info(f"Draft ID: {draft_id}")
        info(f"Preview: {mock_draft_text[:120]}...")

        # Mock critic pass
        step(3, "Running mock critic validation...")
        success("Critic pass: SAFE ✓")

        return draft_file

    else:
        step(2, "Running live writer (Claude API)...")

        # Set environment for local testing
        os.environ["CLAWDBOT_LOCAL_TEST"] = "1"
        os.environ["NEWS_PATH"] = str(news_file)
        os.environ["DRAFTS_PATH"] = str(drafts_dir)
        os.environ["RAG_PATH"] = str(rag_file)

        try:
            from writer.writer import generate_post
            result = generate_post()
            if result:
                success(f"Draft generated: {result.name}")
                return result
            else:
                error("Writer failed to generate safe draft")
                return None
        except Exception as e:
            error(f"Writer error: {e}")
            return None


def stage_approval(draft_file: Path, mock: bool = True) -> Optional[Path]:
    """
    Stage 3: Human-in-the-Loop Approval.
    """
    banner("STAGE 3: HUMAN APPROVAL (HITL)", C.RED)

    with open(draft_file) as f:
        draft = json.load(f)

    # Display the draft for review
    print(f"{C.BOLD}{'─' * 60}{C.END}")
    print(f"{C.BOLD}📝 DRAFT FOR REVIEW:{C.END}\n")
    print(draft["text"])
    print(f"\n{C.DIM}Source: {draft.get('news_source', 'N/A')}")
    print(f"Words: {draft['word_count']} | Model: {draft['model']}{C.END}")
    print(f"{C.BOLD}{'─' * 60}{C.END}\n")

    if mock:
        step(4, "Simulating Slack approval (auto-approve in mock mode)...")
        warning("In production, this waits for a human to click 'Approve' in Slack")
        approval = "y"
    else:
        # Interactive terminal approval
        print(f"{C.BOLD}{C.YELLOW}Human decision required:{C.END}")
        print("  [y] Approve & Post")
        print("  [n] Reject")
        print("  [e] Edit")
        approval = input(f"\n{C.BOLD}Your choice (y/n/e): {C.END}").strip().lower()

    approved_dir = draft_file.parent.parent / "approved"
    approved_dir.mkdir(parents=True, exist_ok=True)

    if approval == "y":
        # Move to approved
        draft["status"] = "approved"
        draft["approved_at"] = datetime.utcnow().isoformat()
        draft["approved_by"] = "test_harness (local)"

        approved_file = approved_dir / draft_file.name
        with open(approved_file, "w") as f:
            json.dump(draft, f, indent=2)

        draft_file.unlink()
        success("Draft APPROVED ✓")
        return approved_file

    elif approval == "e":
        print(f"\n{C.YELLOW}Enter edited text (press Enter twice to finish):{C.END}")
        lines = []
        while True:
            line = input()
            if line == "":
                break
            lines.append(line)

        if lines:
            draft["original_text"] = draft["text"]
            draft["text"] = "\n".join(lines)
            draft["edited_by"] = "test_harness (local)"

            with open(draft_file, "w") as f:
                json.dump(draft, f, indent=2)

            success("Draft edited — re-running approval...")
            return stage_approval(draft_file, mock=False)

    else:
        draft["status"] = "rejected"
        draft["rejected_at"] = datetime.utcnow().isoformat()
        draft["rejected_by"] = "test_harness (local)"

        rejected_name = f"REJECTED_{draft_file.name}"
        with open(draft_file.parent / rejected_name, "w") as f:
            json.dump(draft, f, indent=2)
        draft_file.unlink()

        error("Draft REJECTED ✗")
        return None


def stage_publisher(approved_file: Path, mock: bool = True, skip_platforms: list = None) -> bool:
    """
    Stage 4: Publish to social platforms.
    """
    skip_platforms = skip_platforms or []
    banner("STAGE 4: PUBLISHER", C.GREEN)

    with open(approved_file) as f:
        draft = json.load(f)

    if skip_platforms:
        info(f"Skipping platforms: {', '.join(skip_platforms)}")

    if mock:
        step(5, "Simulating social media posting...")
        if "twitter" not in skip_platforms:
            info(f"Would post to Twitter: {draft['text'][:80]}...")
        if "linkedin" not in skip_platforms:
            info(f"Would post to LinkedIn: {draft['text'][:80]}...")
        active = [p for p in ["Twitter", "LinkedIn"] if p.lower() not in skip_platforms]
        success(f"Mock posted to: {', '.join(active)}")
        return True
    else:
        step(5, "Publishing to social platforms...")
        try:
            from publisher.social_poster import post_to_all_platforms
            results = post_to_all_platforms(draft, skip_platforms=skip_platforms)
            successes = [p for p, r in results.items() if r.get("success")]
            skipped = [p for p, r in results.items() if r.get("skipped")]
            if successes:
                success(f"Posted to: {', '.join(successes)}")
            if skipped:
                info(f"Skipped: {', '.join(skipped)}")
            if successes:
                return True
            else:
                error("No platforms succeeded")
                return False
        except Exception as e:
            error(f"Publishing error: {e}")
            return False


# ═══════════════════════════════════════════════════════
# MAIN PIPELINE
# ═══════════════════════════════════════════════════════


def run_full_pipeline(mock: bool = True, stage_filter: str = "all", skip_platforms: list = None):
    """Run the complete pipeline end-to-end."""
    banner("🤖 ClawdBot Pipeline Simulation", C.HEADER)
    print(f"  Mode: {'MOCK (no API calls)' if mock else 'LIVE (real APIs)'}")
    print(f"  Stage: {stage_filter}")
    print(f"  Time: {datetime.utcnow().isoformat()}")

    # Create temporary working directory
    work_dir = Path(tempfile.mkdtemp(prefix="clawdbot_"))
    print(f"  Work dir: {work_dir}\n")

    try:
        # ── Stage 1: Scraper ─────────────────────────
        if stage_filter in ("all", "scraper"):
            news_file = stage_scraper(work_dir, mock=mock)
            if not news_file:
                error("Scraper stage failed")
                return False

        # ── Stage 2: Writer ──────────────────────────
        draft_file = None
        if stage_filter in ("all", "writer"):
            draft_file = stage_writer(work_dir, mock=mock)
            if not draft_file:
                error("Writer stage failed")
                return False

        # ── Stage 3: Approval ────────────────────────
        approved_file = None
        if stage_filter in ("all", "approval") and draft_file:
            approved_file = stage_approval(draft_file, mock=mock)
            if not approved_file:
                warning("Draft was rejected — pipeline stopping")
                return False

        # ── Stage 4: Publisher ───────────────────────
        if stage_filter in ("all", "publisher") and approved_file:
            posted = stage_publisher(approved_file, mock=mock, skip_platforms=skip_platforms or [])
            if not posted:
                error("Publisher stage failed")
                return False

        # ── Summary ──────────────────────────────────
        banner("PIPELINE COMPLETE ✅", C.GREEN)

        # Show file tree
        print(f"{C.BOLD}Generated files:{C.END}")
        for root, dirs, files in os.walk(work_dir):
            level = root.replace(str(work_dir), "").count(os.sep)
            indent = "  " * (level + 1)
            print(f"{indent}{C.BLUE}{Path(root).name}/{C.END}")
            sub_indent = "  " * (level + 2)
            for file in files:
                size = os.path.getsize(os.path.join(root, file))
                print(f"{sub_indent}{file} ({size} bytes)")

        return True

    except KeyboardInterrupt:
        warning("\nPipeline interrupted by user")
        return False
    finally:
        # Optionally clean up
        if mock:
            info(f"\nWork directory preserved at: {work_dir}")
            info("Delete with: rm -rf " + str(work_dir))


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="ClawdBot Pipeline Test Harness")
    parser.add_argument(
        "--mock",
        action="store_true",
        default=True,
        help="Run in mock mode (no real API calls)",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Run with real APIs (needs env vars)",
    )
    parser.add_argument(
        "--stage",
        choices=["all", "scraper", "writer", "approval", "publisher"],
        default="all",
        help="Run a specific pipeline stage only",
    )
    parser.add_argument(
        "--skip-linkedin",
        action="store_true",
        help="Skip LinkedIn posting",
    )
    parser.add_argument(
        "--skip-twitter",
        action="store_true",
        help="Skip Twitter posting",
    )
    args = parser.parse_args()

    mock_mode = not args.live
    skip = []
    if args.skip_linkedin:
        skip.append("linkedin")
    if args.skip_twitter:
        skip.append("twitter")

    result = run_full_pipeline(mock=mock_mode, stage_filter=args.stage, skip_platforms=skip)
    sys.exit(0 if result else 1)

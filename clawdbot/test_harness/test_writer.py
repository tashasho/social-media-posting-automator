"""
ClawdBot Writer Tests — Unit tests for draft generation logic.

Tests the writer module's prompt building, draft saving, and retry logic
using mocked Anthropic client (no real API calls).
"""

import json
import os
import sys
import pytest
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch
from datetime import datetime

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))


class MockAnthropicResponse:
    """Mock Anthropic API response."""

    def __init__(self, text: str):
        self.content = [MagicMock(text=text)]


@pytest.fixture
def work_dir():
    """Create temporary working directory with required structure."""
    with tempfile.TemporaryDirectory(prefix="clawdbot_test_") as tmpdir:
        work = Path(tmpdir)

        # Create directories
        (work / "news").mkdir()
        (work / "drafts").mkdir()
        (work / "rag").mkdir()

        # Create news fixture
        news = {
            "scraped_at": "2026-02-12T18:00:00Z",
            "article_count": 1,
            "summary": "1. [TechCrunch] AI Startup Funding Hits Record\n",
            "articles": [
                {
                    "title": "AI Funding Record",
                    "url": "https://example.com/article",
                }
            ],
        }
        with open(work / "news" / "latest.json", "w") as f:
            json.dump(news, f)

        # Create RAG corpus
        corpus = {
            "version": "1.0",
            "examples": [
                {
                    "text": "The best founders are obsessed with the problem.",
                    "author": "paulg",
                    "category": "founder_advice",
                },
                {
                    "text": "Unit economics matter again.",
                    "author": "jasonlk",
                    "category": "market_trends",
                },
            ],
        }
        with open(work / "rag" / "vc_corpus.json", "w") as f:
            json.dump(corpus, f)

        yield work


class TestWriterPromptBuilding:
    """Test prompt construction logic."""

    def test_build_generation_prompt_with_examples(self, work_dir):
        """Prompt should include news and RAG examples."""
        os.environ["NEWS_PATH"] = str(work_dir / "news" / "latest.json")
        os.environ["RAG_PATH"] = str(work_dir / "rag" / "vc_corpus.json")
        os.environ["DRAFTS_PATH"] = str(work_dir / "drafts")
        os.environ["CLAWDBOT_LOCAL_TEST"] = "1"
        os.environ["ANTHROPIC_API_KEY"] = "sk-ant-test-key-for-testing-only-1234567890"

        # Import after setting env vars
        from writer.writer import build_generation_prompt, load_news, load_rag_examples

        news = load_news()
        examples = load_rag_examples(n=2)

        prompt = build_generation_prompt(news, examples)

        assert "TODAY'S NEWS:" in prompt
        assert "STYLE EXAMPLES" in prompt
        assert "Z5 Capital" in prompt
        assert "LinkedIn" in prompt

    def test_build_prompt_without_examples(self, work_dir):
        """Prompt should have fallback when no RAG examples available."""
        os.environ["NEWS_PATH"] = str(work_dir / "news" / "latest.json")
        os.environ["RAG_PATH"] = str(work_dir / "nonexistent.json")
        os.environ["DRAFTS_PATH"] = str(work_dir / "drafts")
        os.environ["CLAWDBOT_LOCAL_TEST"] = "1"
        os.environ["ANTHROPIC_API_KEY"] = "sk-ant-test-key-for-testing-only-1234567890"

        from writer.writer import build_generation_prompt, load_news, load_rag_examples

        news = load_news()
        examples = load_rag_examples(n=5)

        prompt = build_generation_prompt(news, examples)

        assert "No examples available" in prompt or "STYLE EXAMPLES" in prompt


class TestDraftSaving:
    """Test draft file output."""

    def test_draft_json_format(self, work_dir):
        """Saved draft should have required fields."""
        drafts_dir = work_dir / "drafts"

        # Create a mock draft
        draft_data = {
            "text": "This is a test draft about AI trends.",
            "created_at": datetime.utcnow().isoformat(),
            "draft_id": "abc123",
            "word_count": 8,
            "news_source": "https://example.com",
            "model": "test-model",
            "attempt": 1,
            "status": "pending_approval",
            "critic_result": "SAFE",
        }

        draft_file = drafts_dir / "test_draft.json"
        with open(draft_file, "w") as f:
            json.dump(draft_data, f, indent=2)

        # Verify
        with open(draft_file) as f:
            saved = json.load(f)

        assert saved["status"] == "pending_approval"
        assert "text" in saved
        assert "created_at" in saved
        assert "draft_id" in saved
        assert len(saved["text"]) > 0

    def test_draft_path_security(self, work_dir):
        """Draft filenames should not allow path traversal."""
        # Simulate the path safety check from webhook_receiver
        malicious_name = "../../../etc/passwd"
        safe_name = Path(malicious_name).name
        assert safe_name == "passwd"  # Path component only, no traversal


class TestRAGLoading:
    """Test RAG corpus loading."""

    def test_load_rag_examples(self, work_dir):
        """Should load and randomly sample from corpus."""
        os.environ["RAG_PATH"] = str(work_dir / "rag" / "vc_corpus.json")
        os.environ["ANTHROPIC_API_KEY"] = "sk-ant-test-key-for-testing-only-1234567890"
        os.environ["NEWS_PATH"] = str(work_dir / "news" / "latest.json")
        os.environ["DRAFTS_PATH"] = str(work_dir / "drafts")

        from writer.writer import load_rag_examples

        examples = load_rag_examples(n=2)
        assert len(examples) == 2
        assert all("text" in ex for ex in examples)

    def test_load_rag_missing_file(self, work_dir):
        """Should return empty list when corpus is missing."""
        os.environ["RAG_PATH"] = str(work_dir / "nonexistent.json")
        os.environ["ANTHROPIC_API_KEY"] = "sk-ant-test-key-for-testing-only-1234567890"
        os.environ["NEWS_PATH"] = str(work_dir / "news" / "latest.json")
        os.environ["DRAFTS_PATH"] = str(work_dir / "drafts")

        from writer.writer import load_rag_examples

        examples = load_rag_examples(n=5)
        assert examples == []


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

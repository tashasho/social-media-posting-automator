"""
ClawdBot Critic Tests — Unit tests for constitutional critic validation.

Tests various content categories to ensure the critic correctly identifies
unsafe content (financial advice, political takes, profanity, etc.)
"""

import json
import os
import sys
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))


class MockAnthropicResponse:
    """Mock Anthropic API response."""

    def __init__(self, text: str):
        self.content = [MagicMock(text=text)]


# ── Test Data ────────────────────────────────────────

SAFE_DRAFTS = [
    "The AI sector continues to grow, with enterprise adoption accelerating. "
    "According to TechCrunch, funding hit $120B this year. At Z5 Capital, we're "
    "excited about the opportunity in applied AI for healthcare and fintech.",

    "The startup ecosystem is shifting toward capital efficiency. We're seeing "
    "founders who raised $3M achieve what previously required $30M. The quality "
    "of companies being built today is remarkable.",
]

UNSAFE_DRAFTS_FINANCIAL = [
    "You should definitely invest in Anthropic stock — it's guaranteed to 10x! "
    "Buy as much as you can before the IPO.",

    "The returns from crypto are guaranteed. Every smart investor should buy "
    "Bitcoin right now. You can't lose.",
]

UNSAFE_DRAFTS_POLITICAL = [
    "The current administration's tech policy is destroying innovation. "
    "Vote them out if you care about startups.",

    "Democrats are ruining Silicon Valley with their regulations. "
    "We need conservative leadership to save tech.",
]

UNSAFE_DRAFTS_PROFANITY = [
    "This damn market is going to hell. Every f***ing startup is overvalued.",
]

UNSAFE_DRAFTS_UNVERIFIED = [
    "Studies show that exactly 97.3% of AI startups will fail within 2 years. "
    "Our proprietary research also shows that Series B valuations dropped 67.8%.",
]


class TestCriticSafeContent:
    """Test that the critic passes safe content."""

    @patch("writer.writer.client")
    def test_safe_draft_passes(self, mock_client):
        """Safe content should be marked as SAFE."""
        os.environ["ANTHROPIC_API_KEY"] = "sk-ant-test-key-for-testing-only-1234567890"
        os.environ["NEWS_PATH"] = "/tmp/test_news.json"
        os.environ["DRAFTS_PATH"] = "/tmp/test_drafts"
        os.environ["RAG_PATH"] = "/tmp/test_rag.json"

        mock_client.messages.create.return_value = MockAnthropicResponse("SAFE")

        from writer.writer import critic_pass

        for draft in SAFE_DRAFTS:
            is_safe, reason = critic_pass(draft)
            assert is_safe, f"Expected SAFE for: {draft[:50]}..."


class TestCriticUnsafeContent:
    """Test that the critic flags unsafe content."""

    @patch("writer.writer.client")
    def test_financial_advice_flagged(self, mock_client):
        """Financial advice should be flagged as UNSAFE."""
        os.environ["ANTHROPIC_API_KEY"] = "sk-ant-test-key-for-testing-only-1234567890"
        os.environ["NEWS_PATH"] = "/tmp/test_news.json"
        os.environ["DRAFTS_PATH"] = "/tmp/test_drafts"
        os.environ["RAG_PATH"] = "/tmp/test_rag.json"

        mock_client.messages.create.return_value = MockAnthropicResponse(
            "UNSAFE: Contains financial advice ('guaranteed returns')"
        )

        from writer.writer import critic_pass

        for draft in UNSAFE_DRAFTS_FINANCIAL:
            is_safe, reason = critic_pass(draft)
            assert not is_safe, f"Expected UNSAFE for: {draft[:50]}..."
            assert len(reason) > 0

    @patch("writer.writer.client")
    def test_political_content_flagged(self, mock_client):
        """Political statements should be flagged."""
        os.environ["ANTHROPIC_API_KEY"] = "sk-ant-test-key-for-testing-only-1234567890"
        mock_client.messages.create.return_value = MockAnthropicResponse(
            "UNSAFE: Contains political partisan statement"
        )

        from writer.writer import critic_pass

        for draft in UNSAFE_DRAFTS_POLITICAL:
            is_safe, reason = critic_pass(draft)
            assert not is_safe

    @patch("writer.writer.client")
    def test_profanity_flagged(self, mock_client):
        """Profanity should be flagged."""
        os.environ["ANTHROPIC_API_KEY"] = "sk-ant-test-key-for-testing-only-1234567890"
        mock_client.messages.create.return_value = MockAnthropicResponse(
            "UNSAFE: Contains profanity"
        )

        from writer.writer import critic_pass

        for draft in UNSAFE_DRAFTS_PROFANITY:
            is_safe, reason = critic_pass(draft)
            assert not is_safe


class TestCriticEdgeCases:
    """Test critic behavior with edge cases."""

    @patch("writer.writer.client")
    def test_ambiguous_response_treated_as_unsafe(self, mock_client):
        """Non-standard critic response should be treated as UNSAFE."""
        os.environ["ANTHROPIC_API_KEY"] = "sk-ant-test-key-for-testing-only-1234567890"

        mock_client.messages.create.return_value = MockAnthropicResponse(
            "I'm not sure about this draft. It might be okay."
        )

        from writer.writer import critic_pass

        is_safe, reason = critic_pass("Some draft text")
        assert not is_safe, "Ambiguous response should be treated as unsafe"

    @patch("writer.writer.client")
    def test_api_error_treated_as_unsafe(self, mock_client):
        """API errors should be treated as UNSAFE (fail-safe)."""
        os.environ["ANTHROPIC_API_KEY"] = "sk-ant-test-key-for-testing-only-1234567890"

        mock_client.messages.create.side_effect = Exception("API timeout")

        from writer.writer import critic_pass

        is_safe, reason = critic_pass("Some draft text")
        assert not is_safe, "API error should be treated as unsafe"
        assert "error" in reason.lower()

    @patch("writer.writer.client")
    def test_safe_with_trailing_whitespace(self, mock_client):
        """SAFE with trailing whitespace should still pass."""
        os.environ["ANTHROPIC_API_KEY"] = "sk-ant-test-key-for-testing-only-1234567890"

        mock_client.messages.create.return_value = MockAnthropicResponse(
            "SAFE  \n"
        )

        from writer.writer import critic_pass

        is_safe, reason = critic_pass("Valid draft text")
        assert is_safe


class TestCriticConstitution:
    """Test that the constitution prompt is properly structured."""

    def test_constitution_covers_all_rules(self):
        """Constitution should mention all required safety rules."""
        os.environ["ANTHROPIC_API_KEY"] = "sk-ant-test-key-for-testing-only-1234567890"
        os.environ["NEWS_PATH"] = "/tmp/test_news.json"
        os.environ["DRAFTS_PATH"] = "/tmp/test_drafts"
        os.environ["RAG_PATH"] = "/tmp/test_rag.json"

        from writer.writer import CONSTITUTION

        required_topics = [
            "financial",
            "political",
            "profanity",
            "professional",
            "length",
        ]

        constitution_lower = CONSTITUTION.lower()
        for topic in required_topics:
            assert topic in constitution_lower, (
                f"Constitution missing '{topic}' check"
            )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

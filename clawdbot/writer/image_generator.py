"""
ClawdBot Image Generator — Generate Z5-branded visuals for social posts.

Uses Gemini to generate image descriptions, then creates branded visuals
following Z5 Capital's social media design guidelines.

Templates:
    - "data_drop": Dark charcoal bg, gradient chart, white text (for data/trends)
    - "thought_leader": White bg, gradient quote mark, charcoal text (for insights)
    - "milestone": Split screen with gradient border (for announcements)

Usage:
    from image_generator import generate_post_image
    path = generate_post_image(draft_text, template="data_drop")
"""

import json
import os
import sys
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import google.generativeai as genai

# ── Logging ──────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [IMAGE] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("image_generator")

# ── Configuration ────────────────────────────────────
GEMINI_KEY = os.getenv("GEMINI_API_KEY", "")
if GEMINI_KEY:
    genai.configure(api_key=GEMINI_KEY)

IMAGES_DIR = Path(os.getenv("IMAGES_PATH", "data/images"))

# ── Z5 Brand Constants ──────────────────────────────
Z5_COLORS = {
    "charcoal": "#212529",
    "white": "#FFFFFF",
    "light_grey": "#F8F9FA",
    "grey": "#6C757D",
    "magenta": "#E91E63",
    "violet": "#7B1FA2",
}

# ── Template Prompts ────────────────────────────────

TEMPLATE_DATA_DROP = """Social media post graphic following strict Z5 Capital brand guidelines. "Data Drop" template:

BACKGROUND: Solid dark charcoal color (#212529), clean and dark.

LAYOUT ({orientation}):
- TOP LEFT: Left-aligned headline text "{headline}" in white, bold, uppercase Montserrat ExtraBold font. Clean, modern typography.
- BELOW HEADLINE: Smaller white body text in Inter Regular: "{subtitle}"
- CENTER: A sleek upward-trending line chart/bar chart with glowing gradient bars going from Magenta (#E91E63) to Violet (#7B1FA2). The chart shows exponential growth. Clean minimal grid lines in subtle dark grey. The gradient makes the data pop like neon against the dark background.
- BOTTOM area: Small data labels in white: "{source_line}"
- BOTTOM RIGHT: Small Z5 Capital logo (purple/magenta geometric Z prism icon) — unobtrusive

STYLE: Ultra-clean, minimal, professional. No clutter. One primary message. No gradient on body text — only on chart elements. Dark mode aesthetic. Premium VC firm look. No stock photo feel."""

TEMPLATE_THOUGHT_LEADER = """Social media post graphic following strict Z5 Capital brand guidelines. "Thought Leader" template:

BACKGROUND: Clean white (#FFFFFF) or very light grey (#F8F9FA).

LAYOUT ({orientation}):
- TOP LEFT: A large, oversized opening quotation mark in a gradient from Magenta (#E91E63) to Violet (#7B1FA2). Subtle and elegant.
- CENTER: The quote text "{headline}" in dark charcoal (#212529), bold Montserrat font, left-aligned. Impactful typography.
- BELOW: Attribution "— Z5 Capital" in grey (#6C757D), Inter Medium font.
- BOTTOM CENTER: Small Z5 Capital logo (purple/magenta geometric Z prism icon)

STYLE: Clean, white-space heavy, professional. Day mode aesthetic. One quote only. No clutter. Premium VC firm look."""

TEMPLATE_MILESTONE = """Social media post graphic following strict Z5 Capital brand guidelines. "Milestone" template:

LAYOUT ({orientation}):
- LEFT SIDE: White space with left-aligned text
  - Small tag in magenta: "{tag}"
  - Headline: "{headline}" in dark charcoal (#212529), Montserrat ExtraBold, uppercase
  - Subtitle: "{subtitle}" in grey (#6C757D), Inter Regular
- BOTTOM OR LEFT EDGE: A 4px thick gradient border from Magenta (#E91E63) to Violet (#7B1FA2)
- BOTTOM RIGHT: Small Z5 Capital logo

STYLE: Card-style layout. Clean, professional. Gradient accent border only — no gradient on text. Premium VC firm look."""


def classify_template(draft_text: str) -> str:
    """
    Auto-classify which Z5 template to use based on post content.

    Returns: 'data_drop', 'thought_leader', or 'milestone'
    """
    text_lower = draft_text.lower()

    # Data indicators
    data_keywords = [
        '$', 'billion', 'million', '%', 'record', 'funding', 'raised',
        'growth', 'revenue', 'valuation', 'ratio', 'trend', 'chart',
        'data', 'statistics', 'report', 'quarter', 'q1', 'q2', 'q3', 'q4',
        'yoy', 'year-over-year',
    ]

    # Milestone indicators
    milestone_keywords = [
        'welcome', 'announce', 'join', 'hired', 'launch', 'closed',
        'partnership', 'acquisition', 'ipo', 'series', 'seed round',
        'promotion', 'new hire',
    ]

    data_score = sum(1 for kw in data_keywords if kw in text_lower)
    milestone_score = sum(1 for kw in milestone_keywords if kw in text_lower)

    if data_score >= 3:
        return "data_drop"
    elif milestone_score >= 2:
        return "milestone"
    else:
        return "thought_leader"


def extract_headline(draft_text: str, max_words: int = 8) -> str:
    """Extract a punchy headline from the draft text."""
    # Take first sentence
    first_sentence = draft_text.split('.')[0].strip()
    words = first_sentence.split()

    if len(words) <= max_words:
        return first_sentence.upper()

    # Try to find a natural break
    headline = ' '.join(words[:max_words]).upper()
    return headline


def build_image_prompt(
    draft_text: str,
    template: str = "auto",
    platform: str = "linkedin",
    logo_path: Optional[str] = None,
) -> tuple[str, str]:
    """
    Build an image generation prompt from draft text and template.

    Returns:
        (prompt_string, template_used)
    """
    if template == "auto":
        template = classify_template(draft_text)

    log.info(f"Using template: {template}")

    # Platform orientation
    orientations = {
        "linkedin": "LinkedIn 4:5 portrait",
        "twitter": "Twitter 16:9 landscape",
        "instagram": "Instagram 1:1 square",
    }
    orientation = orientations.get(platform, "4:5 portrait")

    # Extract content elements
    headline = extract_headline(draft_text)

    # Extract first meaningful sentence as subtitle
    sentences = [s.strip() for s in draft_text.split('.') if len(s.strip()) > 20]
    subtitle = sentences[1] if len(sentences) > 1 else sentences[0] if sentences else ""
    if len(subtitle) > 80:
        subtitle = subtitle[:77] + "..."

    # Source extraction
    sources = []
    for src in ["TechCrunch", "Bloomberg", "Reuters", "The Information", "Forbes",
                "WSJ", "Financial Times", "Crunchbase", "PitchBook"]:
        if src.lower() in draft_text.lower():
            sources.append(src)
    source_line = "Source: " + " • ".join(sources) if sources else "Source: Z5 Capital Research"

    if template == "data_drop":
        prompt = TEMPLATE_DATA_DROP.format(
            orientation=orientation,
            headline=headline,
            subtitle=subtitle,
            source_line=source_line,
        )
    elif template == "thought_leader":
        # Pick the most quotable sentence
        prompt = TEMPLATE_THOUGHT_LEADER.format(
            orientation=orientation,
            headline=headline,
        )
    elif template == "milestone":
        prompt = TEMPLATE_MILESTONE.format(
            orientation=orientation,
            tag="Z5 CAPITAL",
            headline=headline,
            subtitle=subtitle,
        )
    else:
        log.warning(f"Unknown template '{template}', falling back to data_drop")
        template = "data_drop"
        prompt = TEMPLATE_DATA_DROP.format(
            orientation=orientation,
            headline=headline,
            subtitle=subtitle,
            source_line=source_line,
        )

    return prompt, template


def generate_post_image(
    draft_text: str,
    draft_id: str = "",
    template: str = "auto",
    platform: str = "linkedin",
    output_dir: Optional[Path] = None,
) -> Optional[Path]:
    """
    Generate a Z5-branded image for a social media post.

    This generates a prompt and saves metadata for external image generation.
    The actual image generation is done by the pipeline orchestrator
    (which has access to image generation tools).

    Args:
        draft_text: The post text to create a visual for
        draft_id: ID of the draft for filename
        template: 'auto', 'data_drop', 'thought_leader', or 'milestone'
        platform: 'linkedin', 'twitter', or 'instagram'
        output_dir: Where to save the image prompt

    Returns:
        Path to the image prompt JSON file
    """
    output_dir = output_dir or IMAGES_DIR
    output_dir.mkdir(parents=True, exist_ok=True)

    prompt, template_used = build_image_prompt(draft_text, template, platform)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"{timestamp}_{draft_id}_prompt.json"
    prompt_file = output_dir / filename

    prompt_data = {
        "prompt": prompt,
        "template": template_used,
        "platform": platform,
        "draft_id": draft_id,
        "headline": extract_headline(draft_text),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "z5_colors": Z5_COLORS,
    }

    with open(prompt_file, "w") as f:
        json.dump(prompt_data, f, indent=2)

    log.info(f"✅ Image prompt saved: {prompt_file}")
    log.info(f"   Template: {template_used} | Platform: {platform}")

    return prompt_file


# ── CLI ──────────────────────────────────────────────
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python image_generator.py <draft_file.json> [template] [platform]")
        print("  Templates: auto, data_drop, thought_leader, milestone")
        print("  Platforms: linkedin, twitter, instagram")
        sys.exit(1)

    draft_file = sys.argv[1]
    template = sys.argv[2] if len(sys.argv) > 2 else "auto"
    platform = sys.argv[3] if len(sys.argv) > 3 else "linkedin"

    with open(draft_file) as f:
        draft = json.load(f)

    result = generate_post_image(
        draft_text=draft["text"],
        draft_id=draft.get("draft_id", "unknown"),
        template=template,
        platform=platform,
    )

    if result:
        with open(result) as f:
            data = json.load(f)
        print(f"\n{'='*60}")
        print(f"Template: {data['template']}")
        print(f"Platform: {data['platform']}")
        print(f"Headline: {data['headline']}")
        print(f"{'='*60}")
        print(f"\nPrompt:\n{data['prompt']}")
    else:
        print("Failed to generate image prompt")
        sys.exit(1)

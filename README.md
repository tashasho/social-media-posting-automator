# 📣 Social Media Posting Automator

> **AI-powered social media content pipeline for [Z5 Capital](https://z5.capital)** — scrapes VC/tech news, generates branded posts using Gemini AI, validates them with a constitutional critic, and publishes to Twitter/X and LinkedIn after human approval via Slack.

---

## 🎯 What It Does

This system fully automates the social media content lifecycle for a venture capital firm:

1. **Scrapes** the latest tech/VC news from NewsAPI and RSS feeds
2. **Generates** social media posts using Google Gemini with RAG-enhanced style matching
3. **Validates** every draft through a constitutional critic (blocks financial advice, unverified claims, political takes)
4. **Creates** Z5-branded visuals following strict design guidelines
5. **Routes** drafts to a Slack channel for human-in-the-loop (HITL) approval
6. **Posts** approved content to Twitter/X and LinkedIn simultaneously

**No post is ever published without explicit human approval.**

---

## 🏗️ Architecture

```
              ┌─────────────────────────────────────┐
              │  🔍  SCRAPER (Container 1)          │
              │  NewsAPI + RSS → /data/news.json    │
              │  No LLM access · No write access    │
              └─────────────────┬───────────────────┘
                                │ news data (read-only)
                                ▼
              ┌─────────────────────────────────────┐
              │  ✍️  WRITER (Container 2)            │
              │  News + RAG → Gemini → Draft        │
              │  Constitutional critic validation   │
              │  Image prompt generation            │
              │  Sandboxed · Read-only root FS      │
              └─────────────────┬───────────────────┘
                                │ draft JSON
                                ▼
              ┌─────────────────────────────────────┐
              │  📢  PUBLISHER (Container 3)        │
              │  Slack HITL → Approve → Post        │
              │  Twitter/X + LinkedIn               │
              │  Human-gated · No auto-posting      │
              └─────────────────────────────────────┘
```

Each container is **fully isolated** — the Writer cannot access social media APIs, and the Scraper cannot reach the LLM. Only the Publisher holds social media credentials, and it only acts on explicit human approval.

---

## 📁 Project Structure

```
social-media-posting-automator/
├── README.md                           ← You are here
├── .gitignore
│
└── clawdbot/                           ← Core application
    ├── docker-compose.yml              # Container orchestration
    ├── .env.example                    # Environment variable template
    ├── README.md                       # Detailed internal docs
    │
    ├── scraper/                        # 🔍 Container 1: News Fetcher
    │   ├── Dockerfile
    │   ├── scraper.py                  # Multi-source news aggregator (NewsAPI + RSS)
    │   ├── apify_vc_scraper.py         # VC Twitter scraping via Apify
    │   ├── config.yaml                 # Source configuration
    │   └── requirements.txt
    │
    ├── writer/                         # ✍️ Container 2: AI Content Generator
    │   ├── Dockerfile
    │   ├── writer.py                   # Gemini-powered post generation + critic
    │   ├── image_generator.py          # Z5-branded visual prompt builder
    │   ├── auto_curate.py              # RAG corpus quality filter
    │   └── requirements.txt
    │
    ├── publisher/                      # 📢 Container 3: Human-Gated Publisher
    │   ├── Dockerfile
    │   ├── slack_approval.py           # Slack interactive approval messages
    │   ├── webhook_receiver.py         # Flask webhook handler for Slack actions
    │   ├── social_poster.py            # Twitter/X + LinkedIn posting
    │   └── requirements.txt
    │
    ├── data/
    │   ├── news/latest.json            # Latest scraped news fixture
    │   ├── rag/vc_corpus.json          # Curated VC writing samples for style matching
    │   └── images/                     # Generated branded visuals
    │
    ├── brand/
    │   ├── social_media_guidelines.md  # Z5 design system & template specs
    │   └── z5_logo.png                 # Brand logo asset
    │
    ├── test_harness/                   # 🧪 Local testing tools
    │   ├── run_pipeline.py             # Full pipeline simulation (--mock mode)
    │   ├── mock_slack.py               # Slack mock for offline testing
    │   ├── test_writer.py              # Writer unit tests
    │   └── test_critic.py              # Critic validation tests
    │
    └── firewall/
        └── setup_iptables.sh           # Network security whitelist rules
```

---

## ⚙️ How It Works

### 1. Scraping (`scraper.py`)

The scraper fetches articles from two sources:

- **NewsAPI** — queries for tech/VC/startup keywords with date filtering
- **RSS Feeds** — TechCrunch, The Verge, and other outlets as a free fallback

Articles are deduplicated by URL hash and saved as structured JSON with title, summary, source, and publish date.

### 2. Writing (`writer.py`)

The writer uses **Google Gemini** to generate social media posts:

- Loads scraped news as context
- Pulls random samples from the **RAG corpus** (`vc_corpus.json`) — a curated collection of high-performing VC posts for style matching
- Generates a draft post in Z5 Capital's voice

Every draft then passes through a **Constitutional Critic** — a second Gemini call that validates the post against safety rules:

| Rule | What It Catches |
|------|----------------|
| No financial advice | "Buy", "invest in [company]", "guaranteed returns" |
| No political takes | Partisan statements, election commentary |
| No unverified claims | Facts not backed by news sources |
| No hallucinations | Information not present in source material |

If the critic rejects a draft, the writer **retries up to 3 times** with feedback. If all attempts fail, the pipeline exits with an error (no unsafe content ever reaches Slack).

### 3. Image Generation (`image_generator.py`)

Each post gets a branded visual using one of three Z5 templates:

| Template | Use Case | Style |
|----------|----------|-------|
| **Data Drop** | Charts, trends, statistics | Dark mode (#212529), gradient chart elements |
| **Thought Leader** | Quotes, insights | White/light grey, oversized quotation mark |
| **Milestone** | Funding rounds, hires | Split screen, gradient accent border |

The template is auto-classified from post content. Platform-specific aspect ratios are applied (4:5 for LinkedIn, 16:9 for Twitter, 1:1 for Instagram).

### 4. Publishing (`publisher/`)

A three-step human-gated flow:

1. **`slack_approval.py`** sends the draft to a Slack channel with ✅ Approve, ❌ Reject, and ✏️ Edit buttons
2. **`webhook_receiver.py`** (Flask) listens for Slack interactive actions
3. **`social_poster.py`** posts approved content to Twitter/X (via API v2) and LinkedIn (via Marketing API)

---

## 🔒 Security Model

This system was designed with **defense-in-depth** — the AI never has unsupervised access to social media accounts.

| Layer | How It Works |
|-------|-------------|
| **Container Isolation** | 3 separate containers, each with least-privilege access |
| **Filesystem** | Writer has read-only root FS; only `/tmp` is writable |
| **Network** | Writer is on an internal-only network; iptables whitelist restricts egress |
| **Privileges** | Non-root user (UID 1000), `cap_drop: ALL`, `no-new-privileges` |
| **Human Gate** | Slack HITL — no auto-posting is architecturally possible |
| **Content Validation** | Constitutional critic blocks unsafe content before it reaches Slack |
| **Secret Isolation** | Social media API keys exist only in the Publisher container |

---

## 🚀 Quick Start

### Prerequisites

- [Docker](https://docs.docker.com/get-docker/) and Docker Compose
- API keys (see below)

### 1. Clone and Configure

```bash
git clone https://github.com/tashasho/social-media-posting-automator.git
cd social-media-posting-automator/clawdbot
cp .env.example .env
```

Edit `.env` with your API keys:

```bash
# Required
GEMINI_API_KEY=your_gemini_key           # Google AI Studio
NEWS_API_KEY=your_newsapi_key            # newsapi.org

# Slack (for approval workflow)
SLACK_BOT_TOKEN=xoxb-...
SLACK_SIGNING_SECRET=...
SLACK_APPROVAL_CHANNEL=#clawdbot-approvals
SLACK_WEBHOOK_URL=https://hooks.slack.com/...

# Social platforms (for publishing)
TWITTER_API_KEY=...
TWITTER_API_SECRET=...
TWITTER_ACCESS_TOKEN=...
TWITTER_ACCESS_SECRET=...
LINKEDIN_ACCESS_TOKEN=...
LINKEDIN_ORG_ID=...
```

### 2. Run with Docker

```bash
# Build all containers
docker compose build

# Run the full pipeline
docker compose up
```

### 3. Run Locally (No Docker / No API Keys)

```bash
# Install dependencies
pip install -r writer/requirements.txt -r publisher/requirements.txt

# Run full pipeline in mock mode
python test_harness/run_pipeline.py --mock
```

---

## 🧪 Testing

```bash
# Run all tests
pip install pytest
python -m pytest test_harness/ -v

# Test the writer in isolation
python test_harness/test_writer.py

# Test the constitutional critic
python test_harness/test_critic.py

# Simulate Slack webhook locally
python publisher/webhook_receiver.py
# Then in another terminal:
curl -X POST http://localhost:5000/slack/actions \
  -H "Content-Type: application/json" \
  -d '{"type":"block_actions"}'
```

---

## 🛠️ Tech Stack

| Component | Technology |
|-----------|-----------|
| AI Model | Google Gemini (content generation + critic) |
| News Sources | NewsAPI, RSS (feedparser), Apify |
| Approval | Slack SDK (Block Kit interactive messages) |
| Social Posting | Tweepy (Twitter API v2), LinkedIn Marketing API |
| RAG | JSON corpus with random sampling |
| Image Branding | Pillow + Gemini prompt templates |
| Orchestration | Docker Compose (3 isolated containers) |
| Web Server | Flask (webhook receiver) |
| Language | Python 3.11+ |

---

## 📄 License

Proprietary — Z5 Capital Internal Use Only.

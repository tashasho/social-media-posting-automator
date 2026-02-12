# 🤖 ClawdBot — VC Content Automation (Hardened Architecture)

> AI-powered social media content generator for Z5 Capital, built with security-first principles.

## Architecture

```
┌──────────────────────────────┐
│  🔍 Scraper (Read-Only)     │  Fetches news → /data/news.json
│  No LLM, no write access    │
└──────────────┬───────────────┘
               ▼
┌──────────────────────────────┐
│  ✍️  Writer (Sandboxed)      │  Reads news → Claude → /data/drafts/
│  Only anthropic.com access   │  Constitutional critic validation
│  Read-only root FS           │
└──────────────┬───────────────┘
               ▼
┌──────────────────────────────┐
│  📢 Publisher (Human-Gated)  │  Slack HITL → Approve → Post
│  Activated by Slack webhook  │  Twitter + LinkedIn
└──────────────────────────────┘
```

### Security Highlights

| Layer | Control |
|-------|---------|
| Container Isolation | 3 separate containers, least privilege |
| Filesystem | Read-only mounts, immutable root FS |
| Network | IPTables whitelist, internal-only writer network |
| Privilege | Non-root user, `cap_drop: ALL` |
| Approval | Slack HITL — no auto-posting possible |
| Validation | Constitutional critic agent, 3-attempt retry |

## Quick Start

```bash
# 1. Clone and configure
cp .env.example .env
# Edit .env with your API keys

# 2. Build all containers
docker compose build

# 3. Run the pipeline
docker compose up

# 4. Test locally (no Docker/API keys needed)
python test_harness/run_pipeline.py --mock
```

## Project Structure

```
clawdbot/
├── docker-compose.yml          # Orchestration
├── .env.example                # Environment template
├── scraper/                    # Container 1: News fetcher
│   ├── Dockerfile
│   ├── scraper.py
│   ├── apify_vc_scraper.py     # VC Twitter scraping via Apify
│   └── config.yaml
├── writer/                     # Container 2: AI content generation
│   ├── Dockerfile
│   ├── writer.py               # Core generation + critic
│   └── auto_curate.py          # RAG corpus quality filter
├── publisher/                  # Container 3: Human-gated posting
│   ├── Dockerfile
│   ├── webhook_receiver.py     # Flask Slack webhook handler
│   ├── slack_approval.py       # Slack interactive messages
│   └── social_poster.py        # Twitter/LinkedIn posting
├── data/
│   ├── rag/vc_corpus.json      # Curated VC writing samples
│   └── news/latest.json        # Latest news fixture
├── test_harness/               # Local pipeline simulation
│   ├── run_pipeline.py
│   ├── mock_slack.py
│   ├── test_writer.py
│   └── test_critic.py
└── firewall/
    └── setup_iptables.sh       # Network security rules
```

## Development

### Run Tests
```bash
pip install -r writer/requirements.txt -r publisher/requirements.txt pytest
python -m pytest test_harness/ -v
```

### Simulate Full Pipeline
```bash
python test_harness/run_pipeline.py --mock
```

### Test Slack Webhook Locally
```bash
python publisher/webhook_receiver.py
# In another terminal:
curl -X POST http://localhost:5000/slack/actions \
  -H "Content-Type: application/json" \
  -d '{"type":"block_actions"}'
```

## License

Proprietary — Z5 Capital Internal Use Only.

---
description: Generate a new ClawdBot post with branded Z5 visual and send to Slack
---

# ClawdBot Post Generation Workflow

This workflow generates a new AI-written post with Gemini, creates a Z5-branded visual, and sends both to Slack for approval.

## Prerequisites
- `.env` file at `/Users/bhumikamarmat/social media /clawdbot/.env` with `GEMINI_API_KEY` and `SLACK_WEBHOOK_URL`
- Brand guidelines at `/Users/bhumikamarmat/social media /clawdbot/brand/social_media_guidelines.md`

## Steps

### 1. (One-time only) Send ClawdBot Intro to Slack

**Skip this step if the intro has already been sent to the channel.**

// turbo
Send the intro message via the Slack webhook. The intro explains what ClawdBot is, how to approve (react ✅) or reject (react ❌), and what happens next. Use this exact payload shape:
```python
import os, requests, certifi
os.environ['REQUESTS_CA_BUNDLE'] = certifi.where()
# Load .env...
url = os.environ['SLACK_WEBHOOK_URL']
intro = {
    'blocks': [
        {'type': 'header', 'text': {'type': 'plain_text', 'text': '🤖 Meet ClawdBot — Your AI Social Media Assistant'}},
        {'type': 'divider'},
        {'type': 'section', 'text': {'type': 'mrkdwn', 'text': "Hey team! :wave: I'm *ClawdBot*, Z5 Capital's AI-powered social media assistant.\n\n:newspaper: I scan the latest VC, tech & startup news daily\n:black_nib: I draft insightful posts in Z5's voice using Gemini AI\n:art: I generate branded visuals following Z5's design guidelines\n:mailbox_with_mail: I send drafts here for your review before anything goes live\n\n*Nothing gets posted without your approval.*"}},
        {'type': 'divider'},
        {'type': 'section', 'text': {'type': 'mrkdwn', 'text': ":ballot_box: *How to Approve or Reject a Draft:*\n\nWhen you see a draft post, simply *react with an emoji*:\n\n>  :white_check_mark:  React with  *:white_check_mark:*  to  *APPROVE*  — the post + visual will be queued for publishing\n>\n>  :x:  React with  *:x:*  to  *REJECT*  — I'll discard it and generate a fresh one\n\nThat's it! One emoji reaction is all it takes."}},
        {'type': 'divider'},
        {'type': 'context', 'elements': [
            {'type': 'mrkdwn', 'text': ":bulb: *What happens next:* Once you approve, the post and its branded visual will be ready to publish on LinkedIn and Twitter/X. I'll keep sending fresh daily drafts for your review. You're always in control."}
        ]}
    ],
    'text': 'Meet ClawdBot — your AI social media assistant'
}
requests.post(url, json=intro, timeout=10)
```

### 2. Generate Draft with Gemini

// turbo
```bash
cd "/Users/bhumikamarmat/social media /clawdbot"
python3 -c "
import os, json, sys, warnings
warnings.filterwarnings('ignore')
from pathlib import Path
with open('.env') as f:
    for line in f:
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line: continue
        k, _, v = line.partition('=')
        if k.strip() and v.strip(): os.environ.setdefault(k.strip(), v.strip())
os.environ['CLAWDBOT_LOCAL_TEST'] = '1'
os.environ['NEWS_PATH'] = str(Path('data/news/latest.json').resolve())
os.environ['DRAFTS_PATH'] = str(Path('data/drafts').resolve())
os.environ['RAG_PATH'] = str(Path('data/rag/vc_corpus.json').resolve())
from writer.writer import generate_post
draft_file = generate_post()
if draft_file:
    with open(draft_file) as f: draft = json.load(f)
    print('DRAFT_TEXT_START')
    print(draft['text'])
    print('DRAFT_TEXT_END')
    print(f'WORD_COUNT:{draft.get(\"word_count\",0)}')
    print(f'MODEL:{draft.get(\"model\",\"?\")}')
    print(f'DRAFT_FILE:{draft_file}')
else:
    print('ERROR'); sys.exit(1)
"
```

### 3. Generate Z5-Branded Image

Use the `generate_image` tool. Auto-classify the template based on content:

| Content Type | Template | Key Visual |
|---|---|---|
| Data, funding, trends, numbers | **Data Drop** | Charcoal bg, gradient bars/charts |
| Quotes, opinions, insights | **Thought Leader** | White bg, gradient quote mark |
| Announcements, milestones | **Milestone** | Card layout, gradient border |

**Z5 Brand Rules (ALWAYS follow):**
- **Data Drop bg**: #212529 (charcoal)
- **Gradient**: Magenta #E91E63 → Violet #7B1FA2 (only on graphic elements, NEVER on text)
- **Headlines**: Montserrat ExtraBold, ALL CAPS, white on dark / charcoal on light
- **Body**: Inter Regular, sentence case
- **Z5 Logo**: Bottom-right corner, small, unobtrusive (purple/magenta Z prism)
- **Alignment**: Always left-aligned text
- **Platform sizes**: LinkedIn 4:5 portrait | Twitter 16:9 landscape | Instagram 1:1
- **Never**: Gradient on body text, multiple messages per image, stretched logos
- Reference guidelines: `/Users/bhumikamarmat/social media /clawdbot/brand/social_media_guidelines.md`

### 4. Save Image

Copy the generated image to `data/images/` in the project.

### 5. Send Draft + Visual to Slack

// turbo
Send the draft text via webhook with reaction instructions:
```python
import os, requests, certifi
os.environ['REQUESTS_CA_BUNDLE'] = certifi.where()
# Load .env...
url = os.environ['SLACK_WEBHOOK_URL']
payload = {
    'blocks': [
        {'type': 'header', 'text': {'type': 'plain_text', 'text': '📝 Draft — Ready for Review'}},
        {'type': 'divider'},
        {'type': 'section', 'text': {'type': 'mrkdwn', 'text': f"*Today's Draft:*\n\n{draft_text}"}},
        {'type': 'divider'},
        {'type': 'context', 'elements': [
            {'type': 'mrkdwn', 'text': f':newspaper: *Source:* {sources}'},
            {'type': 'mrkdwn', 'text': f':bar_chart: *Words:* {word_count} | *Model:* Gemini 2.0 Flash'},
            {'type': 'mrkdwn', 'text': ':art: *Visual:* Z5 branded image generated'},
        ]},
        {'type': 'divider'},
        {'type': 'section', 'text': {'type': 'mrkdwn', 'text': ':point_right: *React to this message:*\n\n>  :white_check_mark:  = *Approve*\n>  :x:  = *Reject*'}},
    ],
    'text': f'Draft ready for review ({word_count} words)'
}
requests.post(url, json=payload, timeout=10)
```

### 6. On Approval

If user reacts ✅ on Slack, the post + image are ready for publishing.
Run `python3 test_harness/run_pipeline.py --live --skip-linkedin --skip-twitter` to do a full pipeline test.

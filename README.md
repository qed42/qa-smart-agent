# qa-smart-agent
QA Ai Agents
# QA Smart Agent v1

AI-powered QA test case generator from Figma + Jira + User Story.
Supports OpenAI · Anthropic · Gemini — any model, any domain, any project.

---

## What it does

- Fetches Jira story in real time OR accepts plain pasted text
- Fetches Figma design frames and converts to structured doc
- Sends to AI → generates manual QA test cases
- Returns CSV + DOCX (import to Jira / TestRail / Excel)
- Backend API hides API keys from team — nobody sees the keys

---

## Folder structure

```
qa-smart-agent/
  ├── backend/
  │   ├── server.js          ← Node.js API (team calls this, never AI directly)
  │   ├── package.json       ← Node dependencies
  │   ├── .env.example       ← env template — commit this ✅
  │   └── .env               ← real keys — NEVER commit ❌
  ├── agent/
  │   ├── qa_smart_agentv1.py  ← Python CLI (direct use)
  │   ├── requirements.txt     ← Python dependencies
  │   └── INSTALL.txt          ← detailed setup guide
  ├── .gitignore
  └── README.md              ← this file
```

---

## Prerequisites

Make sure these are installed before starting:

| Tool | Version | Check | Install |
|---|---|---|---|
| Node.js | 18+ | `node --version` | https://nodejs.org |
| Python | 3.10+ | `python3 --version` | https://python.org |
| npm | 9+ | `npm --version` | comes with Node.js |
| git | any | `git --version` | https://git-scm.com |

---

## Setup — Backend API

### Step 1 — Clone the repo

```bash
git clone https://github.com/yourorg/qa-smart-agent.git
cd qa-smart-agent
```

### Step 2 — Go into backend folder

```bash
cd backend
```

### Step 3 — Install Node dependencies

```bash
npm install
```

Expected output:
```
added 120 packages in 8s
```

### Step 4 — Create your `.env` file

```bash
cp .env.example .env
```

> ⚠️ **IMPORTANT: Never commit `.env` to git. It contains real API keys.**
> Only `.env.example` (with empty values) goes to the repo.

### Step 5 — Add your API keys to `.env`

Open `.env` in any editor:

```bash
# macOS / Linux
nano .env

# Windows
notepad .env
```

Fill in your keys:

```bash
# AI Keys — add at least one
OPENAI_API_KEY=sk-proj-your-openai-key-here
ANTHROPIC_API_KEY=sk-ant-your-anthropic-key-here
GEMINI_API_KEY=your-gemini-key-here

# Figma (optional — only needed for Figma integration)
FIGMA_TOKEN=figd_your-figma-token-here

# Jira Cloud (optional — only needed for Jira integration)
JIRA_BASE_URL=https://yourcompany.atlassian.net
JIRA_EMAIL=you@yourcompany.com
JIRA_API_TOKEN=your-jira-api-token-here

# Server port (default 3000)
PORT=3000
```

#### Where to get API keys

| Key | URL |
|---|---|
| `OPENAI_API_KEY` | https://platform.openai.com/api-keys |
| `ANTHROPIC_API_KEY` | https://console.anthropic.com/settings/keys |
| `GEMINI_API_KEY` | https://aistudio.google.com/app/apikey |
| `FIGMA_TOKEN` | figma.com → Profile → Settings → Security → Personal access tokens |
| `JIRA_API_TOKEN` | https://id.atlassian.com/manage-profile/security/api-tokens |

### Step 6 — Start the backend server

```bash
node server.js
```

Expected output:
```
🚀 QA Smart Agent API — http://localhost:3000
   POST /generate-tests  — generate test cases
   GET  /models          — list supported models
   GET  /usage           — usage report
   GET  /health          — provider status
```

---

## Setup — Python Agent (direct CLI use)

If you want to run the agent directly from command line (without the backend):

### Step 1 — Go into agent folder

```bash
cd agent
```

### Step 2 — Create virtual environment

```bash
# macOS / Linux
python3 -m venv .venv
source .venv/bin/activate

# Windows
python -m venv .venv
.venv\Scripts\activate
```

### Step 3 — Install Python dependencies

```bash
pip install -r requirements.txt
```

Expected output:
```
Successfully installed anthropic openai requests Pillow google-generativeai
```

### Step 4 — Install Node docx package (for .docx output)

```bash
npm install docx
```

### Step 5 — Set environment variables

```bash
# macOS / Linux — add to ~/.zshrc or ~/.bashrc
export OPENAI_API_KEY="sk-proj-..."
export ANTHROPIC_API_KEY="sk-ant-..."
export FIGMA_TOKEN="figd_..."
export JIRA_BASE_URL="https://yourcompany.atlassian.net"
export JIRA_EMAIL="you@company.com"
export JIRA_API_TOKEN="your-token"

# Windows CMD
set OPENAI_API_KEY=sk-proj-...
set ANTHROPIC_API_KEY=sk-ant-...
```

---

## Testing — Backend API

Open a **new terminal tab** while server is running.

### Test 1 — Health check (confirms server + keys are working)

```bash
curl http://localhost:3000/health
```

Expected response:
```json
{
  "status": "ok",
  "timestamp": "2026-05-06T05:12:56.412Z",
  "providers": {
    "openai": true,
    "anthropic": true,
    "gemini": false,
    "figma": true,
    "jira": true
  }
}
```

`true` = key is set. `false` = key missing in `.env`.

### Test 2 — List supported models

```bash
curl http://localhost:3000/models
```

### Test 3 — Generate test cases (JSON response)

```bash
curl -X POST http://localhost:3000/generate-tests \
  -H "Content-Type: application/json" \
  -H "x-user-email: you@company.com" \
  -d '{
    "story": "As a user I want to login via SSO. AC: Valid credentials redirect to dashboard. Invalid credentials show error message. Empty fields show validation errors.",
    "business_context": "B2B SaaS login flow. Security is critical.",
    "model": "gpt-4o-mini",
    "story_id": "TEST-001"
  }'
```

Expected response:
```json
{
  "success": true,
  "count": 18,
  "test_cases": [...],
  "csv": "Story ID,Test Case ID,...",
  "usage": { "tokens": 4200, "cost_usd": "0.000630" }
}
```

### Test 4 — Download CSV file directly

```bash
curl -X POST http://localhost:3000/generate-tests \
  -H "Content-Type: application/json" \
  -H "Accept: text/csv" \
  -H "x-user-email: you@company.com" \
  -d '{
    "story": "As a user I want to login via SSO...",
    "model": "gpt-4o-mini",
    "story_id": "TEST-001"
  }' \
  -o my_test_cases.csv

# Open the file
open my_test_cases.csv        # macOS
start my_test_cases.csv       # Windows
xdg-open my_test_cases.csv    # Linux
```

### Test 5 — Download DOCX file directly

```bash
curl -X POST http://localhost:3000/generate-tests \
  -H "Content-Type: application/json" \
  -H "Accept: application/vnd.openxmlformats-officedocument.wordprocessingml.document" \
  -H "x-user-email: you@company.com" \
  -d '{
    "story": "As a user I want to login via SSO...",
    "model": "gpt-4o-mini",
    "story_id": "TEST-001"
  }' \
  -o my_test_cases.docx
```

### Test 6 — With Jira ticket (real-time fetch)

```bash
curl -X POST http://localhost:3000/generate-tests \
  -H "Content-Type: application/json" \
  -H "Accept: text/csv" \
  -H "x-user-email: you@company.com" \
  -d '{
    "jira_ticket": "PROJ-123",
    "model": "gpt-4o-mini"
  }' \
  -o proj123_tests.csv
```

### Test 7 — With Figma URL

```bash
curl -X POST http://localhost:3000/generate-tests \
  -H "Content-Type: application/json" \
  -H "Accept: text/csv" \
  -H "x-user-email: you@company.com" \
  -d '{
    "story": "Cart management with SKU and quantity.",
    "figma_url": "https://www.figma.com/design/FILE_KEY/Name?node-id=1318-1991",
    "frame_ids": ["1318:1991", "1330:17483"],
    "model": "gpt-4o-mini",
    "story_id": "CART-001"
  }' \
  -o cart_tests.csv
```

### Test 8 — Usage report (tokens + cost per user)

```bash
curl http://localhost:3000/usage
```

---

## Testing — Python CLI (direct use)

```bash
cd agent
source .venv/bin/activate   # Windows: .venv\Scripts\activate

# Story only
python qa_smart_agentv1.py \
  --story "As a user I want to login via SSO. AC: Valid login redirects to dashboard." \
  --model gpt-4o-mini \
  --output login_tests

# Jira ticket only
python qa_smart_agentv1.py \
  --jira-ticket PROJ-123 \
  --output proj123_tests

# Figma only
python qa_smart_agentv1.py \
  --figma-url "https://www.figma.com/design/FILE_KEY/Name?node-id=1318-1991" \
  --frame-ids "1318:1991" "1330:17483" \
  --output figma_tests

# All together — best quality
python qa_smart_agentv1.py \
  --jira-ticket PROJ-123 \
  --figma-url "https://www.figma.com/design/FILE_KEY/Name?node-id=1318-1991" \
  --frame-ids "1318:1991" "1330:17483" \
  --business "B2B e-commerce platform" \
  --model gpt-4o-mini \
  --output full_tests
```

---

## Supported AI models

| Model | Provider | Est. cost/run | Quality |
|---|---|---|---|
| `gpt-4o-mini` | OpenAI | ~$0.003 | Good ✅ recommended |
| `gpt-4o` | OpenAI | ~$0.03 | Better |
| `claude-sonnet-4-5` | Anthropic | ~$0.02 | Better |
| `claude-opus-4-5` | Anthropic | ~$0.10 | Best |
| `gemini-1.5-flash` | Gemini | ~$0.001 | Good |
| `gemini-1.5-pro` | Gemini | ~$0.01 | Better |

Change model by passing `"model": "gpt-4o"` in API request or `--model gpt-4o` in CLI.

---

## API request body — all fields

```json
{
  "story":            "plain text user story or AC (optional)",
  "jira_ticket":      "PROJ-123 (optional — fetched in real time)",
  "business_context": "domain description (optional)",
  "figma_url":        "https://figma.com/design/... (optional)",
  "frame_ids":        ["1318:1991", "1330:17483"],
  "story_id":         "PROJ-123 (used in CSV Story ID column)",
  "model":            "gpt-4o-mini"
}
```

At least one of `story`, `jira_ticket`, `business_context`, or `figma_url` is required.

---

## API response formats

| `Accept` header | Returns |
|---|---|
| `application/json` (default) | JSON with test cases + CSV string |
| `text/csv` | CSV file download |
| `application/vnd.openxmlformats-officedocument.wordprocessingml.document` | DOCX file download |

---

## CSV output columns

```
Story ID · Test Case ID · Test Scenario · Test Case Title
Module · Priority · Severity · Preconditions · Test Steps
Test Data · Expected Result · Actual Result · Status
Environment · Browser/Device · Created By · Execution Date
Comments · Coverage Type · Source Reference · Story Summary
```

---

## Troubleshooting

| Error | Fix |
|---|---|
| `Cannot find module` | Run `npm install` inside `backend/` folder |
| `ENOENT package.json` | You are in wrong folder — `cd backend` first |
| `health shows openai: false` | Add `OPENAI_API_KEY` to `.env` and restart server |
| `Jira 401` | Check `JIRA_EMAIL` and `JIRA_API_TOKEN` in `.env` |
| `Jira 404` | Ticket ID wrong — use format `PROJ-123` not `proj123` |
| `Figma 403` | Your token has no access — ask file owner to share |
| `Port 3000 in use` | Change `PORT=3001` in `.env` |
| Python `ModuleNotFoundError` | Run `pip install -r requirements.txt` |

---

## Important notes for team

- **Never share `.env` file** — contains real API keys
- **Never paste API keys in Slack, chat, or email** — revoke immediately if exposed
- **`.env.example` is safe to commit** — it has no real keys, only placeholders
- **Generated CSV/DOCX files are gitignored** — they will not be committed
- Each team member sets up their own `.env` locally with keys shared by admin

---

## Quick commands reference

```bash
# Start backend
cd backend && node server.js

# Health check
curl http://localhost:3000/health

# Generate CSV — story only
curl -X POST http://localhost:3000/generate-tests \
  -H "Content-Type: application/json" \
  -H "Accept: text/csv" \
  -H "x-user-email: you@company.com" \
  -d '{"story": "your story here", "model": "gpt-4o-mini"}' \
  -o tests.csv

# Usage report
curl http://localhost:3000/usage
```
 

 # Automation scripts from csv test cases use 2nd Command.

  qa-smart-agent % python agent/qa_automation_writer.py \                                            
  --csv ./laaha_survey_gpt4o_tests.csv \
  --repo /Users/qed42/laaha-playwright-automation \
  --create-new \
  --model gpt-4o \
  --dry-run

# 2 To create/update Automatoin files rerunt without --dry run

 --dry-run to create/update files.
(base) qed42@Mac qa-smart-agent % python agent/qa_automation_writer.py \
  --csv ./laaha_survey_gpt4o_tests.csv \
  --repo /Users/qed42/laaha-playwright-automation \
  --create-new \
  --model gpt-4o 
  
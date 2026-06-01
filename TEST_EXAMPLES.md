# QA Smart Agent — Test Examples

Practical curl examples for testing the backend API.
Run these after `node server.js` is running on `http://localhost:3000`.

---

## Health check first (always run this before testing)

```bash
curl http://localhost:3000/health
```

Expected:
```json
{
  "status": "ok",
  "providers": {
    "openai": true,
    "anthropic": true,
    "gemini": false,
    "figma": true,
    "jira": true
  }
}
```

`true` = key is set in `.env` ✅  `false` = key missing ❌

---

## Example 1 — OpenAI (gpt-4o-mini) — JSON response

```bash
curl -X POST http://localhost:3000/generate-tests \
  -H "Content-Type: application/json" \
  -H "x-user-email: nityanand@qed42.com" \
  -d '{
    "story": "Add Queue action buttons (Delete, ReIndex & Retry) to the Queue Insights Page. Users can manage items in completed or failed status. AC: Action buttons visible when items are in completed or failed status. Delete removes a particular item. ReIndex reindexes a particular item. Retry retries a failed item. Delete All deletes all items. ReIndex All reindexes all items. Retry All retries all failed items.",
    "business_context": "Queue Insights Page — manage items in completed or failed status using individual and bulk action buttons.",
    "model": "gpt-4o-mini",
    "story_id": "QUEUE-001"
  }'
```

---

## Example 2 — OpenAI — CSV download

```bash
curl -X POST http://localhost:3000/generate-tests \
  -H "Content-Type: application/json" \
  -H "Accept: text/csv" \
  -H "x-user-email: nityanand@qed42.com" \
  -d '{
    "story": "Add Queue action buttons Delete ReIndex Retry to Queue Insights Page. AC: Buttons visible for completed or failed items. Delete removes item. ReIndex reindexes item. Retry retries failed item. Delete All removes all. ReIndex All reindexes all. Retry All retries all failed.",
    "business_context": "Queue Insights Page bulk and individual action management.",
    "model": "gpt-4o-mini",
    "story_id": "QUEUE-001"
  }' \
  -o queue_openai_tests.csv

# Open the CSV
open queue_openai_tests.csv        # macOS
start queue_openai_tests.csv       # Windows
xdg-open queue_openai_tests.csv    # Linux
```

---

## Example 3 — Anthropic (claude-sonnet-4-5) — JSON response

> Requires `ANTHROPIC_API_KEY` in `.env`

```bash
curl -X POST http://localhost:3000/generate-tests \
  -H "Content-Type: application/json" \
  -H "x-user-email: nityanand@qed42.com" \
  -d '{
    "story": "Add Queue action buttons Delete ReIndex Retry to Queue Insights Page. AC: Buttons visible for completed or failed items. Delete removes item. ReIndex reindexes. Retry retries failed. Delete All, ReIndex All, Retry All for bulk actions.",
    "business_context": "Queue Insights Page — individual and bulk action management.",
    "model": "claude-sonnet-4-5",
    "story_id": "QUEUE-001"
  }'
```

---

## Example 4 — Anthropic — CSV download

```bash
curl -X POST http://localhost:3000/generate-tests \
  -H "Content-Type: application/json" \
  -H "Accept: text/csv" \
  -H "x-user-email: nityanand@qed42.com" \
  -d '{
    "story": "Add Queue action buttons Delete ReIndex Retry to Queue Insights Page. AC: Buttons visible for completed or failed items. Delete removes item. ReIndex reindexes. Retry retries failed. Delete All, ReIndex All, Retry All for bulk actions.",
    "business_context": "Queue Insights Page — individual and bulk action management.",
    "model": "claude-sonnet-4-5",
    "story_id": "QUEUE-001"
  }' \
  -o queue_anthropic_tests.csv

open queue_anthropic_tests.csv
```

---

## Example 5 — Anthropic (claude-opus-4-5) — best quality

```bash
curl -X POST http://localhost:3000/generate-tests \
  -H "Content-Type: application/json" \
  -H "Accept: text/csv" \
  -H "x-user-email: nityanand@qed42.com" \
  -d '{
    "story": "Add Queue action buttons Delete ReIndex Retry to Queue Insights Page. AC: Buttons visible for completed or failed items. Delete removes item. ReIndex reindexes. Retry retries failed. Delete All, ReIndex All, Retry All for bulk actions.",
    "business_context": "Queue Insights Page — individual and bulk action management.",
    "model": "claude-opus-4-5",
    "story_id": "QUEUE-001"
  }' \
  -o queue_opus_tests.csv

open queue_opus_tests.csv
```

---

## Example 6 — Gemini (gemini-1.5-flash) — cheapest overall

> Requires `GEMINI_API_KEY` in `.env`

```bash
curl -X POST http://localhost:3000/generate-tests \
  -H "Content-Type: application/json" \
  -H "Accept: text/csv" \
  -H "x-user-email: nityanand@qed42.com" \
  -d '{
    "story": "Add Queue action buttons Delete ReIndex Retry to Queue Insights Page. AC: Buttons visible for completed or failed items. Delete removes item. ReIndex reindexes. Retry retries failed.",
    "model": "gemini-1.5-flash",
    "story_id": "QUEUE-001"
  }' \
  -o queue_gemini_tests.csv

open queue_gemini_tests.csv
```

---

## Example 7 — Jira ticket (real-time fetch) + model

> Requires `JIRA_BASE_URL`, `JIRA_EMAIL`, `JIRA_API_TOKEN` in `.env`

```bash
curl -X POST http://localhost:3000/generate-tests \
  -H "Content-Type: application/json" \
  -H "Accept: text/csv" \
  -H "x-user-email: nityanand@qed42.com" \
  -d '{
    "jira_ticket": "PROJ-123",
    "model": "gpt-4o-mini",
    "story_id": "PROJ-123"
  }' \
  -o proj123_tests.csv

open proj123_tests.csv
```

---

## Example 8 — Story + Figma frames

> Requires `FIGMA_TOKEN` in `.env`

```bash
curl -X POST http://localhost:3000/generate-tests \
  -H "Content-Type: application/json" \
  -H "Accept: text/csv" \
  -H "x-user-email: nityanand@qed42.com" \
  -d '{
    "story": "Cart management — add items by SKU with quantity min 1 max 1000.",
    "figma_url": "https://www.figma.com/design/FILE_KEY/Name?node-id=1318-1991",
    "frame_ids": ["1318:1991", "1330:17483"],
    "business_context": "B2B e-commerce cart.",
    "model": "gpt-4o-mini",
    "story_id": "CART-001"
  }' \
  -o cart_tests.csv

open cart_tests.csv
```

---

## Example 9 — DOCX download

```bash
curl -X POST http://localhost:3000/generate-tests \
  -H "Content-Type: application/json" \
  -H "Accept: application/vnd.openxmlformats-officedocument.wordprocessingml.document" \
  -H "x-user-email: nityanand@qed42.com" \
  -d '{
    "story": "Add Queue action buttons Delete ReIndex Retry...",
    "model": "gpt-4o-mini",
    "story_id": "QUEUE-001"
  }' \
  -o queue_tests.docx

open queue_tests.docx
```

---

## Model options — change `"model"` field only

```bash
# OpenAI — cheapest ✅ recommended for most runs
"model": "gpt-4o-mini"

# OpenAI — better quality
"model": "gpt-4o"

# Anthropic — balanced (add ANTHROPIC_API_KEY to .env)
"model": "claude-sonnet-4-5"

# Anthropic — best quality, higher cost
"model": "claude-opus-4-5"

# Gemini — very cheap (add GEMINI_API_KEY to .env)
"model": "gemini-1.5-flash"

# Gemini — better quality
"model": "gemini-1.5-pro"
```

---

## Usage report — tokens and cost per user

```bash
curl http://localhost:3000/usage
```

Expected:
```json
{
  "total_requests": 12,
  "total_cost_usd": "0.0234",
  "by_user": {
    "nityanand@qed42.com": {
      "requests": 8,
      "tokens": 36000,
      "cost": 0.014,
      "tests_generated": 144
    }
  }
}
```

---

## List all supported models

```bash
curl http://localhost:3000/models
```

---

## Quick cost reference

| Model | Est. cost per run |
|---|---|
| `gpt-4o-mini` | ~$0.003 |
| `gemini-1.5-flash` | ~$0.001 |
| `gpt-4o` | ~$0.03 |
| `claude-sonnet-4-5` | ~$0.02 |
| `gemini-1.5-pro` | ~$0.01 |
| `claude-opus-4-5` | ~$0.10 |

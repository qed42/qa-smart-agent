# QA Smart Agent v2 — 80% Quality Gate Upgrade

This version keeps the existing QA Smart Agent input/output contract but improves the quality of generated test cases.

## What changed

### 1. Embedded test-case generation skill rules

The agent now follows a reusable QA skill-style prompt inspired by test-case generation skills:

- Requirement-driven coverage
- Traceability from requirement/AC to test case
- Functional, negative, edge/error, state transition, and regression-sensitive coverage
- Pragmatic quality over quantity
- Compact test suite generation

### 2. Compact 10+ years QA style

The previous prompt allowed 15–25 test cases, which can create too many basic cases.

v2 changes this to:

- Normal story: **8–14 strong test cases**
- Complex story: **15–20 only when needed**
- Merge similar field/value checks using EP/BVA
- Avoid static label/heading/decorative UI test cases
- Prefer business-flow and risk-based scenarios

### 3. Local 80% quality evaluator

After AI generates test cases, the agent runs a deterministic quality gate.

Scoring areas:

| Area | Points |
|---|---:|
| Schema + executable steps | 20 |
| Coverage mix | 25 |
| Compactness / duplicate avoidance | 20 |
| Traceability | 20 |
| QA judgment / risk coverage | 15 |
| **Total** | **100** |

If score is below **80**, the agent asks the same model to revise once.

### 4. No regression to current CSV/API output

The CSV columns are unchanged.

The JSON response is backward compatible. It still returns:

```json
{
  "success": true,
  "count": 12,
  "test_cases": [],
  "csv": "...",
  "usage": {}
}
```

v2 additionally returns:

```json
"quality": {
  "score": 86,
  "passed": true,
  "issues": [],
  "breakdown": {}
}
```

Existing consumers can ignore this new field.

## Files

Use these as drop-in upgraded versions:

- `qa_smart_agentv2.py`
- `server_v2.js`

## Python CLI usage

```bash
python qa_smart_agentv2.py \
  --story "As a user I want to login via SSO. AC: Valid credentials redirect to dashboard. Invalid credentials show error message. Empty fields show validation errors." \
  --model gpt-4o-mini \
  --output login_tests_v2
```

## Backend usage

```bash
node server_v2.js
```

Then call the same API:

```bash
curl -X POST http://localhost:3000/generate-tests \
  -H "Content-Type: application/json" \
  -H "x-user-email: you@company.com" \
  -d '{
    "story": "Add Queue action buttons Delete ReIndex Retry to Queue Insights Page. AC: Buttons visible for completed or failed items. Delete removes item. ReIndex reindexes item. Retry retries failed item. Delete All removes all items. ReIndex All reindexes all items. Retry All retries all failed items.",
    "business_context": "Queue Insights Page — manage completed or failed queue items using individual and bulk actions.",
    "model": "gpt-4o-mini",
    "story_id": "QUEUE-001"
  }'
```

## Claude skills recommendation

Using Claude skills can help, but do not depend on a Claude-only runtime.

Best approach:

- Keep the QA agent as the orchestrator.
- Use skill rules as embedded reusable instructions.
- Allow Claude Sonnet/Opus as model options for higher quality.
- Keep OpenAI/Gemini support so the project remains model-independent.
- Add local quality evaluation so the output quality does not depend only on the prompt.

This is why v2 embeds the useful skill behavior inside the agent and adds a deterministic 80% quality gate.

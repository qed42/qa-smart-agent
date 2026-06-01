"""
╔══════════════════════════════════════════════════════════════╗
║         QA SMART AGENT — Figma + Jira + Business            ║
║                                                              ║
║  Flexible inputs — any combination works:                    ║
║    - Figma only                                              ║
║    - Jira ticket only                                        ║
║    - Business context only                                   ║
║    - All three together (best quality)                       ║
║                                                              ║
║  AI models supported:                                        ║
║    - OpenAI  : gpt-4o-mini, gpt-4o                          ║
║    - Anthropic: claude-opus-4-5, claude-sonnet-4-5           ║
║                                                              ║
║  Usage:                                                      ║
║    python qa_smart_agent.py --jira-ticket PROJ-123           ║
║    python qa_smart_agent.py --figma-url "..." --frame-ids "."║
║    python qa_smart_agent.py --jira-ticket PROJ-123           ║
║      --figma-url "..." --frame-ids "..." --business "..."    ║
║                                                              ║
║  Requirements:                                               ║
║    pip install openai anthropic requests                     ║
║    npm install docx                                          ║
║                                                              ║
║  Environment variables:                                      ║
║    FIGMA_TOKEN       — Figma personal access token           ║
║    JIRA_BASE_URL     — https://yourcompany.atlassian.net     ║
║    JIRA_EMAIL        — your Jira login email                 ║
║    JIRA_API_TOKEN    — Jira API token (from atlassian.net)   ║
║    OPENAI_API_KEY    — OpenAI API key (if using OpenAI)      ║
║    ANTHROPIC_API_KEY — Anthropic API key (if using Claude)   ║
╚══════════════════════════════════════════════════════════════╝
"""

import os
import re
import io
import csv
import json
import time
import base64
import argparse
import textwrap
import subprocess
from datetime import datetime
from urllib.parse import urlparse, parse_qs

import requests


# ─────────────────────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────────────────────

FIGMA_TOKEN    = os.environ.get("FIGMA_TOKEN", "")
JIRA_BASE_URL  = os.environ.get("JIRA_BASE_URL", "").rstrip("/")
JIRA_EMAIL     = os.environ.get("JIRA_EMAIL", "")
JIRA_API_TOKEN = os.environ.get("JIRA_API_TOKEN", "")
OPENAI_KEY     = os.environ.get("OPENAI_API_KEY", "")
ANTHROPIC_KEY  = os.environ.get("ANTHROPIC_API_KEY", "")

FIGMA_BASE          = "https://api.figma.com/v1"
MAX_IMAGE_SIZE_KB   = 4500
MAX_IMAGE_DIMENSION = 1920
JPEG_QUALITY        = 85
BATCH_SIZE          = 3

# Supported models
OPENAI_MODELS    = ["gpt-4o-mini", "gpt-4o", "gpt-4-turbo"]
ANTHROPIC_MODELS = ["claude-opus-4-5", "claude-sonnet-4-5", "claude-haiku-4-5-20251001"]

# Noise node names to skip during extraction
_SKIP_NAMES = {
    "", "vector", "rectangle", "ellipse", "line", "polygon",
    "star", "union", "subtract", "intersect", "exclude",
    "mask", "boolean operation", "slice", "arrow",
}
_UI_TYPES = {"FRAME", "COMPONENT", "INSTANCE", "GROUP", "TEXT"}

# CSV columns matching QA template
CSV_FIELDS = [
    "Story ID", "Test Case ID", "Test Scenario", "Test Case Title",
    "Module", "Priority", "Severity", "Preconditions", "Test Steps",
    "Test Data", "Expected Result", "Actual Result", "Status",
    "Environment", "Browser/Device", "Created By", "Execution Date",
    "Comments", "Coverage Type", "Source Reference", "Story Summary",
]


# ─────────────────────────────────────────────────────────────
# JIRA — fetch story in real time
# ─────────────────────────────────────────────────────────────

def fetch_jira_story(ticket_id: str) -> dict:
    """
    Fetch a Jira ticket from Jira Cloud in real time.
    Returns a dict with: id, summary, description, acceptance_criteria,
    story_type, priority, labels, components, status
    """
    if not JIRA_BASE_URL:
        raise EnvironmentError("JIRA_BASE_URL not set. e.g. https://yourcompany.atlassian.net")
    if not JIRA_EMAIL or not JIRA_API_TOKEN:
        raise EnvironmentError("JIRA_EMAIL and JIRA_API_TOKEN must be set.")

    url     = f"{JIRA_BASE_URL}/rest/api/3/issue/{ticket_id}"
    auth    = (JIRA_EMAIL, JIRA_API_TOKEN)
    headers = {"Accept": "application/json"}

    print(f"  Fetching Jira ticket: {ticket_id}...")

    for attempt in range(3):
        try:
            r = requests.get(url, auth=auth, headers=headers, timeout=30)
        except requests.exceptions.Timeout:
            print(f"  ⏱  Jira timeout (attempt {attempt+1}/3), retrying...")
            time.sleep(3)
            continue

        if r.status_code == 401:
            raise PermissionError(
                "Jira 401 — check JIRA_EMAIL and JIRA_API_TOKEN.\n"
                "Get your token at: https://id.atlassian.com/manage-profile/security/api-tokens"
            )
        if r.status_code == 404:
            raise ValueError(f"Jira ticket '{ticket_id}' not found. Check the ticket ID.")

        r.raise_for_status()
        data = r.json()
        break
    else:
        raise RuntimeError("Jira API failed after 3 attempts.")

    fields = data.get("fields", {})

    # Extract acceptance criteria — stored in different fields depending on Jira config
    ac = _extract_acceptance_criteria(fields)

    # Extract description text
    description = _extract_adf_text(fields.get("description") or {})

    story = {
        "id":                   ticket_id,
        "summary":              fields.get("summary", ""),
        "description":          description,
        "acceptance_criteria":  ac,
        "story_type":           fields.get("issuetype", {}).get("name", "Story"),
        "priority":             fields.get("priority", {}).get("name", "Medium"),
        "status":               fields.get("status", {}).get("name", ""),
        "labels":               fields.get("labels", []),
        "components":           [c.get("name") for c in fields.get("components", [])],
        "assignee":             (fields.get("assignee") or {}).get("displayName", ""),
        "reporter":             (fields.get("reporter") or {}).get("displayName", ""),
    }

    print(f"  ✅ Jira: [{ticket_id}] {story['summary'][:60]}")
    if story["acceptance_criteria"]:
        print(f"     AC found: {len(story['acceptance_criteria'].splitlines())} lines")
    else:
        print(f"     No AC found — will infer from description and Figma")

    return story


def _extract_acceptance_criteria(fields: dict) -> str:
    """
    Try multiple common Jira field names for acceptance criteria.
    Different Jira setups store AC in different custom fields.
    """
    # Common custom field names for AC
    ac_field_names = [
        "customfield_10016",   # Acceptance Criteria (most common)
        "customfield_10014",
        "customfield_10028",
        "acceptance_criteria",
        "customfield_10034",
    ]

    for field_name in ac_field_names:
        val = fields.get(field_name)
        if val:
            if isinstance(val, str):
                return val
            if isinstance(val, dict):
                return _extract_adf_text(val)

    # Fallback — look in description for "Acceptance Criteria" section
    desc = _extract_adf_text(fields.get("description") or {})
    if "acceptance criteria" in desc.lower():
        lines     = desc.splitlines()
        ac_lines  = []
        capturing = False
        for line in lines:
            if "acceptance criteria" in line.lower():
                capturing = True
                continue
            if capturing:
                if line.strip() and any(kw in line.lower() for kw in ["definition of done", "notes:", "technical"]):
                    break
                ac_lines.append(line)
        if ac_lines:
            return "\n".join(ac_lines).strip()

    return ""


def _extract_adf_text(adf: dict) -> str:
    """
    Extract plain text from Atlassian Document Format (ADF) JSON.
    Jira Cloud stores rich text as ADF — this converts it to plain text.
    """
    if not adf or not isinstance(adf, dict):
        return ""

    parts = []

    def _walk(node):
        if not isinstance(node, dict):
            return
        node_type = node.get("type", "")
        text      = node.get("text", "")

        if text:
            parts.append(text)
        elif node_type in ("hardBreak", "rule"):
            parts.append("\n")
        elif node_type in ("paragraph", "heading", "bulletList", "orderedList"):
            parts.append("\n")

        for child in node.get("content", []):
            _walk(child)

        if node_type in ("listItem",):
            parts.append("\n")

    _walk(adf)
    return " ".join(parts).strip()


def format_jira_for_prompt(story: dict) -> str:
    """Format Jira story data into a clean prompt section."""
    lines = [
        f"Ticket: {story['id']}",
        f"Type: {story['story_type']}",
        f"Priority: {story['priority']}",
        f"Status: {story['status']}",
        f"Summary: {story['summary']}",
    ]

    if story.get("components"):
        lines.append(f"Components: {', '.join(story['components'])}")

    if story.get("labels"):
        lines.append(f"Labels: {', '.join(story['labels'])}")

    if story.get("description"):
        lines.append(f"\nDescription:\n{story['description'][:1000]}")

    if story.get("acceptance_criteria"):
        lines.append(f"\nAcceptance Criteria:\n{story['acceptance_criteria'][:2000]}")

    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────
# FIGMA — fetch metadata (optional)
# ─────────────────────────────────────────────────────────────

def parse_figma_url(url: str) -> tuple:
    match = re.search(r"figma\.com/(?:design|file)/([^/?]+)", url)
    if not match:
        raise ValueError(f"Cannot parse Figma file key from: {url}")
    file_key = match.group(1)
    params   = parse_qs(urlparse(url).query)
    node_raw = params.get("node-id", [None])[0]
    node_id  = node_raw.replace("-", ":") if node_raw else None
    return file_key, node_id


def figma_get(endpoint: str, params: dict = None) -> dict:
    headers = {"X-Figma-Token": FIGMA_TOKEN}
    url     = f"{FIGMA_BASE}{endpoint}"

    for attempt in range(4):
        try:
            r = requests.get(url, headers=headers, params=params, timeout=90)
        except requests.exceptions.Timeout:
            print(f"  ⏱  Figma timeout (attempt {attempt+1}/4)...")
            time.sleep(5 * (attempt + 1))
            continue

        if r.status_code == 429:
            wait = 2 ** attempt * 5
            print(f"  ⚠️  Figma rate limited — waiting {wait}s...")
            time.sleep(wait)
            continue

        if r.status_code == 403:
            raise PermissionError("Figma 403 — check FIGMA_TOKEN and file access.")

        r.raise_for_status()
        return r.json()

    raise RuntimeError("Figma API failed after 4 attempts.")


def fetch_figma_metadata(file_key: str, node_ids: list) -> dict:
    ids_param = ",".join(node_ids)
    print(f"  Fetching Figma metadata for {len(node_ids)} frame(s)...")
    data   = figma_get(f"/files/{file_key}/nodes", params={"ids": ids_param, "depth": 2})
    result = {}
    for nid, wrapper in data.get("nodes", {}).items():
        result[nid] = _extract_node(wrapper.get("document", {}))
    return result


def _extract_node(node: dict, depth: int = 0) -> dict:
    name  = node.get("name", "").strip()
    ntype = node.get("type", "")
    ext   = {"name": name, "type": ntype}

    if ntype == "TEXT":
        text = node.get("characters", "").strip()
        if text:
            ext["text"] = text[:200]

    interactions = node.get("interactions", [])
    if interactions:
        links = []
        for ia in interactions:
            trigger = ia.get("trigger", {}).get("type", "")
            for action in ia.get("actions", []):
                dest = action.get("destinationId", "")
                if dest:
                    links.append({"trigger": trigger, "dest": dest})
        if links:
            ext["interactions"] = links

    children = node.get("children", [])
    if children and depth < 2:
        kept = []
        for child in children:
            cname = child.get("name", "").strip().lower()
            ctype = child.get("type", "")
            if cname in _SKIP_NAMES or ctype not in _UI_TYPES:
                continue
            cd = _extract_node(child, depth + 1)
            if cd.get("text") or cd.get("interactions") or cd.get("children"):
                kept.append(cd)
            elif cname and ctype in ("COMPONENT", "INSTANCE", "FRAME"):
                kept.append({"name": cd["name"], "type": ctype})
        if kept:
            ext["children"] = kept

    return ext


def build_flow_map(metadata: dict) -> str:
    lines = []

    def _walk(node, parent=""):
        name = node.get("name", parent)
        for ia in node.get("interactions", []):
            trigger = ia.get("trigger", "")
            dest    = ia.get("dest", "")
            if dest:
                lines.append(f"  {name} --[{trigger}]--> Frame {dest}")
        for child in node.get("children", []):
            _walk(child, name)

    for nid, node in metadata.items():
        lines.append(f"[Frame {nid}: {node.get('name', '')}]")
        _walk(node)

    return "\n".join(lines) if lines else "No prototype links found."


def metadata_to_markdown(metadata: dict, flow_map: str) -> str:
    """Convert Figma metadata to structured markdown — replaces images."""
    lines = ["## Figma design structure\n"]
    lines.append("### Screen navigation flow")
    lines.append("```")
    lines.append(flow_map)
    lines.append("```\n")
    lines.append("### Screen components\n")

    for frame_id, node in metadata.items():
        screen_name = node.get("name", frame_id)
        lines.append(f"#### Screen: {screen_name} (Frame {frame_id})")

        components  = []
        texts       = []
        interactions = []
        _flatten_node(node, components, texts, interactions, "")

        if components:
            lines.append("UI components:")
            for c in components:
                state = f" [{c['state']}]" if c['state'] else ""
                lines.append(f"- {c['name']} ({c['type']}){state}")

        if texts:
            lines.append("\nText content:")
            for t in texts:
                lines.append(f"- {t}")

        if interactions:
            lines.append("\nInteractions:")
            for i in interactions:
                lines.append(f"- {i['component']} → {i['trigger']} → Frame {i['dest']}")

        lines.append("")

    return "\n".join(lines)


def _flatten_node(node, components, texts, interactions, parent_name):
    name  = node.get("name", "")
    ntype = node.get("type", "")

    if ntype in ("FRAME", "COMPONENT", "INSTANCE", "GROUP") and name:
        state = ""
        nl    = name.lower()
        if "hover"    in nl: state = "hover"
        elif "focus"  in nl: state = "focus"
        elif "error"  in nl: state = "error state"
        elif "disabl" in nl: state = "disabled"
        elif "active" in nl: state = "active"
        elif "empty"  in nl: state = "empty state"
        components.append({"name": name, "type": ntype, "state": state})

    if ntype == "TEXT" and node.get("text"):
        t = node.get("text", "").strip()
        if t and t not in texts:
            texts.append(t)

    for ia in node.get("interactions", []):
        trigger = ia.get("trigger", "")
        dest    = ia.get("dest", "")
        if dest:
            interactions.append({"component": name or parent_name, "trigger": trigger, "dest": dest})

    for child in node.get("children", []):
        _flatten_node(child, components, texts, interactions, name)



# ─────────────────────────────────────────────────────────────
# PLAIN TEXT STORY — extract AC from pasted text
# ─────────────────────────────────────────────────────────────

def _extract_ac_from_plain_text(text: str) -> str:
    """
    Try to extract acceptance criteria from plain pasted story text.
    Looks for common AC patterns:
      - Lines starting with AC:, Given/When/Then, "As a user..."
      - Bullet points after "Acceptance Criteria" heading
    """
    lines     = text.splitlines()
    ac_lines  = []
    capturing = False

    for line in lines:
        ll = line.strip().lower()

        # Start capturing after AC heading
        if any(kw in ll for kw in ["acceptance criteria", "ac:", "given ", "when ", "then "]):
            capturing = True

        # Stop at next section
        if capturing and ll and any(kw in ll for kw in ["definition of done", "notes:", "technical notes", "out of scope"]):
            break

        if capturing and line.strip():
            ac_lines.append(line.strip())

    if ac_lines:
        return "\n".join(ac_lines)

    # Fallback — return full text, AI will figure it out
    return text


# ─────────────────────────────────────────────────────────────
# BUILD PROMPT — combines all available context
# ─────────────────────────────────────────────────────────────

def build_prompt(
    figma_doc:        str,
    jira_story:       dict,
    business_context: str,
    story_id:         str,
) -> tuple[str, str]:
    """
    Build system + user prompt using whatever context is available.
    Returns (system_prompt, user_prompt).

    v2 quality update:
      - Claude Skill-style testing instructions are embedded as reusable rules.
      - Output stays backward-compatible with the existing CSV fields.
      - Focus is compact, high-value coverage rather than many basic cases.
    """
    sid = story_id or (jira_story.get("id") if jira_story else "") or "QA-001"

    system_prompt = textwrap.dedent("""
    You are a senior QA engineer with 10+ years experience and a pragmatic test-case generation skill.

    PRIMARY OBJECTIVE
    Generate compact, requirement-driven, execution-ready manual test cases with >=80/100 quality.
    Prefer fewer high-value tests that cover multiple related checks over many small/basic tests.

    CORE TESTING PRINCIPLES
    - Test what matters: user value, business rules, integrations, data/state changes, errors, permissions, and recovery.
    - Every requirement/AC must be covered by at least one test case.
    - One test case may cover multiple related acceptance checks when the flow is naturally connected.
    - Avoid duplicate/basic cases like separate tests for every label, heading, or static text.
    - Skip static decorative UI unless it impacts compliance, navigation, accessibility, or user decision making.
    - Use Black Box testing, Boundary Value Analysis, Equivalence Partitioning, State Transition, and risk-based prioritization.
    - Include positive, negative, edge/error, state transition, and regression-sensitive coverage.
    - Keep steps executable and expected results measurable.

    COMPACT COVERAGE RULES
    - Target 8-14 strong test cases for a normal story.
    - Use 15-20 only for genuinely complex flows with many roles/states/integrations.
    - Combine similar validation checks into one parameterized/EP test case.
    - Do not create one test case per field/value/button unless the behavior or risk is different.
    - Prefer business journey tests, not checklist-style noise.

    REQUIRED QUALITY BAR
    The generated set must pass this internal 80+ rubric:
    - Requirement / AC coverage and traceability: 25
    - Real QA judgment and risk coverage: 20
    - Compactness with no duplicate/basic tests: 15
    - Executable steps and measurable expected results: 15
    - Negative / edge / state transition coverage: 15
    - CSV/schema compliance: 10

    STRICT OUTPUT RULES
    - Return ONLY valid JSON array.
    - No markdown, no explanation, no preamble.
    - Use exactly the requested field names.
    """).strip()

    # ── Build context sections ──
    sections = []

    # Jira story section
    if jira_story:
        sections.append(f"""
JIRA STORY / USER STORY
{'-'*40}
{format_jira_for_prompt(jira_story)}
""")
    else:
        sections.append(f"""
JIRA STORY / USER STORY
{'-'*40}
Not provided — infer acceptance criteria from Figma design and business context.
""")

    # Business context section
    if business_context and business_context.strip().lower() not in ("refer figma", ""):
        sections.append(f"""
BUSINESS CONTEXT
{'-'*40}
{business_context.strip()}
""")
    else:
        sections.append(f"""
BUSINESS CONTEXT
{'-'*40}
Not provided — infer from story, Figma components, text labels, and screen names.
""")

    # Figma doc section
    if figma_doc:
        sections.append(f"""
FIGMA DESIGN DOCUMENT
{'-'*40}
{figma_doc[:8000]}
""")
    else:
        sections.append(f"""
FIGMA DESIGN
{'-'*40}
Not provided — generate test cases based on story and business context only.
""")

    context = "\n".join(sections)

    # ── Detect what's available for smarter instructions ──
    has_figma   = bool(figma_doc)
    has_jira    = bool(jira_story and jira_story.get("summary"))
    has_biz     = bool(business_context and business_context.strip().lower() not in ("refer figma", ""))

    if not has_jira and not has_biz and has_figma:
        inference_note = """
IMPORTANT: No story or business context provided.
Act as a human QA analyst — read the Figma doc, infer the business domain from
component names and screen flow, self-generate acceptance criteria,
then apply BVA + EP + Black Box to generate compact high-value test cases.
"""
    elif has_jira and not has_figma:
        inference_note = """
IMPORTANT: No Figma design provided.
Generate test cases from the story and acceptance criteria.
Cover all AC points with compact positive, negative, edge, and state scenarios.
"""
    else:
        inference_note = """
Use ALL provided context together.
Story/AC = what to test. Figma = how the UI behaves. Business context = domain rules.
"""
    user_prompt = textwrap.dedent(f"""
    {context}

    {inference_note}

    TASK
    Generate a compact high-quality test suite, not a large basic checklist.

    COVERAGE EXPECTATIONS
    1. Functional happy path and key user journey.
    2. Requirement-to-test traceability through Source Reference and Comments.
    3. Negative and validation paths grouped using Equivalence Partitioning.
    4. Boundary values only where limits are present or can be reasonably inferred.
    5. State transitions such as empty → selected/filled → submitted → success/error → retry/cancel.
    6. Permission/role checks only when the story implies role/status restrictions.
    7. Regression-sensitive checks for existing behavior that could break.

    DEDUPLICATION RULES
    - Do not create separate tests for each static label, heading, or visual-only element.
    - Merge related button visibility/action checks into a single scenario when they share the same precondition.
    - Merge invalid input cases into one EP/BVA scenario where possible.
    - Each test case must explain why it matters through scenario, expected result, and comments.

    Return ONLY a valid JSON array. Each object MUST have EXACTLY these fields:
    {{
      "Story ID":        "{sid}",
      "Test Case ID":    "TC_001",
      "Test Scenario":   "brief scenario description",
      "Test Case Title": "clear concise test case title",
      "Module":          "feature module name",
      "Priority":        "High | Medium | Low",
      "Severity":        "Critical | Major | Minor | Trivial",
      "Preconditions":   "what must be true before test",
      "Test Steps":      "1. step one\\n2. step two\\n3. step three",
      "Test Data":       "specific test data, EP set, or BVA values",
      "Expected Result": "exact expected outcome",
      "Actual Result":   "",
      "Status":          "Not Executed",
      "Environment":     "Stage",
      "Browser/Device":  "Chrome / Desktop",
      "Created By":      "QA Agent",
      "Execution Date":  "",
      "Comments":        "Req/AC coverage note + why this test matters",
      "Coverage Type":   "Functional | UI | Negative | Edge Case | State Transition | Regression",
      "Source Reference":"{sid} | AC/REQ references covered",
      "Story Summary":   "one-line summary of what this feature does"
    }}

    Final self-check before returning:
    - Is every AC/requirement covered?
    - Are basic/static-only tests removed?
    - Are similar cases merged?
    - Would a 10+ years QA lead accept this as >=80/100?
    - Is the response valid JSON array only?
    """).strip()

    return system_prompt, user_prompt



# ─────────────────────────────────────────────────────────────
# AI CALL — supports OpenAI and Anthropic
# ─────────────────────────────────────────────────────────────

def call_ai(system_prompt: str, user_prompt: str, model: str) -> str:
    """Route to correct AI provider based on model name."""
    model_lower = model.lower()

    if any(m in model_lower for m in ["gpt", "o1", "o3"]):
        return _call_openai(system_prompt, user_prompt, model)
    elif any(m in model_lower for m in ["claude", "anthropic"]):
        return _call_anthropic(system_prompt, user_prompt, model)
    else:
        raise ValueError(
            f"Unknown model '{model}'.\n"
            f"OpenAI models: {OPENAI_MODELS}\n"
            f"Anthropic models: {ANTHROPIC_MODELS}"
        )


def _call_openai(system_prompt: str, user_prompt: str, model: str) -> str:
    if not OPENAI_KEY:
        raise EnvironmentError("OPENAI_API_KEY not set.")

    from openai import OpenAI
    client = OpenAI(api_key=OPENAI_KEY)

    token_est = (len(system_prompt) + len(user_prompt)) // 4
    print(f"  Calling OpenAI {model} (~{token_est} tokens)...")
    print(f"  Est. cost: ~${token_est * 0.00000015:.4f}")

    for attempt in range(3):
        try:
            response = client.chat.completions.create(
                model       = model,
                max_tokens  = 16000,
                temperature = 0,
                messages    = [
                    {"role": "system", "content": system_prompt},
                    {"role": "user",   "content": user_prompt},
                ],
            )
            raw = response.choices[0].message.content.strip()
            print(f"  ✅ OpenAI responded — {response.usage.total_tokens} tokens used")
            print(f"  💰 Actual cost: ~${response.usage.total_tokens * 0.00000015:.4f}")
            return raw
        except Exception as e:
            if attempt == 2:
                raise
            print(f"  ⚠️  Attempt {attempt+1} failed: {e}. Retrying in 5s...")
            time.sleep(5)


def _call_anthropic(system_prompt: str, user_prompt: str, model: str) -> str:
    if not ANTHROPIC_KEY:
        raise EnvironmentError("ANTHROPIC_API_KEY not set.")

    import anthropic
    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)

    token_est = (len(system_prompt) + len(user_prompt)) // 4
    print(f"  Calling Anthropic {model} (~{token_est} tokens)...")

    for attempt in range(3):
        try:
            response = client.messages.create(
                model      = model,
                max_tokens = 16000,
                system     = system_prompt,
                messages   = [{"role": "user", "content": user_prompt}],
            )
            raw = response.content[0].text.strip()
            print(f"  ✅ Claude responded")
            return raw
        except Exception as e:
            if attempt == 2:
                raise
            print(f"  ⚠️  Attempt {attempt+1} failed: {e}. Retrying in 5s...")
            time.sleep(5)


def parse_ai_response(raw: str) -> list:
    """Parse JSON from AI response, with truncation recovery."""
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw).strip()

    if raw and not raw.rstrip().endswith("]"):
        last_good = raw.rfind("},")
        if last_good > 0:
            raw = raw[:last_good+1] + "\n]"
            print(f"  ⚠️  Truncated JSON recovered")

    test_cases = json.loads(raw)

    for i, tc in enumerate(test_cases):
        tc["Test Case ID"] = f"TC_{i+1:03d}"

    return test_cases


# ─────────────────────────────────────────────────────────────
# SAVE — CSV + Markdown
# ─────────────────────────────────────────────────────────────

def save_to_csv(test_cases: list, output_path: str):
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for tc in test_cases:
            row = {}
            for field in CSV_FIELDS:
                val = tc.get(field, "")
                if isinstance(val, list):
                    val = "\n".join(f"{i+1}. {s}" for i, s in enumerate(val))
                row[field] = val
            writer.writerow(row)


def save_markdown(content: str, path: str):
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"  ✅ Markdown: {path} (~{len(content)//4} tokens)")


def print_summary(test_cases: list, outputs: dict):
    priority = {}
    coverage = {}
    for tc in test_cases:
        p = tc.get("Priority", "?")
        c = tc.get("Coverage Type", "?")
        priority[p] = priority.get(p, 0) + 1
        coverage[c] = coverage.get(c, 0) + 1

    print("\n" + "─" * 55)
    print(f"  Total test cases : {len(test_cases)}")
    for label, path in outputs.items():
        if path:
            print(f"  {label:<18}: {path}")
    print("  By Priority:")
    for k, v in sorted(priority.items()):
        print(f"    {k:<20} {v}")
    print("  By Coverage:")
    for k, v in sorted(coverage.items()):
        print(f"    {k:<20} {v}")
    print("─" * 55)



# ─────────────────────────────────────────────────────────────
# QUALITY GATE — local 80% acceptance evaluator + retry guidance
# ─────────────────────────────────────────────────────────────

def _non_empty(tc: dict, field: str) -> bool:
    return bool(str(tc.get(field, "")).strip())


def _contains_any(text: str, words: list[str]) -> bool:
    low = text.lower()
    return any(w in low for w in words)


def evaluate_test_cases(test_cases: list, source_text: str = "") -> dict:
    """
    Lightweight deterministic evaluator to avoid obvious low-quality output.
    It does not replace human QA review, but it catches common manager feedback:
      - too many basic/static cases
      - missing negative/edge/state coverage
      - weak expected results
      - missing traceability
      - invalid schema gaps

    Returns: {score, passed, issues, breakdown}
    """
    issues = []
    breakdown = {}

    if not isinstance(test_cases, list) or not test_cases:
        return {
            "score": 0,
            "passed": False,
            "issues": ["No test cases generated."],
            "breakdown": {}
        }

    count = len(test_cases)
    all_text = "\n".join(json.dumps(tc, ensure_ascii=False) for tc in test_cases)

    # 1) Schema + executability — 20
    required_fields = CSV_FIELDS
    missing_field_hits = 0
    weak_steps = 0
    weak_expected = 0
    for tc in test_cases:
        for field in required_fields:
            if field not in tc:
                missing_field_hits += 1
        steps = str(tc.get("Test Steps", ""))
        expected = str(tc.get("Expected Result", ""))
        if steps.count("\n") < 1 and not re.search(r"\b1\.", steps):
            weak_steps += 1
        if len(expected.strip()) < 25 or _contains_any(expected, ["works fine", "as expected", "properly"]):
            weak_expected += 1

    schema_score = 20
    schema_score -= min(8, missing_field_hits)
    schema_score -= min(6, weak_steps * 2)
    schema_score -= min(6, weak_expected * 2)
    breakdown["schema_executability"] = max(0, schema_score)
    if missing_field_hits:
        issues.append(f"{missing_field_hits} required field occurrences are missing.")
    if weak_steps:
        issues.append(f"{weak_steps} test case(s) have weak/non-stepwise test steps.")
    if weak_expected:
        issues.append(f"{weak_expected} test case(s) have weak expected results.")

    # 2) Coverage mix — 25
    coverage_values = [str(tc.get("Coverage Type", "")).lower() for tc in test_cases]
    titles_scenarios = " ".join(
        f"{tc.get('Test Case Title','')} {tc.get('Test Scenario','')} {tc.get('Test Steps','')} {tc.get('Expected Result','')}"
        for tc in test_cases
    ).lower()

    has_positive = _contains_any(titles_scenarios, ["valid", "success", "happy", "successful", "correct"])
    has_negative = _contains_any(titles_scenarios, ["invalid", "empty", "unauthor", "permission", "error", "fail", "cancel"])
    has_edge = _contains_any(titles_scenarios, ["boundary", "min", "max", "limit", "special", "double-click", "refresh", "back"])
    has_state = _contains_any(titles_scenarios, ["state", "status", "transition", "retry", "completed", "failed", "pending"])
    has_regression = _contains_any(titles_scenarios, ["regression", "existing", "should not affect", "unchanged"])

    coverage_score = 0
    coverage_score += 6 if has_positive else 0
    coverage_score += 6 if has_negative else 0
    coverage_score += 5 if has_edge else 0
    coverage_score += 5 if has_state else 0
    coverage_score += 3 if has_regression else 0
    breakdown["coverage_mix"] = coverage_score
    if not has_negative:
        issues.append("Negative/error coverage is missing or too weak.")
    if not has_edge:
        issues.append("Edge/BVA coverage is missing or too weak.")
    if not has_state:
        issues.append("State-transition/status coverage is missing or too weak.")

    # 3) Compactness and duplicate avoidance — 20
    compact_score = 20
    if count > 20:
        compact_score -= 8
        issues.append(f"Too many test cases ({count}); compact target is 8-14 for normal stories.")
    elif count > 14:
        compact_score -= 3

    normalized_titles = [
        re.sub(r"[^a-z0-9]+", " ", str(tc.get("Test Case Title", "")).lower()).strip()
        for tc in test_cases
    ]
    duplicate_count = count - len(set(normalized_titles))
    if duplicate_count:
        compact_score -= min(8, duplicate_count * 3)
        issues.append(f"{duplicate_count} duplicate/similar title(s) detected.")

    static_noise = sum(
        1 for tc in test_cases
        if _contains_any(
            f"{tc.get('Test Case Title','')} {tc.get('Test Scenario','')}",
            ["heading", "label", "static text", "banner text", "decorative"]
        )
    )
    if static_noise:
        compact_score -= min(6, static_noise * 2)
        issues.append(f"{static_noise} static/basic UI test(s) should be merged or removed.")

    breakdown["compactness"] = max(0, compact_score)

    # 4) Traceability / comments — 20
    trace_score = 20
    weak_trace = sum(
        1 for tc in test_cases
        if not _non_empty(tc, "Source Reference") or not _non_empty(tc, "Comments")
    )
    if weak_trace:
        trace_score -= min(12, weak_trace * 2)
        issues.append(f"{weak_trace} test case(s) have weak Source Reference or Comments traceability.")

    # Basic AC keyword coverage signal — not strict NLP, just a helpful heuristic
    source_low = source_text.lower()
    ac_keywords = set(re.findall(r"\b[a-z][a-z0-9_-]{3,}\b", source_low))
    stop = {
        "this","that","with","from","user","story","acceptance","criteria","should","when",
        "then","given","have","will","must","only","provided","figma","business","context"
    }
    ac_keywords = {w for w in ac_keywords if w not in stop}
    if ac_keywords:
        covered = sum(1 for w in ac_keywords if w in all_text.lower())
        keyword_ratio = covered / max(1, len(ac_keywords))
        if keyword_ratio < 0.35:
            trace_score -= 5
            issues.append("Low requirement keyword coverage signal; generated tests may not map well to source story/AC.")

    breakdown["traceability"] = max(0, trace_score)

    # 5) QA judgment / risk — 15
    risk_words = ["permission", "role", "status", "bulk", "individual", "data", "audit", "retry", "recover", "refresh", "duplicate", "race", "partial"]
    qa_score = 15 if _contains_any(all_text, risk_words) else 9
    if qa_score < 15:
        issues.append("Risk-based QA judgment is weak; add role/status/data/recovery risks where relevant.")
    breakdown["qa_judgment"] = qa_score

    score = sum(breakdown.values())
    return {
        "score": int(score),
        "passed": score >= 80,
        "issues": issues,
        "breakdown": breakdown
    }


def build_quality_revision_prompt(original_user_prompt: str, test_cases: list, evaluation: dict) -> str:
    """Ask the same model to revise output only when local quality gate is below 80."""
    return textwrap.dedent(f"""
    The previous test suite scored {evaluation.get('score', 0)}/100 and must be improved to >=80/100.

    Issues to fix:
    {json.dumps(evaluation.get('issues', []), indent=2)}

    Previous test cases:
    {json.dumps(test_cases, indent=2, ensure_ascii=False)}

    Original task/context:
    {original_user_prompt}

    Revise the test suite using these rules:
    - Keep output as ONLY valid JSON array.
    - Keep the same CSV field schema exactly.
    - Improve requirement/AC traceability in Source Reference and Comments.
    - Merge duplicate/basic/static cases.
    - Keep normal story output compact, ideally 8-14 high-value test cases.
    - Ensure positive, negative, edge/BVA, state transition, and regression-sensitive coverage.
    - Make steps executable and expected results measurable.
    """).strip()



# ─────────────────────────────────────────────────────────────
# MAIN PIPELINE
# ─────────────────────────────────────────────────────────────

def run(
    figma_url:        str   = "",
    frame_ids:        list  = None,
    jira_ticket:      str   = "",
    plain_story:      str   = "",
    business_context: str   = "",
    story_id:         str   = "",
    model:            str   = "gpt-4o-mini",
    output_prefix:    str   = None,
    delay_between:    float = 2.0,
):
    """
    Full QA agent pipeline. Any combination of inputs works:
      - figma_url alone
      - jira_ticket alone
      - business_context alone
      - any combination of the above

    At least ONE of figma_url, jira_ticket, or business_context must be provided.
    """
    frame_ids = frame_ids or []
    ts        = datetime.now().strftime("%Y%m%d_%H%M%S")
    prefix    = output_prefix or f"qa_output_{ts}"
    md_path   = f"{prefix}.md"
    csv_path  = f"{prefix}.csv"

    if not figma_url and not jira_ticket and not plain_story and not business_context:
        raise ValueError(
            "At least one input required:\n"
            "  --figma-url, --jira-ticket, --story, or --business"
        )

    print(f"\n{'='*55}")
    print(f"  QA Smart Agent")
    print(f"  Model   : {model}")
    print(f"  Figma   : {'Yes' if figma_url else 'No'}")
    print(f"  Jira    : {jira_ticket or 'No'}")
    print(f"  Story   : {'Pasted text (' + str(len(plain_story)) + ' chars)' if plain_story else 'No'}")
    print(f"  Business: {'Yes' if business_context else 'No'}")
    print(f"{'='*55}")

    # ── Fetch Jira story OR use plain pasted story ──
    jira_story   = None
    plain_story  = plain_story.strip()

    if jira_ticket:
        print("\n📋 Fetching Jira story from Jira Cloud...")
        jira_story = fetch_jira_story(jira_ticket)
        time.sleep(1)
    elif plain_story:
        print("\n📋 Using pasted story text...")
        # Wrap plain text as a minimal jira_story dict so build_prompt handles it uniformly
        jira_story = {
            "id":                   story_id or "QA-001",
            "summary":              plain_story[:120],
            "description":          plain_story,
            "acceptance_criteria":  _extract_ac_from_plain_text(plain_story),
            "story_type":           "Story",
            "priority":             "Medium",
            "status":               "In Progress",
            "labels":               [],
            "components":           [],
            "assignee":             "",
            "reporter":             "",
        }
        ac_lines = jira_story["acceptance_criteria"].splitlines()
        print(f"  ✅ Story text loaded ({len(plain_story)} chars)")
        print(f"     AC lines found: {len(ac_lines)}")

    # Determine story ID
    sid = story_id or jira_ticket or "QA-001"

    # ── Fetch Figma (if URL provided) ──
    figma_doc = ""
    if figma_url:
        if not FIGMA_TOKEN:
            raise EnvironmentError("FIGMA_TOKEN not set.")

        print("\n🔗 Parsing Figma URL...")
        file_key, url_node_id = parse_figma_url(figma_url)
        print(f"   file_key = {file_key}")

        all_ids = []
        seen    = set()
        for nid in ([url_node_id] if url_node_id else []) + frame_ids:
            if nid and nid not in seen:
                all_ids.append(nid)
                seen.add(nid)

        if not all_ids:
            raise ValueError("No frame IDs found. Provide --frame-ids or Figma URL with node-id.")
        print(f"   frames   = {all_ids}")

        print("\n📐 Fetching Figma metadata...")
        metadata = fetch_figma_metadata(file_key, all_ids)
        time.sleep(delay_between)

        print("\n🔗 Building flow map...")
        flow_map  = build_flow_map(metadata)
        figma_doc = metadata_to_markdown(metadata, flow_map)
        token_est = len(figma_doc) // 4
        print(f"   Figma DOC: ~{token_est} tokens")

        if token_est > 8000:
            print(f"   ⚠️  Large DOC — consider using fewer frames")

        save_markdown(figma_doc, md_path)
        time.sleep(delay_between)
    else:
        print("\n   Figma: skipped (not provided)")

    # ── Build prompt ──
    print("\n📝 Building AI prompt...")
    system_prompt, user_prompt = build_prompt(
        figma_doc        = figma_doc,
        jira_story       = jira_story,
        business_context = business_context,
        story_id         = sid,
    )

    # ── Call AI ──
    print(f"\n🤖 Generating test cases...")
    raw        = call_ai(system_prompt, user_prompt, model)
    test_cases = parse_ai_response(raw)
    print(f"   ✅ {len(test_cases)} test cases generated")

    # ── Local quality gate: target >=80, retry once with focused revision if needed ──
    source_for_eval = "\n".join([user_prompt, figma_doc or "", business_context or ""])
    quality = evaluate_test_cases(test_cases, source_for_eval)
    print(f"   🧪 Quality score: {quality['score']}/100")
    if not quality["passed"]:
        print("   ⚠️  Below 80 — asking model for compact quality revision...")
        revision_prompt = build_quality_revision_prompt(user_prompt, test_cases, quality)
        raw = call_ai(system_prompt, revision_prompt, model)
        revised_cases = parse_ai_response(raw)
        revised_quality = evaluate_test_cases(revised_cases, source_for_eval)
        print(f"   🧪 Revised quality score: {revised_quality['score']}/100")
        if revised_quality["score"] >= quality["score"]:
            test_cases = revised_cases
            quality = revised_quality

    if not quality["passed"]:
        print("   ⚠️  Final quality still below 80 by local heuristic. Review recommended.")
        for issue in quality.get("issues", [])[:5]:
            print(f"      - {issue}")

    # ── Save CSV ──
    print(f"\n💾 Saving CSV...")
    save_to_csv(test_cases, csv_path)

    outputs = {
        "CSV": csv_path,
        "Figma DOC": md_path if figma_url else None,
    }
    print_summary(test_cases, outputs)
    print(f"\n✅ Done!\n")

    return test_cases


# ─────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description=textwrap.dedent("""
        QA Smart Agent — generate test cases from any combination of:
          Figma design + Jira story (real-time) + Business context

        At least one input is required. All inputs are optional individually.

        Examples:
          # Figma only
          python qa_smart_agent.py --figma-url "..." --frame-ids "1318:1991"

          # Jira only
          python qa_smart_agent.py --jira-ticket PROJ-123

          # All three (best quality)
          python qa_smart_agent.py \\
            --figma-url "..." --frame-ids "1318:1991" \\
            --jira-ticket PROJ-123 \\
            --business "B2B e-commerce platform"

          # Change AI model
          python qa_smart_agent.py --jira-ticket PROJ-123 --model gpt-4o
          python qa_smart_agent.py --jira-ticket PROJ-123 --model claude-opus-4-5
        """),
        formatter_class=argparse.RawTextHelpFormatter,
    )

    # Inputs — all optional individually
    parser.add_argument("--figma-url",    default="", help="Figma design URL (optional)")
    parser.add_argument("--frame-ids",    nargs="+", default=[], help="Figma frame/node IDs")
    parser.add_argument("--jira-ticket",  default="", help="Jira ticket ID e.g. PROJ-123 (fetched in real time)")
    parser.add_argument("--story",        default="", help="Plain text user story — paste directly (no Jira needed)")
    parser.add_argument("--business",     default="", help="Business context / use case (optional)")
    parser.add_argument("--story-id",     default="", help="Override story ID in CSV (default: jira ticket ID)")

    # AI model
    parser.add_argument(
        "--model",
        default = "gpt-4o-mini",
        help    = (
            "AI model to use. Options:\n"
            f"  OpenAI   : {', '.join(OPENAI_MODELS)}\n"
            f"  Anthropic: {', '.join(ANTHROPIC_MODELS)}\n"
            "Default: gpt-4o-mini (cheapest)"
        )
    )

    # Output
    parser.add_argument("--output", default=None, help="Output file prefix (no extension)")
    parser.add_argument("--delay",  type=float, default=2.0, help="Delay between API calls (seconds)")

    args = parser.parse_args()

    if not args.figma_url and not args.jira_ticket and not args.business:
        parser.error("At least one of --figma-url, --jira-ticket, or --business is required.")

    run(
        figma_url        = args.figma_url,
        frame_ids        = args.frame_ids,
        jira_ticket      = args.jira_ticket,
        plain_story      = args.story,
        business_context = args.business,
        story_id         = args.story_id,
        model            = args.model,
        output_prefix    = args.output,
        delay_between    = args.delay,
    )


if __name__ == "__main__":
    main()


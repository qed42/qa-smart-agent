/**
 * QA Smart Agent — Unified Backend API
 *
 * Supports: OpenAI · Anthropic · Gemini (any model dynamically)
 * Returns : JSON · CSV download · DOCX download
 * Inputs  : story · figma · jira_ticket · business_context
 *
 * Setup:
 *   npm install express @anthropic-ai/sdk openai @google/generative-ai \
 *               dotenv express-rate-limit docx node-fetch
 *   node server.js
 *
 * .env:
 *   ANTHROPIC_API_KEY=sk-ant-...
 *   OPENAI_API_KEY=sk-proj-...
 *   GEMINI_API_KEY=AIza...
 *   FIGMA_TOKEN=figd_...
 *   JIRA_BASE_URL=https://yourcompany.atlassian.net
 *   JIRA_EMAIL=you@company.com
 *   JIRA_API_TOKEN=your_token
 */

import express            from "express";
import rateLimit          from "express-rate-limit";
import fs                 from "fs";
import path               from "path";
import { fileURLToPath }  from "url";
import dotenv             from "dotenv";
import fetch              from "node-fetch";
import { Document, Packer, Paragraph, TextRun, HeadingLevel } from "docx";

dotenv.config();

const app       = express();
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const USAGE_LOG = path.join(__dirname, "usage_log.json");

app.use(express.json({ limit: "200kb" }));


// ─────────────────────────────────────────────────────────────
// RATE LIMITING
// ─────────────────────────────────────────────────────────────

app.use("/generate-tests", rateLimit({
    windowMs    : 60 * 60 * 1000,
    max         : 20,
    keyGenerator: (req) => req.headers["x-user-email"] || req.ip,
    message     : { error: "Rate limit — max 20 requests/hour/user." }
}));


// ─────────────────────────────────────────────────────────────
// USAGE TRACKER
// ─────────────────────────────────────────────────────────────

function loadUsage()       { return fs.existsSync(USAGE_LOG) ? JSON.parse(fs.readFileSync(USAGE_LOG)) : []; }
function saveUsage(entry)  { const log = loadUsage(); log.push(entry); fs.writeFileSync(USAGE_LOG, JSON.stringify(log, null, 2)); }

const PRICING = {
    // OpenAI
    "gpt-4o-mini"           : { input: 0.15,   output: 0.60   },
    "gpt-4o"                : { input: 5.00,   output: 15.00  },
    "gpt-4-turbo"           : { input: 10.00,  output: 30.00  },
    // Anthropic
    "claude-opus-4-5"       : { input: 15.00,  output: 75.00  },
    "claude-sonnet-4-5"     : { input: 3.00,   output: 15.00  },
    "claude-haiku-4-5-20251001" : { input: 0.25, output: 1.25 },
    // Gemini
    "gemini-1.5-flash"      : { input: 0.075,  output: 0.30   },
    "gemini-1.5-pro"        : { input: 3.50,   output: 10.50  },
};

function estimateCost(inputTokens, outputTokens, model) {
    const p = PRICING[model] || { input: 1.00, output: 3.00 };
    return ((inputTokens * p.input) + (outputTokens * p.output)) / 1_000_000;
}


// ─────────────────────────────────────────────────────────────
// DETECT PROVIDER from model name
// ─────────────────────────────────────────────────────────────

function detectProvider(model = "") {
    const m = model.toLowerCase();
    if (m.startsWith("gpt") || m.startsWith("o1") || m.startsWith("o3"))  return "openai";
    if (m.startsWith("claude"))                                             return "anthropic";
    if (m.startsWith("gemini"))                                             return "gemini";
    throw new Error(`Unknown model "${model}". Use gpt-*, claude-*, or gemini-* prefix.`);
}


// ─────────────────────────────────────────────────────────────
// AI CALL — routes to correct provider automatically
// ─────────────────────────────────────────────────────────────

async function callAI(systemPrompt, userPrompt, model) {
    const provider = detectProvider(model);

    if (provider === "openai") {
        const { default: OpenAI } = await import("openai");
        const client   = new OpenAI({ apiKey: process.env.OPENAI_API_KEY });
        const response = await client.chat.completions.create({
            model,
            max_tokens  : 16000,
            temperature : 0,
            messages    : [
                { role: "system", content: systemPrompt },
                { role: "user",   content: userPrompt   },
            ],
        });
        return {
            text         : response.choices[0].message.content.trim(),
            inputTokens  : response.usage.prompt_tokens,
            outputTokens : response.usage.completion_tokens,
            provider,
        };
    }

    if (provider === "anthropic") {
        const { default: Anthropic } = await import("@anthropic-ai/sdk");
        const client   = new Anthropic({ apiKey: process.env.ANTHROPIC_API_KEY });
        const response = await client.messages.create({
            model,
            max_tokens : 16000,
            system     : systemPrompt,
            messages   : [{ role: "user", content: userPrompt }],
        });
        return {
            text         : response.content[0].text.trim(),
            inputTokens  : response.usage.input_tokens,
            outputTokens : response.usage.output_tokens,
            provider,
        };
    }

    if (provider === "gemini") {
        const { GoogleGenerativeAI } = await import("@google/generative-ai");
        const genAI  = new GoogleGenerativeAI(process.env.GEMINI_API_KEY);
        const gemini = genAI.getGenerativeModel({ model });
        const result = await gemini.generateContent(`${systemPrompt}\n\n${userPrompt}`);
        const text   = result.response.text().trim();
        // Gemini doesn't return token counts in same way — estimate
        const inputTokens  = Math.ceil((systemPrompt.length + userPrompt.length) / 4);
        const outputTokens = Math.ceil(text.length / 4);
        return { text, inputTokens, outputTokens, provider };
    }
}


// ─────────────────────────────────────────────────────────────
// JIRA FETCH — real time
// ─────────────────────────────────────────────────────────────

async function fetchJiraStory(ticketId) {
    const base  = (process.env.JIRA_BASE_URL || "").replace(/\/$/, "");
    const email = process.env.JIRA_EMAIL;
    const token = process.env.JIRA_API_TOKEN;

    if (!base || !email || !token) {
        throw new Error("JIRA_BASE_URL, JIRA_EMAIL, JIRA_API_TOKEN must be set in .env");
    }

    const url = `${base}/rest/api/3/issue/${ticketId}`;
    const r   = await fetch(url, {
        headers: {
            "Authorization": "Basic " + Buffer.from(`${email}:${token}`).toString("base64"),
            "Accept"       : "application/json",
        }
    });

    if (r.status === 401) throw new Error("Jira 401 — check JIRA_EMAIL and JIRA_API_TOKEN");
    if (r.status === 404) throw new Error(`Jira ticket '${ticketId}' not found`);

    const data   = await r.json();
    const fields = data.fields || {};

    // Extract text from Atlassian Document Format
    const adfToText = (node) => {
        if (!node || typeof node !== "object") return "";
        let text = node.text || "";
        (node.content || []).forEach(child => { text += adfToText(child); });
        return text;
    };

    return {
        id          : ticketId,
        summary     : fields.summary || "",
        description : adfToText(fields.description),
        priority    : (fields.priority || {}).name || "Medium",
        status      : (fields.status   || {}).name || "",
        type        : (fields.issuetype|| {}).name || "Story",
        ac          : adfToText(fields.customfield_10016 || fields.customfield_10014 || {}),
    };
}


// ─────────────────────────────────────────────────────────────
// FIGMA FETCH — metadata as structured doc
// ─────────────────────────────────────────────────────────────

async function fetchFigmaDoc(figmaUrl, frameIds = []) {
    const token = process.env.FIGMA_TOKEN;
    if (!token) throw new Error("FIGMA_TOKEN not set in .env");

    // Parse file key
    const match = figmaUrl.match(/figma\.com\/(?:design|file)\/([^/?]+)/);
    if (!match) throw new Error("Invalid Figma URL");
    const fileKey = match[1];

    // Parse node from URL
    const urlNode = new URL(figmaUrl).searchParams.get("node-id");
    if (urlNode) frameIds = [urlNode.replace("-", ":"), ...frameIds];
    const ids = [...new Set(frameIds)].join(",");

    if (!ids) throw new Error("No frame IDs found. Add node-id to Figma URL or pass frameIds.");

    const r = await fetch(
        `https://api.figma.com/v1/files/${fileKey}/nodes?ids=${ids}&depth=2`,
        { headers: { "X-Figma-Token": token } }
    );

    if (r.status === 403) throw new Error("Figma 403 — check FIGMA_TOKEN");
    const data  = await r.json();
    const nodes = data.nodes || {};

    // Convert to markdown doc
    let doc = "## Figma design structure\n\n";

    const extractTexts = (node, depth = 0) => {
        if (!node) return "";
        let out = "";
        const name  = node.name  || "";
        const type  = node.type  || "";
        const chars = node.characters || "";

        if (type === "TEXT" && chars.trim()) {
            out += `${"  ".repeat(depth)}- "${chars.trim().slice(0, 150)}"\n`;
        } else if (name && ["FRAME","COMPONENT","INSTANCE","GROUP"].includes(type)) {
            out += `${"  ".repeat(depth)}[${name}]\n`;
        }

        (node.children || []).forEach(c => { out += extractTexts(c, depth + 1); });
        return out;
    };

    for (const [nodeId, wrapper] of Object.entries(nodes)) {
        const doc_node = wrapper.document || {};
        doc += `### Screen: ${doc_node.name || nodeId} (Frame ${nodeId})\n`;
        doc += extractTexts(doc_node);
        doc += "\n";
    }

    return doc;
}


// ─────────────────────────────────────────────────────────────
// BUILD PROMPT
// ─────────────────────────────────────────────────────────────

function buildPrompt(story, jiraData, businessContext, figmaDoc, storyId) {
    const sid = storyId || (jiraData && jiraData.id) || "QA-001";

    const systemPrompt = `You are a senior QA engineer with 10+ years experience and a pragmatic test-case generation skill.

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
- Use exactly the requested field names.`;

    const hasStory   = story && story.trim();
    const hasJira    = jiraData && jiraData.summary;
    const hasBiz     = businessContext && businessContext.trim();
    const hasFigma   = figmaDoc && figmaDoc.trim();

    let context = "";

    if (hasJira) {
        context += `JIRA STORY (${jiraData.id}):\n`;
        context += `Summary: ${jiraData.summary}\n`;
        if (jiraData.description) context += `Description: ${jiraData.description.slice(0, 1000)}\n`;
        if (jiraData.ac)          context += `Acceptance Criteria:\n${jiraData.ac.slice(0, 2000)}\n`;
        context += "\n";
    }

    if (hasStory) {
        context += `USER STORY:\n${story.trim()}\n\n`;
    }

    if (hasBiz) {
        context += `BUSINESS CONTEXT:\n${businessContext.trim()}\n\n`;
    }

    if (hasFigma) {
        context += `FIGMA DESIGN DOC:\n${figmaDoc.slice(0, 8000)}\n\n`;
    }

    if (!hasStory && !hasJira && !hasBiz && hasFigma) {
        context += `NOTE: No story or business context provided.
Analyse the Figma design above like a human QA analyst.
Infer the business domain from component names and screen flow.
Self-generate acceptance criteria then apply BVA + EP + Black Box.\n\n`;
    }

    const userPrompt = `${context}
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

Return ONLY a valid JSON array. Each object MUST have EXACTLY:
{
  "Story ID":        "${sid}",
  "Test Case ID":    "TC_001",
  "Test Scenario":   "scenario description",
  "Test Case Title": "clear title",
  "Module":          "module name",
  "Priority":        "High | Medium | Low",
  "Severity":        "Critical | Major | Minor | Trivial",
  "Preconditions":   "what must be true",
  "Test Steps":      "1. step\\n2. step\\n3. step",
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
  "Source Reference":"${sid} | AC/REQ references covered",
  "Story Summary":   "one line summary"
}

Final self-check before returning:
- Is every AC/requirement covered?
- Are basic/static-only tests removed?
- Are similar cases merged?
- Would a 10+ years QA lead accept this as >=80/100?
- Is the response valid JSON array only?`;

    return { systemPrompt, userPrompt };
}



// ─────────────────────────────────────────────────────────────
// QUALITY GATE — local 80% acceptance evaluator + retry guidance
// ─────────────────────────────────────────────────────────────

function containsAny(text = "", words = []) {
    const low = String(text).toLowerCase();
    return words.some(w => low.includes(w));
}

function evaluateTestCases(testCases, sourceText = "") {
    const issues = [];
    const breakdown = {};

    if (!Array.isArray(testCases) || testCases.length === 0) {
        return { score: 0, passed: false, issues: ["No test cases generated."], breakdown: {} };
    }

    const count = testCases.length;
    const allText = testCases.map(tc => JSON.stringify(tc)).join("\n");

    // 1) Schema + executability — 20
    let missingFieldHits = 0;
    let weakSteps = 0;
    let weakExpected = 0;

    for (const tc of testCases) {
        for (const field of CSV_FIELDS) {
            if (!(field in tc)) missingFieldHits += 1;
        }

        const steps = String(tc["Test Steps"] || "");
        const expected = String(tc["Expected Result"] || "");

        if ((steps.match(/\n/g) || []).length < 1 && !/\b1\./.test(steps)) weakSteps += 1;
        if (expected.trim().length < 25 || containsAny(expected, ["works fine", "as expected", "properly"])) weakExpected += 1;
    }

    let schemaScore = 20;
    schemaScore -= Math.min(8, missingFieldHits);
    schemaScore -= Math.min(6, weakSteps * 2);
    schemaScore -= Math.min(6, weakExpected * 2);
    breakdown.schema_executability = Math.max(0, schemaScore);

    if (missingFieldHits) issues.push(`${missingFieldHits} required field occurrences are missing.`);
    if (weakSteps) issues.push(`${weakSteps} test case(s) have weak/non-stepwise test steps.`);
    if (weakExpected) issues.push(`${weakExpected} test case(s) have weak expected results.`);

    // 2) Coverage mix — 25
    const titleScenarioText = testCases.map(tc =>
        `${tc["Test Case Title"] || ""} ${tc["Test Scenario"] || ""} ${tc["Test Steps"] || ""} ${tc["Expected Result"] || ""}`
    ).join(" ").toLowerCase();

    const hasPositive = containsAny(titleScenarioText, ["valid", "success", "happy", "successful", "correct"]);
    const hasNegative = containsAny(titleScenarioText, ["invalid", "empty", "unauthor", "permission", "error", "fail", "cancel"]);
    const hasEdge = containsAny(titleScenarioText, ["boundary", "min", "max", "limit", "special", "double-click", "refresh", "back"]);
    const hasState = containsAny(titleScenarioText, ["state", "status", "transition", "retry", "completed", "failed", "pending"]);
    const hasRegression = containsAny(titleScenarioText, ["regression", "existing", "should not affect", "unchanged"]);

    let coverageScore = 0;
    coverageScore += hasPositive ? 6 : 0;
    coverageScore += hasNegative ? 6 : 0;
    coverageScore += hasEdge ? 5 : 0;
    coverageScore += hasState ? 5 : 0;
    coverageScore += hasRegression ? 3 : 0;
    breakdown.coverage_mix = coverageScore;

    if (!hasNegative) issues.push("Negative/error coverage is missing or too weak.");
    if (!hasEdge) issues.push("Edge/BVA coverage is missing or too weak.");
    if (!hasState) issues.push("State-transition/status coverage is missing or too weak.");

    // 3) Compactness and duplicate avoidance — 20
    let compactScore = 20;
    if (count > 20) {
        compactScore -= 8;
        issues.push(`Too many test cases (${count}); compact target is 8-14 for normal stories.`);
    } else if (count > 14) {
        compactScore -= 3;
    }

    const normalizedTitles = testCases.map(tc =>
        String(tc["Test Case Title"] || "").toLowerCase().replace(/[^a-z0-9]+/g, " ").trim()
    );
    const duplicateCount = count - new Set(normalizedTitles).size;
    if (duplicateCount) {
        compactScore -= Math.min(8, duplicateCount * 3);
        issues.push(`${duplicateCount} duplicate/similar title(s) detected.`);
    }

    const staticNoise = testCases.filter(tc =>
        containsAny(`${tc["Test Case Title"] || ""} ${tc["Test Scenario"] || ""}`, ["heading", "label", "static text", "banner text", "decorative"])
    ).length;
    if (staticNoise) {
        compactScore -= Math.min(6, staticNoise * 2);
        issues.push(`${staticNoise} static/basic UI test(s) should be merged or removed.`);
    }

    breakdown.compactness = Math.max(0, compactScore);

    // 4) Traceability / comments — 20
    let traceScore = 20;
    const weakTrace = testCases.filter(tc =>
        !String(tc["Source Reference"] || "").trim() || !String(tc["Comments"] || "").trim()
    ).length;
    if (weakTrace) {
        traceScore -= Math.min(12, weakTrace * 2);
        issues.push(`${weakTrace} test case(s) have weak Source Reference or Comments traceability.`);
    }

    const sourceWords = new Set(
        String(sourceText).toLowerCase().match(/\b[a-z][a-z0-9_-]{3,}\b/g) || []
    );
    const stop = new Set(["this","that","with","from","user","story","acceptance","criteria","should","when","then","given","have","will","must","only","provided","figma","business","context"]);
    const acKeywords = [...sourceWords].filter(w => !stop.has(w));
    if (acKeywords.length) {
        const covered = acKeywords.filter(w => allText.toLowerCase().includes(w)).length;
        const keywordRatio = covered / Math.max(1, acKeywords.length);
        if (keywordRatio < 0.35) {
            traceScore -= 5;
            issues.push("Low requirement keyword coverage signal; generated tests may not map well to source story/AC.");
        }
    }

    breakdown.traceability = Math.max(0, traceScore);

    // 5) QA judgment / risk — 15
    const riskWords = ["permission", "role", "status", "bulk", "individual", "data", "audit", "retry", "recover", "refresh", "duplicate", "race", "partial"];
    const qaScore = containsAny(allText, riskWords) ? 15 : 9;
    breakdown.qa_judgment = qaScore;
    if (qaScore < 15) issues.push("Risk-based QA judgment is weak; add role/status/data/recovery risks where relevant.");

    const score = Object.values(breakdown).reduce((a, b) => a + b, 0);
    return { score: Math.trunc(score), passed: score >= 80, issues, breakdown };
}

function buildQualityRevisionPrompt(originalUserPrompt, testCases, evaluation) {
    return `The previous test suite scored ${evaluation.score || 0}/100 and must be improved to >=80/100.

Issues to fix:
${JSON.stringify(evaluation.issues || [], null, 2)}

Previous test cases:
${JSON.stringify(testCases, null, 2)}

Original task/context:
${originalUserPrompt}

Revise the test suite using these rules:
- Keep output as ONLY valid JSON array.
- Keep the same CSV field schema exactly.
- Improve requirement/AC traceability in Source Reference and Comments.
- Merge duplicate/basic/static cases.
- Keep normal story output compact, ideally 8-14 high-value test cases.
- Ensure positive, negative, edge/BVA, state transition, and regression-sensitive coverage.
- Make steps executable and expected results measurable.`;
}


// ─────────────────────────────────────────────────────────────
// BUILD CSV
// ─────────────────────────────────────────────────────────────

const CSV_FIELDS = [
    "Story ID","Test Case ID","Test Scenario","Test Case Title",
    "Module","Priority","Severity","Preconditions","Test Steps",
    "Test Data","Expected Result","Actual Result","Status",
    "Environment","Browser/Device","Created By","Execution Date",
    "Comments","Coverage Type","Source Reference","Story Summary"
];

function buildCSV(testCases) {
    const escape = (v) => {
        const s = String(v || "").replace(/"/g, '""');
        return s.includes(",") || s.includes("\n") || s.includes('"') ? `"${s}"` : s;
    };
    return [
        CSV_FIELDS.join(","),
        ...testCases.map(tc => CSV_FIELDS.map(f => escape(tc[f] || "")).join(","))
    ].join("\n");
}


// ─────────────────────────────────────────────────────────────
// BUILD DOCX
// ─────────────────────────────────────────────────────────────

async function buildDocx(testCases, storyId) {
    const children = [
        new Paragraph({
            heading : HeadingLevel.HEADING_1,
            children: [new TextRun({ text: `QA Test Cases — ${storyId}`, bold: true })]
        }),
        new Paragraph({
            children: [new TextRun({ text: `Generated: ${new Date().toISOString()}`, color: "888888" })]
        }),
        new Paragraph({ children: [new TextRun("")] }),
    ];

    testCases.forEach((tc, i) => {
        children.push(
            new Paragraph({
                heading : HeadingLevel.HEADING_2,
                children: [new TextRun({ text: `${tc["Test Case ID"]} — ${tc["Test Case Title"]}`, bold: true })]
            })
        );

        const fields = [
            ["Module",       tc["Module"]],
            ["Priority",     `${tc["Priority"]} / ${tc["Severity"]}`],
            ["Coverage",     tc["Coverage Type"]],
            ["Preconditions",tc["Preconditions"]],
            ["Test Steps",   tc["Test Steps"]],
            ["Test Data",    tc["Test Data"]],
            ["Expected",     tc["Expected Result"]],
            ["Status",       tc["Status"]],
        ];

        fields.forEach(([label, value]) => {
            if (value) {
                children.push(new Paragraph({
                    children: [
                        new TextRun({ text: `${label}: `, bold: true }),
                        new TextRun({ text: String(value) }),
                    ]
                }));
            }
        });

        children.push(new Paragraph({ children: [new TextRun("")] }));
    });

    const doc = new Document({ sections: [{ children }] });
    return await Packer.toBuffer(doc);
}


// ─────────────────────────────────────────────────────────────
// PARSE AI RESPONSE
// ─────────────────────────────────────────────────────────────

function parseAIResponse(raw) {
    raw = raw.replace(/^```(?:json)?\s*/,"").replace(/\s*```$/,"").trim();

    if (!raw.endsWith("]")) {
        const lastGood = raw.lastIndexOf("},");
        if (lastGood > 0) raw = raw.slice(0, lastGood + 1) + "]";
    }

    const testCases = JSON.parse(raw);
    return testCases.map((tc, i) => ({ ...tc, "Test Case ID": `TC_${String(i+1).padStart(3,"0")}` }));
}


// ─────────────────────────────────────────────────────────────
// POST /generate-tests — MAIN ENDPOINT
// ─────────────────────────────────────────────────────────────

app.post("/generate-tests", async (req, res) => {
    const {
        story            = "",
        jira_ticket      = "",
        business_context = "",
        figma_url        = "",
        frame_ids        = [],
        story_id         = "",
        model            = "gpt-4o-mini",
    } = req.body;

    const userEmail = req.headers["x-user-email"] || "unknown";
    const format    = (req.headers["accept"] || "").includes("text/csv")  ? "csv"
                    : (req.headers["accept"] || "").includes("application/vnd") ? "docx"
                    : "json";

    if (!story && !jira_ticket && !business_context && !figma_url) {
        return res.status(400).json({
            error: "Provide at least one of: story, jira_ticket, business_context, figma_url"
        });
    }

    console.log(`\n[${new Date().toISOString()}] /generate-tests`);
    console.log(`  user=${userEmail} | model=${model} | format=${format}`);

    try {
        // ── Fetch Jira if ticket provided ──
        let jiraData = null;
        if (jira_ticket) {
            console.log(`  Fetching Jira: ${jira_ticket}...`);
            jiraData = await fetchJiraStory(jira_ticket);
            console.log(`  ✅ Jira: ${jiraData.summary.slice(0,50)}`);
        }

        // ── Fetch Figma if URL provided ──
        let figmaDoc = "";
        if (figma_url) {
            console.log(`  Fetching Figma...`);
            figmaDoc = await fetchFigmaDoc(figma_url, frame_ids);
            console.log(`  ✅ Figma DOC: ~${Math.ceil(figmaDoc.length/4)} tokens`);
        }

        // ── Build prompt ──
        const sid = story_id || jira_ticket || "QA-001";
        const { systemPrompt, userPrompt } = buildPrompt(
            story, jiraData, business_context, figmaDoc, sid
        );

        // ── Call AI ──
        console.log(`  Calling ${model}...`);
        const aiResult = await callAI(systemPrompt, userPrompt, model);

        console.log(`  ✅ AI done | tokens=${aiResult.inputTokens}+${aiResult.outputTokens}`);

        // ── Parse test cases ──
        let testCases = parseAIResponse(aiResult.text);
        console.log(`  ✅ ${testCases.length} test cases generated`);

        // ── Local quality gate: target >=80, retry once with focused revision if needed ──
        const sourceForEval = [userPrompt, figmaDoc || "", business_context || "", story || ""].join("\n");
        let quality = evaluateTestCases(testCases, sourceForEval);
        console.log(`  🧪 Quality score=${quality.score}/100`);

        let finalAiResult = aiResult;
        if (!quality.passed) {
            console.log(`  ⚠️  Below 80 — asking model for compact quality revision...`);
            const revisionPrompt = buildQualityRevisionPrompt(userPrompt, testCases, quality);
            const revisedAiResult = await callAI(systemPrompt, revisionPrompt, model);
            const revisedCases = parseAIResponse(revisedAiResult.text);
            const revisedQuality = evaluateTestCases(revisedCases, sourceForEval);
            console.log(`  🧪 Revised quality score=${revisedQuality.score}/100`);

            if (revisedQuality.score >= quality.score) {
                testCases = revisedCases;
                quality = revisedQuality;
                finalAiResult = {
                    ...revisedAiResult,
                    inputTokens: aiResult.inputTokens + revisedAiResult.inputTokens,
                    outputTokens: aiResult.outputTokens + revisedAiResult.outputTokens,
                };
            }
        }

        // ── Log usage ──
        const cost = estimateCost(finalAiResult.inputTokens, finalAiResult.outputTokens, model);
        const usageEntry = {
            timestamp    : new Date().toISOString(),
            user         : userEmail,
            model,
            provider     : aiResult.provider,
            input_tokens : finalAiResult.inputTokens,
            output_tokens: finalAiResult.outputTokens,
            total_tokens : finalAiResult.inputTokens + finalAiResult.outputTokens,
            cost_usd     : cost.toFixed(6),
            story_id     : sid,
            test_count   : testCases.length,
            quality_score: quality.score,
            quality_passed: quality.passed,
        };
        saveUsage(usageEntry);

        // ── Return in requested format ──
        if (format === "csv") {
            const csv      = buildCSV(testCases);
            const filename = `qa_tests_${sid}_${Date.now()}.csv`;
            res.setHeader("Content-Type", "text/csv");
            res.setHeader("Content-Disposition", `attachment; filename="${filename}"`);
            res.setHeader("X-Test-Count", testCases.length);
            res.setHeader("X-Cost-USD",   cost.toFixed(6));
            res.setHeader("X-Quality-Score", quality.score);
            return res.send(csv);
        }

        if (format === "docx") {
            const buffer   = await buildDocx(testCases, sid);
            const filename = `qa_tests_${sid}_${Date.now()}.docx`;
            res.setHeader("Content-Type", "application/vnd.openxmlformats-officedocument.wordprocessingml.document");
            res.setHeader("Content-Disposition", `attachment; filename="${filename}"`);
            res.setHeader("X-Test-Count", testCases.length);
            res.setHeader("X-Quality-Score", quality.score);
            return res.send(buffer);
        }

        // Default JSON — includes csv string too
        return res.json({
            success    : true,
            count      : testCases.length,
            test_cases : testCases,
            csv        : buildCSV(testCases),
            usage      : usageEntry,
            quality    : quality,
        });

    } catch (err) {
        console.error(`  ❌ ${err.message}`);
        return res.status(500).json({ error: err.message });
    }
});


// ─────────────────────────────────────────────────────────────
// GET /usage — usage report
// ─────────────────────────────────────────────────────────────

app.get("/usage", (req, res) => {
    const log    = loadUsage();
    const byUser = {};
    let totalCost = 0;

    for (const e of log) {
        if (!byUser[e.user]) byUser[e.user] = { requests: 0, tokens: 0, cost: 0, tests_generated: 0 };
        byUser[e.user].requests        += 1;
        byUser[e.user].tokens          += e.total_tokens || 0;
        byUser[e.user].cost            += parseFloat(e.cost_usd || 0);
        byUser[e.user].tests_generated += e.test_count  || 0;
        totalCost                      += parseFloat(e.cost_usd || 0);
    }

    res.json({
        total_requests   : log.length,
        total_cost_usd   : totalCost.toFixed(4),
        by_user          : byUser,
        recent           : log.slice(-20),
    });
});


// ─────────────────────────────────────────────────────────────
// GET /models — list supported models
// ─────────────────────────────────────────────────────────────

app.get("/models", (req, res) => {
    res.json({
        openai    : ["gpt-4o-mini", "gpt-4o", "gpt-4-turbo"],
        anthropic : ["claude-opus-4-5", "claude-sonnet-4-5", "claude-haiku-4-5-20251001"],
        gemini    : ["gemini-1.5-flash", "gemini-1.5-pro"],
        default   : "gpt-4o-mini",
        pricing   : PRICING,
    });
});


// ─────────────────────────────────────────────────────────────
// GET /health
// ─────────────────────────────────────────────────────────────

app.get("/health", (req, res) => {
    res.json({
        status    : "ok",
        timestamp : new Date().toISOString(),
        providers : {
            openai    : !!process.env.OPENAI_API_KEY,
            anthropic : !!process.env.ANTHROPIC_API_KEY,
            gemini    : !!process.env.GEMINI_API_KEY,
            figma     : !!process.env.FIGMA_TOKEN,
            jira      : !!(process.env.JIRA_BASE_URL && process.env.JIRA_API_TOKEN),
        }
    });
});


// ─────────────────────────────────────────────────────────────
// START
// ─────────────────────────────────────────────────────────────

const PORT = process.env.PORT || 3000;
app.listen(PORT, () => {
    console.log(`\n🚀 QA Smart Agent API — http://localhost:${PORT}`);
    console.log(`   POST /generate-tests  — generate test cases`);
    console.log(`   GET  /models          — list supported models`);
    console.log(`   GET  /usage           — usage report`);
    console.log(`   GET  /health          — provider status\n`);
});

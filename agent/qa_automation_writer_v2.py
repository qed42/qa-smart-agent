#!/usr/bin/env python3
"""
QA Automation Writer
────────────────────
Reads manual QA test cases from CSV and generates/updates Playwright JS POM automation files.

Modes:
  1. Existing repo mode:
     --repo /path/to/existing-playwright-project

  2. New repo mode:
     --repo /path/to/new-playwright-project --create-new

Example:
  python qa_automation_writer.py \
    --csv ./laaha_survey_gpt4o_tests.csv \
    --repo /Users/qed42/laaha-playwright-automation \
    --create-new \
    --model gpt-4o

Behavior:
  - Reads CSV test cases
  - If repo exists: scans structure and follows existing patterns
  - If repo does not exist and --create-new is passed: creates a new Playwright JS POM project
  - Generates/updates POM, tests, test data, utils, config, package.json as needed
  - Backs up existing files before overwrite
"""

import argparse
import csv
import json
import os
import re
import sys
from pathlib import Path
from datetime import datetime


IGNORE_DIRS = {
    "node_modules", ".git", "dist", "build", "coverage", "playwright-report",
    "test-results", ".next", ".cache", "__pycache__", ".venv", "venv"
}

DEFAULT_MAX_TREE_FILES = 300
DEFAULT_MAX_FILE_CHARS = 8000


AUTOMATION_SKILL_PROMPT = """
You are a senior QA automation engineer with 10+ years of experience.

Your task:
Convert manual QA test cases from CSV into maintainable Playwright JavaScript automation using Page Object Model.

Core principles:
1. Follow the existing repository structure when one exists.
2. If this is a new repo, create a clean Playwright JS POM structure.
3. Use Page Object Model:
   - Page objects contain locators and reusable page actions.
   - Test files contain scenario flow and assertions.
   - Utilities contain shared helpers only when reused.
   - Test data files contain stable test data.
4. Keep tests thin and page objects reusable.
5. Do not hard-code brittle selectors if better selectors exist.
6. Prefer Playwright locators in this order:
   - getByRole
   - getByLabel
   - getByPlaceholder
   - getByText only when stable
   - data-testid / id / stable CSS
   - XPath only as last option
7. Do not use hard waits like waitForTimeout except with strong justification.
8. Use expect assertions with clear business meaning.
9. Preserve traceability:
   - Include CSV Test Case ID in the test title or comments.
   - Group tests by feature/module.
10. Generate minimum automation scripts with maximum coverage:
   - Do not automate useless static UI checks.
   - Merge similar manual test cases into reusable flows.
   - Prioritize high-risk functional, negative, edge, regression, and security scenarios.
11. Code must be executable with @playwright/test.
12. If repository already has fixtures, base test, helpers, or naming patterns, reuse them.
13. Avoid duplicate methods. Create generic reusable methods where possible.

For a NEW repo, create this baseline structure:
- package.json
- playwright.config.js
- README.md
- .gitignore
- pageobjects/BasePage.js
- pageobjects/<FeaturePage>.js
- tests/<feature>/<feature>.spec.js
- test-data/<feature>Data.json
- utils/testConfig.js

Quality gate before output:
- Reusability: 25%
- Repository alignment/new repo completeness: 20%
- Executability: 20%
- Locator strategy: 10%
- CSV traceability: 10%
- Test coverage: 10%
- Wait/assertion strategy: 5%

Only generate files that are required.
Return ONLY valid JSON in this exact structure:
{
  "files": [
    {
      "path": "relative/path/from/output-folder.js",
      "action": "create|update",
      "content": "full file content here"
    }
  ],
  "notes": [
    "short implementation note"
  ]
}
No markdown. No explanation outside JSON.
"""


NEW_REPO_TREE = """
package.json
playwright.config.js
README.md
.gitignore
pageobjects/BasePage.js
pageobjects/SurveyPage.js
tests/survey/laahaSurvey.spec.js
test-data/surveyData.json
utils/testConfig.js
"""


def read_csv_cases(csv_path: Path) -> list[dict]:
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV not found: {csv_path}")

    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        rows = [dict(row) for row in reader]

    if not rows:
        raise ValueError("CSV has no test cases.")

    return rows


def compact_test_cases(rows: list[dict]) -> str:
    wanted = [
        "Story ID", "Test Case ID", "Test Scenario", "Test Case Title",
        "Module", "Priority", "Severity", "Preconditions", "Test Steps",
        "Test Data", "Expected Result", "Coverage Type", "Source Reference",
        "Story Summary"
    ]

    lines = []
    for row in rows:
        lines.append("TEST CASE")
        for key in wanted:
            val = (row.get(key) or "").strip()
            if val:
                lines.append(f"{key}: {val}")
        lines.append("---")

    return "\n".join(lines)


def scan_repo_tree(repo: Path, max_files: int = DEFAULT_MAX_TREE_FILES) -> str:
    files = []
    for root, dirs, filenames in os.walk(repo):
        dirs[:] = [d for d in dirs if d not in IGNORE_DIRS and not d.startswith(".git")]
        root_path = Path(root)

        for filename in filenames:
            path = root_path / filename
            rel = path.relative_to(repo)

            if len(files) >= max_files:
                break

            if any(part in IGNORE_DIRS for part in rel.parts):
                continue

            if filename.startswith(".") and filename not in {".env.example", ".gitignore"}:
                continue

            suffix = path.suffix.lower()
            if suffix in {".js", ".ts", ".json", ".md", ".mjs", ".cjs"} or "playwright.config" in filename:
                files.append(str(rel))

        if len(files) >= max_files:
            break

    return "\n".join(sorted(files))


def read_relevant_repo_files(repo: Path, tree: str, max_chars: int = DEFAULT_MAX_FILE_CHARS) -> str:
    priority_patterns = [
        "package.json",
        "playwright.config.js",
        "playwright.config.ts",
        "fixtures/",
        "pageobjects/",
        "pages/",
        "tests/",
        "utils/",
        "helpers/",
        "config/",
    ]

    selected = []
    for rel in tree.splitlines():
        rel_norm = rel.replace("\\", "/")
        if any(rel_norm == p or rel_norm.startswith(p) for p in priority_patterns):
            selected.append(rel)

    chunks = []
    used = 0
    for rel in selected[:40]:
        path = repo / rel
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue

        if not text.strip():
            continue

        remaining = max_chars - used
        if remaining <= 0:
            break

        text = text[: min(len(text), 1200, remaining)]
        used += len(text)

        chunks.append(f"\nFILE: {rel}\n```text\n{text}\n```")

    return "\n".join(chunks)


def build_prompt(
    csv_summary: str,
    repo_tree: str,
    repo_context: str,
    output_folder: Path,
    create_new: bool
) -> tuple[str, str]:
    system_prompt = AUTOMATION_SKILL_PROMPT.strip()

    mode_text = "NEW REPOSITORY MODE" if create_new else "EXISTING REPOSITORY MODE"

    user_prompt = f"""
MODE
────────────────
{mode_text}

CSV TEST CASES
────────────────
{csv_summary}

REPOSITORY TREE
────────────────
{repo_tree}

EXISTING REPOSITORY CONTEXT / PATTERNS
────────────────
{repo_context if repo_context.strip() else "No existing source files were read."}

OUTPUT RULES
────────────────
- Generate files relative to this output folder: {output_folder}
- Do not use absolute paths in JSON.
- Do not create files outside the output folder.
- Use JavaScript.
- Use @playwright/test.
- Preserve CSV Test Case IDs in test names.
- Create/update only required files.
- Return ONLY JSON with files[] and notes[].

NEW REPO RULES, if mode is NEW REPOSITORY MODE:
- Create complete runnable Playwright JS project.
- Include package.json with scripts:
  - test
  - test:headed
  - test:ui
  - report
- Include playwright.config.js.
- Include README.md with setup/run commands.
- Include .gitignore.
- Include pageobjects/BasePage.js.
- Include feature page object.
- Include spec file.
- Include test data JSON.
- Include config utility for base URL.
- Use process.env.BASE_URL fallback.
""".strip()

    return system_prompt, user_prompt


def call_openai(system_prompt: str, user_prompt: str, model: str) -> str:
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        raise EnvironmentError("OPENAI_API_KEY not set.")

    from openai import OpenAI
    client = OpenAI(api_key=api_key)

    print(f"Calling OpenAI {model}...")
    response = client.chat.completions.create(
        model=model,
        temperature=0,
        max_tokens=16000,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )
    return response.choices[0].message.content.strip()


def call_anthropic(system_prompt: str, user_prompt: str, model: str) -> str:
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise EnvironmentError("ANTHROPIC_API_KEY not set.")

    import anthropic
    client = anthropic.Anthropic(api_key=api_key)

    print(f"Calling Anthropic {model}...")
    response = client.messages.create(
        model=model,
        max_tokens=16000,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
    )
    return response.content[0].text.strip()


def call_ai(system_prompt: str, user_prompt: str, model: str) -> str:
    m = model.lower()
    if m.startswith("gpt") or m.startswith("o"):
        return call_openai(system_prompt, user_prompt, model)
    if m.startswith("claude"):
        return call_anthropic(system_prompt, user_prompt, model)
    raise ValueError("Unsupported model. Use OpenAI gpt-* or Anthropic claude-* model.")


def parse_json_response(raw: str) -> dict:
    raw = re.sub(r"^```(?:json)?\s*", "", raw.strip())
    raw = re.sub(r"\s*```$", "", raw).strip()

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        debug_path = Path("qa_automation_writer_raw_response.txt")
        debug_path.write_text(raw, encoding="utf-8")
        raise ValueError(f"AI did not return valid JSON. Raw saved to {debug_path}") from e

    if "files" not in data or not isinstance(data["files"], list):
        raise ValueError("AI JSON must contain files[] list.")

    return data


def safe_output_path(output_folder: Path, relative_path: str) -> Path:
    if not relative_path or relative_path.startswith("/") or relative_path.startswith("~"):
        raise ValueError(f"Invalid relative output path: {relative_path}")

    normalized = Path(relative_path)
    if ".." in normalized.parts:
        raise ValueError(f"Path traversal not allowed: {relative_path}")

    final = (output_folder / normalized).resolve()
    output_resolved = output_folder.resolve()

    if output_resolved not in final.parents and final != output_resolved:
        raise ValueError(f"Output path escapes output folder: {relative_path}")

    return final


def write_files(data: dict, output_folder: Path, dry_run: bool = False, backup: bool = True):
    output_folder.mkdir(parents=True, exist_ok=True)
    written = []

    for item in data.get("files", []):
        rel = item.get("path", "").strip()
        content = item.get("content", "")
        action = item.get("action", "create")

        if not rel:
            raise ValueError("File item missing path.")
        if not isinstance(content, str):
            raise ValueError(f"File content must be string: {rel}")

        final_path = safe_output_path(output_folder, rel)
        print(f"{'[DRY RUN]' if dry_run else '[WRITE]'} {action.upper()} {final_path}")

        if dry_run:
            continue

        final_path.parent.mkdir(parents=True, exist_ok=True)

        if final_path.exists() and backup:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_path = final_path.with_suffix(final_path.suffix + f".bak_{ts}")
            backup_path.write_text(final_path.read_text(encoding="utf-8", errors="ignore"), encoding="utf-8")
            print(f"  Backup: {backup_path}")

        final_path.write_text(content.rstrip() + "\n", encoding="utf-8")
        written.append(str(final_path))

    return written


def main():
    parser = argparse.ArgumentParser(
        description="Generate/update Playwright JS POM automation files from manual test case CSV."
    )

    parser.add_argument("--csv", required=True, help="Path to manual test cases CSV.")
    parser.add_argument("--repo", required=True, help="Existing or new Playwright repository folder.")
    parser.add_argument("--output-folder", default="", help="Where files should be created/updated. Default: same as --repo.")
    parser.add_argument("--model", default="gpt-4o", help="Model name, e.g. gpt-4o, gpt-4o-mini, claude-sonnet-4-5.")
    parser.add_argument("--create-new", action="store_true", help="Create a new Playwright project if --repo does not exist.")
    parser.add_argument("--dry-run", action="store_true", help="Preview files without writing.")
    parser.add_argument("--no-backup", action="store_true", help="Do not create backups before overwriting existing files.")
    parser.add_argument("--max-tree-files", type=int, default=DEFAULT_MAX_TREE_FILES, help="Max repo files to include in tree.")
    parser.add_argument("--max-context-chars", type=int, default=DEFAULT_MAX_FILE_CHARS, help="Max chars from existing repo files.")

    args = parser.parse_args()

    csv_path = Path(args.csv).expanduser().resolve()
    repo = Path(args.repo).expanduser().resolve()
    output_folder = Path(args.output_folder).expanduser().resolve() if args.output_folder else repo

    repo_exists = repo.exists()
    if not repo_exists and not args.create_new:
        raise FileNotFoundError(
            f"Repo folder not found: {repo}\n"
            f"Use --create-new if you want to create a fresh Playwright project."
        )

    create_new_mode = args.create_new and not repo_exists

    print("\nQA Automation Writer")
    print("────────────────────")
    print(f"CSV          : {csv_path}")
    print(f"Repo         : {repo}")
    print(f"Output folder: {output_folder}")
    print(f"Model        : {args.model}")
    print(f"Mode         : {'new repo' if create_new_mode else 'existing repo'}")
    print(f"Write mode   : {'dry-run' if args.dry_run else 'write files'}")

    rows = read_csv_cases(csv_path)
    print(f"\nLoaded CSV test cases: {len(rows)}")
    csv_summary = compact_test_cases(rows)

    if create_new_mode:
        repo_tree = NEW_REPO_TREE.strip()
        repo_context = ""
        print("Repo does not exist. New repo mode enabled.")
    else:
        repo_tree = scan_repo_tree(repo, args.max_tree_files)
        repo_context = read_relevant_repo_files(repo, repo_tree, args.max_context_chars)
        print(f"Repo files scanned: {len(repo_tree.splitlines()) if repo_tree else 0}")

    system_prompt, user_prompt = build_prompt(
        csv_summary=csv_summary,
        repo_tree=repo_tree,
        repo_context=repo_context,
        output_folder=output_folder,
        create_new=create_new_mode,
    )

    raw = call_ai(system_prompt, user_prompt, args.model)
    data = parse_json_response(raw)

    notes = data.get("notes", [])
    if notes:
        print("\nAI notes:")
        for n in notes:
            print(f"- {n}")

    written = write_files(
        data=data,
        output_folder=output_folder,
        dry_run=args.dry_run,
        backup=not args.no_backup,
    )

    print("\nDone.")
    if args.dry_run:
        print("Dry run completed. Re-run without --dry-run to create/update files.")
    else:
        print(f"Files written: {len(written)}")
        for p in written:
            print(f"- {p}")

        if create_new_mode:
            print("\nNext commands:")
            print(f"cd {output_folder}")
            print("npm install")
            print("npx playwright install")
            print("npm test")


if __name__ == "__main__":
    main()

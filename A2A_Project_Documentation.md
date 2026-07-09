# A2A Project Prototype — Technical Documentation

**Branch documented:** `planner_agent`
**Repository:** `ibrahimammar931-lab/A2A-Project-Prototype`

## 1. Overview

This project is a prototype multi-agent system built on FastAPI microservices that automates the "pick up a Jira ticket and produce a reviewed, committed code change" workflow. Each responsibility — reading the ticket, understanding the repository, planning the work, writing code, reviewing it, and pushing it to GitHub — is isolated into its own service. An **Orchestrator** service owns the end-to-end sequencing and is the only component allowed to call every other agent; the agents themselves do not call each other directly.

Code generation and review are performed by LLM calls to Groq's OpenAI-compatible API (`https://api.groq.com/openai/v1`), using the `openai` Python SDK pointed at that base URL.

### 1.1 Services and ports

| Service | File | Default Port | Role |
|---|---|---|---|
| Developer Agent | `developer_agent.py` | 8000 | Generates and revises code |
| Jira Agent | `jira_agent.py` | 8001 | Fetches and normalizes Jira tickets |
| Reviewer Agent | `reviewer_agent.py` | 8002 | Reviews proposed code changes |
| Orchestrator Agent | `orchestrator_agent.py` | 8003 | Coordinates the full workflow |
| Repo Agent | `repo_agent.py` | 8004 | Local git + GitHub API operations |
| Knowledge Agent | `knowledge_agent.py` | 8005 | Builds/maintains structured repo knowledge |
| Planner Agent | `planner_agent.py` | 8006 | Turns a ticket + knowledge into an implementation plan |

Ports are configurable via environment variables in `config.py` (`*_SERVICE_URL`), so the table shows the shipped defaults, not hardcoded values.

### 1.2 Shared building blocks

- **`schemas.py`** — every Pydantic model used across services (requests, responses, and the `AgentMessage` envelope used for inter-agent communication).
- **`config.py`** — loads `.env` via `python-dotenv` and exposes typed config values plus two guard functions, `check_config()` (Groq key) and `check_jira_config()` (Jira credentials), each raising `RuntimeError` when required values are missing.
- **`AgentMessage`** — a generic envelope (`sender`, `receiver`, `message_type`, `payload: dict`) used whenever one agent's output is logged as part of the workflow or passed to another agent (e.g. review requests/responses, developer improvement requests).

---

## 2. Architecture Diagram

```
                              ┌─────────────────────┐
                              │   Orchestrator       │
                              │   (port 8003)         │
                              │  POST /work-on-ticket │
                              └──────────┬───────────┘
                                         │
        ┌────────────────┬──────────────┼──────────────┬───────────────┬──────────────┐
        ▼                ▼              ▼              ▼               ▼              ▼
   ┌─────────┐     ┌───────────┐  ┌────────────┐  ┌───────────┐  ┌────────────┐  ┌───────────┐
   │  Jira   │     │   Repo    │  │ Knowledge  │  │  Planner  │  │ Developer  │  │ Reviewer  │
   │ Agent   │     │  Agent    │  │   Agent    │  │   Agent   │  │   Agent    │  │   Agent   │
   │ (8001)  │     │  (8004)   │  │  (8005)    │  │  (8006)   │  │  (8000)    │  │  (8002)   │
   └─────────┘     └───────────┘  └────────────┘  └───────────┘  └────────────┘  └───────────┘
```

Only the Orchestrator talks to every other service. No agent calls another agent directly — in particular, the Planner Agent never calls the Repo Agent or Developer Agent, and the Developer Agent never calls Jira or the Reviewer. This is a deliberate design constraint, enforced structurally (each agent's code has no HTTP client pointed at another agent), not just documented.

---

## 3. End-to-End Workflow: `POST /work-on-ticket`

This is the single entry point of the whole system, exposed by the Orchestrator. It accepts a `GenerateRequest`:

```json
{
  "issue_key": "PROJ-123",
  "base_branch": "main"
}
```

### 3.1 Step-by-step sequence

1. **Fetch the ticket** — `GET {JIRA_SERVICE_URL}/tickets/{issue_key}` → `JiraTicket`.
2. **Build a task prompt** from the ticket (`ticket_to_task`), a plain-text block containing key, URL, summary, type, status, priority, assignee, reporter, labels, components, description, and custom fields.
3. **Prepare the repo** — `POST {REPO_SERVICE_URL}/prepare-repo` (clones or fetches the configured/target GitHub repo locally) → `RepoInfo`.
4. **Ensure knowledge exists** — `POST {KNOWLEDGE_SERVICE_URL}/ensure-knowledge` with the local repo path. Builds a structured knowledge base if one doesn't exist yet, or loads the existing one.
5. **Plan the work** — `POST {PLANNER_SERVICE_URL}/plan` with the ticket and the knowledge dict → `PlanningResult`. If the planner returns an empty `likely_files` list, the Orchestrator **aborts the workflow** with a `ValueError` ("Refusing to let the Developer create files without repository context").
6. **Create a branch** — `POST {REPO_SERVICE_URL}/create-branch` using the ticket key/title/base branch → `BranchResponse`.
7. **Read planned files** — `POST {REPO_SERVICE_URL}/read-files` for every path in `planning_result.likely_files` (deduplicated) → list of `RepoFile`.
8. **Generate original code** — `POST {DEVELOPER_SERVICE_URL}/generate` with the task, ticket, planning result, and repo files → `DeveloperOutput`. The Orchestrator then calls `validate_planned_changes`, which rejects the output if the Developer touched any file outside the Planner-selected set.
9. **Build a diff** locally (`build_review_diff`, using Python's `difflib.unified_diff`) between the original repo file contents and the Developer's proposed changes.
10. **Request a review** — `POST {REVIEWER_SERVICE_URL}/review`, wrapped in an `AgentMessage`, containing the task, ticket, planning result, diff, changes, explanation, and repo files → returns an `AgentMessage` whose payload is a `ReviewFeedback`.
11. **Conditionally regenerate** — if `review_feedback.requires_revision` is true **and** there are `blocking_issues`, the Orchestrator filters the feedback down to only the blocking issues (optional suggestions are dropped) and calls `POST {DEVELOPER_SERVICE_URL}/improve`. The improved output is again validated against the Planner-selected file set. If no revision is required, the "improved" code is just the original output.
12. **Apply changes to GitHub** — if there are file changes, `POST {REPO_SERVICE_URL}/apply-changes` commits each change directly through the GitHub Contents API on the created branch.
13. **Update knowledge** — `POST {KNOWLEDGE_SERVICE_URL}/update-knowledge` for the changed files only (incremental re-summarization).
14. **Record a synthetic diff/commit/push** — the Orchestrator builds a textual diff summary and `CommitResponse`/`PushResponse` objects from the `apply-changes` result (there's no separate git commit/push step against the local clone; GitHub API commits already happened in step 12).
15. **Open a pull request** — `POST {REPO_SERVICE_URL}/open-pr` with the ticket-derived title/summary/branches → `PullRequestResponse`.
16. **Return `GenerateResponse`** — the full trace: ticket, original code, review feedback, improved code, every `AgentMessage` exchanged, planning result, repo info, branch, repo files read, applied changes, diff, commit, push, and pull request.

### 3.2 Error handling

Every step that calls another service goes through `post_or_raise` (or an inline `raise_for_status()`), which converts a failing HTTP call into an `HTTPException(502)` naming the failing step. Workflow-level validation failures (e.g. no `likely_files`, Developer touching disallowed files) raise `ValueError`, which the top-level handler turns into `HTTPException(502)`. Anything unexpected becomes a generic `HTTPException(500)`.

---

## 4. Service Reference

### 4.1 Jira Agent (`jira_agent.py`, port 8001)

**Purpose:** wraps the Jira REST API v3 and normalizes a raw issue into the shared `JiraTicket` schema.

**Endpoint**

| Method | Path | Description |
|---|---|---|
| GET | `/tickets/{issue_key}` | Fetches one issue and returns a `JiraTicket` |

**Behavior**
- Requires `JIRA_BASE_URL`, `JIRA_EMAIL`, `JIRA_API_TOKEN` (checked via `check_jira_config()`); missing config raises `HTTPException(500)`.
- Calls `GET {JIRA_BASE_URL}/rest/api/3/issue/{issue_key}` with HTTP Basic Auth (`email` / `API token`).
- `extract_jira_text` recursively flattens Jira's Atlassian Document Format (ADF) `description` field into plain text.
- `get_custom_fields` collects every `customfield_*` key with a non-empty value and simplifies nested objects (`name` / `value` / `displayName` / ADF `content`) into plain values via `simplify_value`.
- A failed Jira API call becomes `HTTPException(502)`; any other failure is `HTTPException(500)`.

### 4.2 Knowledge Agent (`knowledge_agent.py`, port 8005)

**Purpose:** maintains a structured, per-file "knowledge base" describing the target repository, without storing raw source code, so the Planner and Developer agents can reason about the codebase cheaply.

**Endpoints**

| Method | Path | Description |
|---|---|---|
| POST | `/ensure-knowledge` | Loads existing knowledge for a repo path, or builds it if missing |
| POST | `/build-knowledge` | Forces a full rebuild of the knowledge base |
| POST | `/update-knowledge` | Incrementally updates knowledge for a given list of `FileChange` |
| GET | `/load-knowledge` | Loads existing knowledge (raises if none exists) |

**Behavior**
- Knowledge is stored on disk under `<repository_path>/knowledge/`, mirroring the source tree with one `.json` summary per source file, plus a `metadata.json` (version, generation timestamp, repo path, file count).
- `build_knowledge` walks the repo, skipping `IGNORED_DIRS` (`.git`, `node_modules`, `__pycache__`, `build`, `dist`, `venv`, `.venv`, `env`, `knowledge`, cache dirs) and only considering `SOURCE_EXTENSIONS` (`.py .js .ts .jsx .tsx .go .rs .java .kt .md .yaml .yml .json`). It wipes and regenerates the knowledge directory each time it's called.
- `_summarize_file` sends each file's content (truncated at 15,000 characters) to Groq (model = `GROQ_MODEL`, `temperature=0.0`, forced JSON) with a system prompt explicitly instructing it *not* to return source code, only a structured summary: `path`, `file_purpose`, `summary`, `classes`, `functions`, `imports`, `exports`, `metadata`. If the LLM call fails, a regex-free heuristic fallback extracts `import`/`from`, `def`, and `class` lines directly from the source as a degraded summary.
- `update_knowledge` only touches the files listed in the provided `FileChange` list: deletions remove the corresponding knowledge `.json`; creates/updates re-summarize either the provided `content` or, if absent, the current on-disk file content.
- `project_knowledge` (the dict returned by `ensure-knowledge`/`load-knowledge`) is what's passed into the Planner Agent as context.

### 4.3 Planner Agent (`planner_agent.py`, port 8006)

**Purpose:** turns a Jira ticket plus the project's knowledge base into a structured implementation plan — and only that. It never writes code, edits files, calls other agents, or reviews anything, both by prompt instruction and by having no HTTP client to other services.

**Endpoint**

| Method | Path | Description |
|---|---|---|
| POST | `/plan` | Produces a `PlanningResult` from a `PlanningRequest` |

**Request/response**
```json
// PlanningRequest
{ "jira_ticket": { ... JiraTicket ... }, "project_knowledge": { ... } }
```
```json
// PlanningResult
{
  "task_summary": "...",
  "requirements": ["..."],
  "implementation_steps": ["..."],
  "likely_modules": ["..."],
  "likely_files": ["..."],
  "acceptance_criteria": ["..."],
  "risks": ["..."],
  "complexity": "Low | Medium | High"
}
```

**Behavior**
- Uses `GROQ_PLANNER_MODEL` (falls back to `GROQ_MODEL` if unset), `temperature=0.1`, forced JSON output.
- The system/user prompt instructs the model to prefer existing files over new ones, choose the smallest sufficient `likely_files` list for small tickets, and pick `likely_files` from the supplied `project_knowledge`.
- After parsing the model's JSON into a `PlanningResult`, the agent **filters `likely_files` down to paths that actually exist in `project_knowledge["files"]`** — this is a hard guarantee, not just a prompt instruction, that the plan can't point the Developer at files the knowledge base doesn't know about.
- Empty/invalid model output raises `ValueError` → `HTTPException(502)`; anything else unexpected is `HTTPException(500)`.

### 4.4 Developer Agent (`developer_agent.py`, port 8000)

**Purpose:** generates and revises code for a task, constrained to a specific set of allowed files.

**Endpoints**

| Method | Path | Description |
|---|---|---|
| POST | `/generate` | Generates original code from a task → `DeveloperOutput` |
| POST | `/improve` | Revises code based on review feedback → `AgentMessage` |

**Behavior**
- Uses `GROQ_MODEL`, `temperature=0.2`, forced JSON. Both prompts require the model to return exactly `code`, `explanation`, `changes` (a list of `{path, action, content}`), with `content` being the *full* file contents after the edit, not a diff or summary.
- `format_allowed_files` builds an explicit constraint block in the prompt: if repo files were provided, the model may only modify those paths (no new files, no renames); if none were provided, it may create new files only if the ticket explicitly requires it.
- `/generate` takes an `AgentTaskRequest` (`task`, optional `ticket`, optional `planning_result`, `repo_files`) directly and returns a `DeveloperOutput`.
- `/improve` takes an `AgentMessage` whose `payload` must contain `task`, `original_code`, `review_feedback`, and optionally `planning_result` / `repo_files`; it returns a new `AgentMessage` (`sender="developer_agent"`) wrapping the improved `DeveloperOutput`.
- `DeveloperOutput.changes` is validated by a Pydantic `field_validator` (`schemas.py`): for `create`/`update`/`upsert` actions, `content` must be present and must "look like code" (multi-line, or containing a marker like `def `, `class `, `import `, etc.) via `_looks_like_code` — this rejects trivial/placeholder responses from the LLM before they ever reach the Orchestrator.
- Both endpoints share the same error mapping: `ValueError` (bad/empty model output) → `HTTPException(502)`, anything else → `HTTPException(500)`.

### 4.5 Reviewer Agent (`reviewer_agent.py`, port 8002)

**Purpose:** reviews a proposed diff against the ticket, separating blocking issues from optional/style feedback.

**Endpoint**

| Method | Path | Description |
|---|---|---|
| POST | `/review` | Reviews a change described in an `AgentMessage` → `AgentMessage` wrapping `ReviewFeedback` |

**Behavior**
- Input `AgentMessage.payload` must contain `task` and `explanation`; `ticket`, `diff`, and `repo_files` are optional context.
- Uses `GROQ_REVIEWER_MODEL`, `temperature=0.1`, forced JSON. The system prompt explicitly tells the model to judge the change against ticket requirements rather than personal style, and to separate `blocking_issues` from `optional_suggestions`, each structured as `{category, severity, summary, recommendation, location, ticket_relevant}`.
- Output is parsed straight into `ReviewFeedback` (`approved`, `decision`, `summary`, `issues`, `suggestions`, `security_notes`, `quality_notes`, `blocking_issues`, `optional_suggestions`, `requires_revision`, `rationale`).
- Returns an `AgentMessage` with `sender="reviewer_agent"`, `receiver="developer_agent"` — even though the Reviewer never calls the Developer directly; the Orchestrator uses this addressing to decide where the feedback should conceptually route.
- Errors follow the same `ValueError` → 502 / other → 500 pattern as the other LLM-backed agents.

### 4.6 Repo Agent (`repo_agent.py`, port 8004)

**Purpose:** the only service that touches git and the GitHub API. It manages a local workspace clone (for reading files/diffs) and performs all writes — branch creation, file changes, and pull requests — through GitHub's REST API rather than pushing a local commit.

**Endpoints**

| Method | Path | Description |
|---|---|---|
| POST | `/prepare-repo` | Clones the repo if absent, or fetches updates if present → `RepoInfo` |
| POST | `/create-branch` | Creates a new branch in GitHub from a base branch, then checks it out locally → `BranchResponse` |
| POST | `/read-files` | Reads specific file paths from the local clone → `ReadFilesResponse` |
| POST | `/apply-changes` | Applies a list of `FileChange` directly via the GitHub Contents API → `ApplyChangesResponse` |
| POST | `/diff` | Returns the local `git diff` for the working tree → `RepoDiffResponse` |
| POST | `/commit` | Builds a commit message/response object (does not itself create a local commit) → `CommitResponse` |
| POST | `/push` | Validates a branch is set and echoes back a `PushResponse` (no local git push is performed) → `PushResponse` |
| POST | `/open-pr` | Opens a GitHub pull request → `PullRequestResponse` |

**Key implementation details**
- **Workspace layout:** each repo is cloned under `REPO_WORKSPACE_ROOT/<slugified-repo-id>` (default root: `workspaces/`). `repo_id_from_url` derives a stable `owner-repo` slug from any GitHub URL form (HTTPS or SSH).
- **Path safety:** `safe_repo_file` and `repo_path_for` both resolve paths and check they stay within the workspace/repo root, rejecting absolute paths or `..`-style escapes — this guards `/read-files` against path traversal.
- **Branch naming:** `build_branch_name` produces `agent/{ISSUE_KEY}-{slugified-title}`, truncated to 80 characters. `unique_github_branch_name` / `unique_branch_name` append `-2`, `-3`, ... if the branch already exists (checked against both GitHub and the local clone as applicable).
- **File writes go through the GitHub Contents API**, not local git commits: `github_put_file_with_retry` fetches the current file (for its `sha`, required by GitHub to update a file) and PUTs the new content; on a `409` SHA conflict it refetches and retries once. `github_delete_file` similarly needs the current `sha`.
- **`normalize_change_action`** maps a wide range of natural-language actions the LLM might emit (`add`, `created`, `modify`, `refactored`, `replace`, `written`, ...) onto exactly two internal actions: `upsert` or `delete`.
- **`/apply-changes`** loops over each `FileChange`: `upsert` actions call `github_put_file_with_retry`; `delete` actions look the file up first and only call `github_delete_file` if it exists (a delete for a nonexistent file is a silent no-op, not an error).
- **`/open-pr`** builds the PR title as `"{ISSUE_KEY.upper()} {title}"` (capped at 256 characters) and a structured Markdown body (`build_pr_body`) with Summary / Ticket / optional Tests / a fixed Notes section stating the PR was created by the Repo Agent and is not auto-merged.
- **Auth:** all GitHub API calls require `GITHUB_TOKEN`; its absence raises `ValueError` inside `github_headers()`, surfaced as `HTTPException(400)` from the relevant endpoint.
- **Errors:** git subprocess failures → `HTTPException(502)`; validation errors (`ValueError`) → `HTTPException(400)`; GitHub API HTTP errors → `HTTPException(502)` with the raw GitHub error body attached for debugging; anything else → `HTTPException(500)`.

### 4.7 Orchestrator Agent (`orchestrator_agent.py`, port 8003)

Documented in full in **Section 3**. This is the only service with an HTTP client pointed at every other agent, and the only place workflow-level decisions (e.g. "should we regenerate the code?", "did the Developer touch files it wasn't supposed to?") are made.

Two orchestrator-only helper functions are worth calling out:
- **`build_review_diff`** — builds a unified diff (via Python's standard `difflib`) between each changed file's original content (from `repo_files`) and the Developer's proposed new content, purely for the Reviewer's benefit; this diff is never sent to GitHub.
- **`validate_planned_changes`** — cross-checks the Developer's `changes` paths against the set of file paths actually read from the repo (the Planner's `likely_files`, as resolved by the Repo Agent). Any change to a path outside that set raises `ValueError`, aborting the workflow before anything is written to GitHub. This is the main safeguard that keeps the LLM-driven Developer from touching arbitrary files.

---

## 5. Data Model Reference (`schemas.py`)

| Model | Used by | Key fields |
|---|---|---|
| `JiraTicket` | Jira, Orchestrator, Planner, Developer, Reviewer | `key`, `url`, `summary`, `description`, `issue_type`, `status`, `priority`, `assignee`, `reporter`, `labels`, `components`, `custom_fields` |
| `RepoInfo` | Repo, Orchestrator | `repo_id`, `path`, `current_branch`, `remote_url`, `status` |
| `BranchResponse` | Repo, Orchestrator | `repo_id`, `branch`, `base_branch` |
| `RepoFile` | Repo, Orchestrator, Developer, Reviewer | `path`, `content` |
| `FileChange` | Developer, Repo, Knowledge | `path`, `action`, `content` (nullable) |
| `PlanningRequest` / `PlanningResult` | Planner, Orchestrator | see Section 4.3 |
| `AgentTaskRequest` | Developer (`/generate`) | `task`, `ticket`, `planning_result`, `repo_files` |
| `DeveloperOutput` | Developer, Orchestrator | `explanation`, `changes: list[FileChange]`, `code` — with validators coercing `code` to `str` and rejecting non-code `content` in `changes` |
| `ReviewIssue` | Reviewer | `category`, `severity`, `summary`, `recommendation`, `location`, `ticket_relevant` |
| `ReviewFeedback` | Reviewer, Orchestrator, Developer | `approved`, `decision`, `summary`, `issues`, `suggestions`, `security_notes`, `quality_notes`, `blocking_issues: list[ReviewIssue]`, `optional_suggestions: list[ReviewIssue]`, `requires_revision`, `rationale` |
| `AgentMessage` | all inter-agent calls | `sender`, `receiver`, `message_type`, `payload: dict` |
| `GenerateRequest` | Orchestrator entry point | `issue_key`, `base_branch` |
| `GenerateResponse` | Orchestrator entry point | full workflow trace (ticket, code, review, plan, repo/branch/files, applied changes, diff, commit, push, PR, messages) |
| `PrepareRepoRequest` / `CreateBranchRequest` / `ReadFilesRequest` / `ReadFilesResponse` | Repo | see Section 4.6 |
| `ApplyChangesRequest` / `ApplyChangesResponse` | Repo | `changes`, `branch`, `commit_message` → `changed_files`, `commit_shas` |
| `RepoDiffRequest` / `RepoDiffResponse` | Repo | `repo_url` → `repo_id`, `diff` |
| `CommitRequest` / `CommitResponse` | Repo | `issue_key`, `summary`, `body` → `commit_sha`, `message` |
| `PushRequest` / `PushResponse` | Repo | `branch` → `repo_id`, `branch`, `remote` |
| `PullRequestRequest` / `PullRequestResponse` | Repo | `title`, `summary`, `base_branch`, `head_branch`, `draft`, `ticket_url`, `test_results` → `number`, `url`, `title` |

---

## 6. Configuration Reference (`config.py` / `.env`)

| Variable | Required by | Purpose |
|---|---|---|
| `GROQ_API_KEY` | Developer, Reviewer, Planner, Knowledge | Groq API key; checked by `check_config()` |
| `GROQ_MODEL` | Developer, Knowledge (default model) | e.g. `llama-3.3-70b-versatile` |
| `GROQ_REVIEWER_MODEL` | Reviewer | Defaults to `GROQ_MODEL` if unset |
| `GROQ_PLANNER_MODEL` | Planner | Defaults to `GROQ_MODEL` if unset |
| `LOG_LEVEL` | all | Passed to `logging.basicConfig` |
| `JIRA_BASE_URL`, `JIRA_EMAIL`, `JIRA_API_TOKEN` | Jira | Checked by `check_jira_config()` |
| `JIRA_SERVICE_URL`, `REVIEWER_SERVICE_URL`, `DEVELOPER_SERVICE_URL`, `REPO_SERVICE_URL`, `KNOWLEDGE_SERVICE_URL`, `PLANNER_SERVICE_URL` | Orchestrator | Base URLs for each downstream service (default to `127.0.0.1:800x`) |
| `GITHUB_REPO_URL` | Repo | Default repo to prepare when a request doesn't specify one |
| `GITHUB_TOKEN` | Repo | Required for any GitHub API write (branches, file writes, PRs) |
| `REPO_WORKSPACE_ROOT` | Repo | Local clone root directory (default: `workspaces`) |

---

## 7. Running the Project Locally

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
# edit .env with your GROQ_API_KEY, Jira credentials, GITHUB_TOKEN, GITHUB_REPO_URL
```

Then start each service in its own terminal:

```bash
uvicorn jira_agent:app --port 8001 --reload
uvicorn reviewer_agent:app --port 8002 --reload
uvicorn developer_agent:app --port 8000 --reload
uvicorn orchestrator_agent:app --port 8003 --reload
uvicorn repo_agent:app --port 8004 --reload
uvicorn knowledge_agent:app --port 8005 --reload
uvicorn planner_agent:app --port 8006 --reload
```

Each service exposes interactive Swagger docs at `http://127.0.0.1:<port>/docs`.

Trigger the full workflow:

```bash
curl -X POST http://127.0.0.1:8003/work-on-ticket \
  -H "Content-Type: application/json" \
  -d "{\"issue_key\":\"PROJ-123\",\"base_branch\":\"main\"}"
```

---

## 8. Design Notes and Guardrails

A few constraints are enforced in code, not just documentation, and are worth calling out because they define the safety envelope of the system:

1. **Planner → Developer file scoping.** The Planner filters `likely_files` to paths present in the knowledge base; the Orchestrator refuses to proceed if that list is empty; and after the Developer runs, `validate_planned_changes` rejects any change outside those files. Three independent checks constrain what the LLM-driven Developer is allowed to touch.
2. **Structural role separation.** No agent module imports an HTTP client pointed at another agent except the Orchestrator — the "only the Orchestrator coordinates" rule from the README is a property of the code, not just a convention.
3. **Content sanity-checking on LLM output.** `DeveloperOutput`'s Pydantic validator rejects file changes whose `content` doesn't look like code, catching a class of degenerate/truncated LLM responses before they reach the Repo Agent.
4. **Selective revision.** The Orchestrator only sends *blocking* review issues back to the Developer for a second pass; optional/style suggestions are dropped from the improvement request, keeping revision cycles focused on ticket-breaking problems.
5. **GitHub-API-first repo writes.** All repository mutations (branch creation, file changes, deletions, PRs) go through the GitHub REST API rather than local `git commit && git push`, which sidesteps needing push credentials configured for the local clone and keeps every write auditable as a GitHub commit/PR.

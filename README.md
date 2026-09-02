# A2A Multi-Agent Automation System

A2A is a local prototype for automating a software development workflow with specialized agents. Starting from a Jira ticket, the system prepares a target repository, builds repository knowledge, plans the implementation, generates code, reviews the proposed changes, applies them to a branch or local folder, and can open a GitHub pull request.

The backend is a set of FastAPI services. The frontend is an Angular dashboard used to start, monitor, and manually control the workflow.

## Features

- Jira ticket loading and normalization.
- GitHub repository preparation, branch creation, file updates, and pull request creation.
- Local-folder mode for applying changes directly to an existing local Git checkout.
- Branch-scoped repository knowledge generation and incremental refresh.
- LLM-based planning, code generation, review, repository summarization, and model selection.
- Manual workflow mode with operator approval before each agent runs.
- Automatic workflow mode that runs the full pipeline without manual approval.
- Angular dashboard with pipeline visualization, agent inspection, model selection, message editing, and execution-log export.

## Architecture

Each agent is a separate FastAPI service. The orchestrator coordinates them over HTTP and exposes dashboard APIs under `/api/workflow/*`.

| Service | File | Port | Responsibility |
|---|---:|---:|---|
| Developer Agent | `agents/developer_agent.py` | `8000` | Generates initial code and revises it after review feedback. |
| Jira Agent | `agents/jira_agent.py` | `8001` | Fetches Jira issues and converts them into the shared `JiraTicket` schema. |
| Reviewer Agent | `agents/reviewer_agent.py` | `8002` | Reviews proposed diffs and returns structured feedback. |
| Repo Agent | `agents/repo_agent.py` | `8004` | Clones/fetches repositories, handles branches, applies file changes, and opens PRs. |
| Knowledge Agent | `agents/knowledge_agent.py` | `8005` | Builds and updates repository knowledge summaries. |
| Planner Agent | `agents/planner_agent.py` | `8006` | Produces an implementation plan from the ticket and repository knowledge. |
| Model Selector Agent | `agents/model_selector_agent.py` | `8007` | Selects the best available LLM for each workflow role. |
| Orchestrator Agent | `agents/orchestrator_agent.py` | `8010` | Runs the workflow and serves dashboard control/state APIs. |
| Angular Dashboard | `dashboard/` | `4200` | Visual control center for the workflow. |

## Repository Layout

```text
A2A/
|-- README.md
|-- SETUP.md
|-- requirements.txt
|-- run_all.ps1
|-- model_selection.json
|-- agents/
|   |-- developer_agent.py
|   |-- jira_agent.py
|   |-- knowledge_agent.py
|   |-- model_selector_agent.py
|   |-- orchestrator_agent.py
|   |-- planner_agent.py
|   |-- repo_agent.py
|   `-- reviewer_agent.py
|-- shared/
|   |-- available_models.py
|   |-- config.py
|   `-- schemas.py
`-- dashboard/
    |-- angular.json
    |-- package.json
    |-- proxy.conf.json
    `-- src/
```

## Requirements

- Python 3.11+
- Git
- Node.js and npm for the Angular dashboard
- Jira API credentials
- At least one configured LLM provider API key
- GitHub token and repository URL for GitHub mode

Python dependencies are listed in `requirements.txt`. Frontend dependencies are listed in `dashboard/package.json`.

## Configuration

Copy the example environment file and fill in real values:

```powershell
Copy-Item .env.example .env
```

Important environment variables:

```env
LOG_LEVEL=INFO

# Model providers
GROQ_API_KEY=your_groq_api_key
OPENROUTER_API_KEY=your_openrouter_api_key
GOOGLE_API_KEY=your_google_api_key
DEEPSEEK_API_KEY=your_deepseek_api_key

# Optional default model overrides
A2A_DEFAULT_MODEL=groq/llama-3.3-70b-versatile
GROQ_MODEL=groq/llama-3.3-70b-versatile
GROQ_REVIEWER_MODEL=groq/llama-3.3-70b-versatile
GROQ_PLANNER_MODEL=groq/llama-3.3-70b-versatile
A2A_LLM_MAX_TOKENS=32768

# Jira
JIRA_BASE_URL=https://your-domain.atlassian.net
JIRA_EMAIL=your_email@example.com
JIRA_API_TOKEN=your_jira_api_token

# Service URLs
DEVELOPER_SERVICE_URL=http://127.0.0.1:8000
JIRA_SERVICE_URL=http://127.0.0.1:8001
REVIEWER_SERVICE_URL=http://127.0.0.1:8002
REPO_SERVICE_URL=http://127.0.0.1:8004
KNOWLEDGE_SERVICE_URL=http://127.0.0.1:8005
PLANNER_SERVICE_URL=http://127.0.0.1:8006
MODEL_SELECTOR_SERVICE_URL=http://127.0.0.1:8007

# Repository
GITHUB_REPO_URL=https://github.com/owner/project.git
GITHUB_TOKEN=your_github_token
REPO_WORKSPACE_ROOT=workspaces
LOCAL_KNOWLEDGE_ROOT=workspaces/knowledge
DEFAULT_BASE_BRANCH=main
DEFAULT_ISSUE_KEY=A2A-184
```

Model choices shown in the dashboard come from `shared/available_models.py`. Persisted per-agent selections are stored in `model_selection.json`.

## Install

Create and activate a Python virtual environment:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Install backend dependencies:

```powershell
pip install -r requirements.txt
```

Install dashboard dependencies:

```powershell
cd dashboard
npm install
cd ..
```

## Run the Backend

The agent modules live in `agents/`, while shared modules live in `shared/`. Because the current Python files import `config`, `schemas`, and `available_models` as top-level modules, add both folders to `PYTHONPATH` before running Uvicorn.

PowerShell:

```powershell
$env:PYTHONPATH = "$PWD\agents;$PWD\shared"
```

Then start each service from the project root in separate terminals:

```powershell
uvicorn agents.jira_agent:app --port 8001 --reload
```

```powershell
uvicorn agents.reviewer_agent:app --port 8002 --reload
```

```powershell
uvicorn agents.developer_agent:app --port 8000 --reload
```

```powershell
uvicorn agents.repo_agent:app --port 8004 --reload
```

```powershell
uvicorn agents.knowledge_agent:app --port 8005 --reload
```

```powershell
uvicorn agents.planner_agent:app --port 8006 --reload
```

```powershell
uvicorn agents.model_selector_agent:app --port 8007 --reload
```

```powershell
uvicorn agents.orchestrator_agent:app --port 8010 --reload
```

You can also use `run_all.ps1` to launch all services in separate PowerShell windows:

```powershell
.\run_all.ps1
```

## Run the Dashboard

The dashboard is configured to proxy `/api` to the orchestrator on `http://127.0.0.1:8010`.

```powershell
cd dashboard
npm start
```

Open:

```text
http://localhost:4200
```

## FastAPI Docs

Once services are running, Swagger UI is available at:

```text
Developer Agent:      http://127.0.0.1:8000/docs
Jira Agent:           http://127.0.0.1:8001/docs
Reviewer Agent:       http://127.0.0.1:8002/docs
Repo Agent:           http://127.0.0.1:8004/docs
Knowledge Agent:      http://127.0.0.1:8005/docs
Planner Agent:        http://127.0.0.1:8006/docs
Model Selector Agent: http://127.0.0.1:8007/docs
Orchestrator Agent:   http://127.0.0.1:8010/docs
```

## Workflow

The dashboard starts and controls the workflow through the orchestrator.

Normal execution order:

1. Fetch the Jira ticket.
2. Prepare the repository workspace.
3. Optionally run model selection.
4. Ensure branch-specific repository knowledge exists.
5. Plan the implementation.
6. Read the files selected by the planner.
7. Generate code changes.
8. Review the generated diff.
9. Revise the code if blocking review issues exist.
10. Apply changes and update repository knowledge.
11. Open a pull request when GitHub mode and `open_pr` are enabled.

Key orchestrator endpoints:

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/api/workflow/state` | Return the current dashboard snapshot. |
| WebSocket | `/ws/workflow` | Stream workflow state changes to the dashboard. |
| POST | `/api/workflow/start` | Start or reset a workflow. |
| POST | `/api/workflow/run-next-agent` | Run the next agent in manual mode. |
| POST | `/api/workflow/set-mode` | Switch between `manual` and `automatic`. |
| POST | `/api/workflow/model-selection` | Save manual model choices. |
| POST | `/api/workflow/set-auto-model-selection` | Enable or disable automatic model selection. |

## Agent Endpoints

### Jira Agent

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/tickets/{issue_key}` | Fetch and normalize a Jira issue. |

### Developer Agent

| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/generate` | Generate initial code changes. |
| POST | `/improve` | Improve code using reviewer feedback. |

### Reviewer Agent

| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/review` | Review proposed code changes. |

### Repo Agent

| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/prepare-repo` | Clone, fetch, or validate a repository workspace. |
| POST | `/create-branch` | Create a GitHub branch for the ticket. |
| POST | `/read-files` | Read UTF-8 text files selected by the planner. |
| POST | `/apply-changes` | Apply create/update/delete file changes. |
| POST | `/diff` | Return the local working-tree diff. |
| POST | `/commit` | Build commit metadata response. |
| POST | `/push` | Build push metadata response. |
| POST | `/open-pr` | Open a GitHub pull request. |

### Knowledge Agent

| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/ensure-knowledge` | Load, build, copy, or refresh branch knowledge. |
| POST | `/build-knowledge` | Rebuild repository knowledge from source files. |
| POST | `/update-knowledge` | Update knowledge for changed files. |
| GET | `/load-knowledge` | Load stored branch knowledge. |
| POST | `/sync-branches` | Synchronize knowledge folders with remote branches. |

### Planner Agent

| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/plan` | Produce a structured implementation plan. |

### Model Selector Agent

| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/select-models` | Choose models for knowledge, planner, developer, and reviewer roles. |

## Validate the Backend

Run a syntax check from the project root:

```powershell
$env:PYTHONPATH = "$PWD\agents;$PWD\shared"
.\.venv\Scripts\python.exe -m py_compile `
  agents\jira_agent.py `
  agents\developer_agent.py `
  agents\reviewer_agent.py `
  agents\repo_agent.py `
  agents\knowledge_agent.py `
  agents\planner_agent.py `
  agents\model_selector_agent.py `
  agents\orchestrator_agent.py `
  shared\config.py `
  shared\schemas.py `
  shared\available_models.py
```

## Example Requests

Prepare a repository:

```powershell
Invoke-RestMethod `
  -Uri "http://127.0.0.1:8004/prepare-repo" `
  -Method Post `
  -ContentType "application/json" `
  -Body '{"repo_url":"https://github.com/owner/project.git"}'
```

Start a workflow from the dashboard API:

```powershell
Invoke-RestMethod `
  -Uri "http://127.0.0.1:8010/api/workflow/start" `
  -Method Post `
  -ContentType "application/json" `
  -Body '{"issue_key":"PROJ-123","base_branch":"main","repo_url":"https://github.com/owner/project.git","open_pr":true}'
```

Create a branch directly through the Repo Agent:

```powershell
Invoke-RestMethod `
  -Uri "http://127.0.0.1:8004/create-branch" `
  -Method Post `
  -ContentType "application/json" `
  -Body '{"repo_url":"https://github.com/owner/project.git","issue_key":"PROJ-123","title":"Add user API","base_branch":"main"}'
```

## Notes and Known Issues

- This is a local prototype intended for development and experimentation.
- The dashboard expects the orchestrator on port `8010`.
- `run_all.ps1` starts all services and sets `PYTHONPATH` for the moved `agents/` and `shared/` modules.
- GitHub mode applies file changes through the GitHub Contents API. Local clones are used for context and knowledge, but file commits are created remotely.
- Local-folder mode applies changes directly to the selected local Git checkout and disables pull request creation.

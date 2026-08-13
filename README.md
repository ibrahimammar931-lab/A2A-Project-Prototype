# A2A Agent Workflow Project

This repository contains a FastAPI-based multi-agent workflow for taking a Jira issue, understanding the target repo, planning the work, generating code, reviewing it, and applying the change to a GitHub branch. It also includes an Angular dashboard for monitoring and manually controlling the workflow.

## What is in this project

The current codebase includes these services:

- Jira Agent: reads Jira issues and normalizes them into shared schemas
- Repo Agent: prepares local workspace clones and performs GitHub operations
- Knowledge Agent: builds and updates repository knowledge summaries
- Planner Agent: creates an implementation plan from a ticket and repo context
- Developer Agent: generates and revises code changes
- Reviewer Agent: reviews diffs and flags blocking issues
- Model Selector Agent: checks candidate models and picks best model per role
- Orchestrator Agent: coordinates the full workflow and exposes the dashboard APIs

## Default service ports

```text
Developer Agent      -> developer_agent.py      -> 8000
Jira Agent           -> jira_agent.py           -> 8001
Reviewer Agent       -> reviewer_agent.py       -> 8002
Orchestrator Agent    -> orchestrator_agent.py    -> 8003
Repo Agent           -> repo_agent.py           -> 8004
Knowledge Agent      -> knowledge_agent.py      -> 8005
Planner Agent        -> planner_agent.py        -> 8006
Model Selector Agent -> model_selector_agent.py -> 8007
```

These service URLs are configurable through environment variables in [config.py](config.py), and the defaults are defined there.

## Project structure

```text
A2A/
├── .env.example
├── .env
├── README.md
├── SETUP.md
├── available_models.py
├── config.py
├── developer_agent.py
├── jira_agent.py
├── knowledge_agent.py
├── model_selection.json
├── model_selector_agent.py
├── orchestrator_agent.py
├── planner_agent.py
├── repo_agent.py
├── requirements.txt
├── reviewer_agent.py
├── schemas.py
├── workspaces/
│   ├── knowledge/
│   └── ...
├── dashboard/
│   ├── angular.json
│   ├── package.json
│   └── src/
├── A2A_Project_Documentation.md
└── A2A_Workflow_Plan.pdf
```

## Quick start

1. Create a virtual environment.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

On macOS/Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

2. Install Python dependencies.

```bash
pip install -r requirements.txt
```

3. Copy the example environment file and fill in your own values.

```bash
copy .env.example .env
```

The example file contains the current required keys and optional overrides used by the code. The important values are:

```env
GROQ_API_KEY=your_groq_api_key_here
GROQ_MODEL=llama-3.3-70b-versatile
GROQ_REVIEWER_MODEL=llama-3.3-70b-versatile
GROQ_PLANNER_MODEL=llama-3.3-70b-versatile
LOG_LEVEL=INFO

ANTHROPIC_API_KEY=your_anthropic_api_key_here
OPENAI_API_KEY=your_openai_api_key_here

JIRA_BASE_URL=https://your-domain.atlassian.net
JIRA_EMAIL=your_email@example.com
JIRA_API_TOKEN=your_jira_api_token_here

DEVELOPER_SERVICE_URL=http://127.0.0.1:8000
JIRA_SERVICE_URL=http://127.0.0.1:8001
REVIEWER_SERVICE_URL=http://127.0.0.1:8002
REPO_SERVICE_URL=http://127.0.0.1:8004
KNOWLEDGE_SERVICE_URL=http://127.0.0.1:8005
PLANNER_SERVICE_URL=http://127.0.0.1:8006
MODEL_SELECTOR_SERVICE_URL=http://127.0.0.1:8007

GITHUB_REPO_URL=https://github.com/owner/project.git
GITHUB_TOKEN=your_github_token_here
REPO_WORKSPACE_ROOT=workspaces
LOCAL_KNOWLEDGE_ROOT=workspaces/knowledge
```

## Run the services

Open separate terminals and start each service.

Terminal 1:

```bash
uvicorn jira_agent:app --port 8001 --reload
```

Terminal 2:

```bash
uvicorn reviewer_agent:app --port 8002 --reload
```

Terminal 3:

```bash
uvicorn developer_agent:app --port 8000 --reload
```

Terminal 4:

```bash
uvicorn repo_agent:app --port 8004 --reload
```

Terminal 5:

```bash
uvicorn knowledge_agent:app --port 8005 --reload
```

Terminal 6:

```bash
uvicorn planner_agent:app --port 8006 --reload
```

Terminal 7:

```bash
uvicorn model_selector_agent:app --port 8007 --reload
```

Terminal 8:

```bash
uvicorn orchestrator_agent:app --port 8003 --reload
```

## FastAPI docs

Once the services are running, the Swagger UI is available here:

```text
Developer Agent:      http://127.0.0.1:8000/docs
Jira Agent:           http://127.0.0.1:8001/docs
Reviewer Agent:       http://127.0.0.1:8002/docs
Orchestrator Agent:    http://127.0.0.1:8003/docs
Repo Agent:           http://127.0.0.1:8004/docs
Knowledge Agent:      http://127.0.0.1:8005/docs
Planner Agent:        http://127.0.0.1:8006/docs
Model Selector Agent: http://127.0.0.1:8007/docs
```

## Dashboard

The Angular dashboard lives in the [dashboard](dashboard) folder. It is built for visualizing the workflow and manually starting the orchestrator pipeline.

From the project root:

```bash
cd dashboard
npm install
npm start
```

Then open:

```text
http://localhost:4200
```

The dashboard talks to the orchestrator through endpoints under `/api/workflow/*`.

## Workflow model

The current orchestrator flow is driven by the dashboard and agent APIs, not by an old `/work-on-ticket` endpoint. The active orchestration endpoints include:

- `GET /api/workflow/state`
- `POST /api/workflow/start`
- `POST /api/workflow/run-next-agent`
- `POST /api/workflow/set-mode`
- `POST /api/workflow/model-selection`
- `POST /api/workflow/set-auto-model-selection`

The workflow normally performs these steps:

1. Fetch Jira ticket
2. Prepare repo workspace
3. Ensure knowledge exists for the repo
4. Plan the work
5. Create or select a branch
6. Read likely files
7. Generate code
8. Review code
9. Improve code if needed
10. Apply changes and update repo knowledge
11. Open a PR if configured

## Model selection

The project can dynamically choose a model for each role using the Model Selector Agent and the `AVAILABLE_MODELS` registry in [available_models.py](available_models.py). The selector is configured through [model_selection.json](model_selection.json) and any per-agent override is also exposed via the dashboard.

## Notes

- The repo uses `.env` values loaded by [config.py](config.py).
- JIRA credential checks and model-provider checks are enforced at runtime.
- GitHub operations require a valid `GITHUB_TOKEN` and a target repo URL.
- The repo workspace defaults to `workspaces/` and the knowledge cache defaults to `workspaces/knowledge`.

## For local development

If you only want to validate the Python files without running the full workflow, use:

```powershell
.\.venv\Scripts\python.exe -m py_compile `
  config.py `
  schemas.py `
  jira_agent.py `
  developer_agent.py `
  reviewer_agent.py `
  repo_agent.py `
  knowledge_agent.py `
  planner_agent.py `
  model_selector_agent.py `
  orchestrator_agent.py
```

This project is a prototype and is designed to be run locally while connected to Jira, Groq/OpenAI-compatible providers, and GitHub credentials.


```powershell
Invoke-RestMethod `
  -Uri "http://127.0.0.1:8004/prepare-repo" `
  -Method Post `
  -ContentType "application/json" `
  -Body '{}'
```

Create a branch:

```powershell
Invoke-RestMethod `
  -Uri "http://127.0.0.1:8004/create-branch" `
  -Method Post `
  -ContentType "application/json" `
  -Body '{"repo_url":"https://github.com/owner/project.git","issue_key":"PROJ-123","title":"Add user API","base_branch":"main"}'
```

Open a pull request after `apply-changes`:

```powershell
Invoke-RestMethod `
  -Uri "http://127.0.0.1:8004/open-pr" `
  -Method Post `
  -ContentType "application/json" `
  -Body '{"repo_url":"https://github.com/owner/project.git","issue_key":"PROJ-123","title":"Add user API","summary":"Adds the user API implementation and tests.","base_branch":"main"}'
```

## Example Response

```json
{
  "ticket": {
    "key": "PROJ-123",
    "summary": "Create a Flask CRUD API for users"
  },
  "original_code": {
    "code": "from flask import Flask ...",
    "explanation": "Initial implementation."
  },
  "review_feedback": {
    "approved": false,
    "issues": ["Missing input validation"],
    "suggestions": ["Add validation"],
    "security_notes": [],
    "quality_notes": []
  },
  "improved_code": {
    "code": "from flask import Flask ...",
    "explanation": "Improved implementation."
  },
  "repo": {
    "repo_id": "owner-project",
    "path": "C:\\Users\\ibrah\\Desktop\\A2A\\workspaces\\owner-project",
    "current_branch": "main",
    "remote_url": "https://github.com/owner/project.git",
    "status": "updated"
  },
  "branch": {
    "repo_id": "owner-project",
    "branch": "agent/PROJ-123-create-a-flask-crud-api-for-users",
    "base_branch": "main"
  },
  "repo_files": [
    {
      "path": "app/main.py",
      "content": "..."
    }
  ],
  "messages": []
}
```

## Data Models

Important shared models live in `schemas.py`:

```text
GenerateRequest
GenerateResponse
JiraTicket
AgentTaskRequest
DeveloperOutput
ReviewFeedback
AgentMessage
```

## Responsibility Boundary

The service split is intentional:

```text
Jira Agent         -> Jira API access and Jira field normalization
Developer Agent    -> code generation and code improvement only
Reviewer Agent     -> code review only
Orchestrator Agent -> workflow coordination only
```

This keeps the Developer Agent from owning external service calls or workflow state,
which makes the project easier to extend with repo operations, planner agents,
retry logic, or parallel review later.

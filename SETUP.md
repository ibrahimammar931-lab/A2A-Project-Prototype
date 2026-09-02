# Setup Guide

This guide is for the current version of the repository and reflects the services and configuration supported by the code in [shared/config.py](shared/config.py), [shared/available_models.py](shared/available_models.py), and the FastAPI entry points in [agents/](agents/).

## Requirements

Install the following before you run the project:

- Python 3.11+
- Git
- A valid Groq or other configured provider API key
- A Jira site URL, Jira email, and Jira API token
- A GitHub repository URL and token if you want repo automation enabled

## 1. Create the environment

From the project root:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

On macOS/Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Then install dependencies:

```bash
pip install -r requirements.txt
```

## 2. Configure environment variables

Copy the sample file:

```bash
copy .env.example .env
```

Then edit `.env` with your real values. Minimum working configuration for the default Groq-based setup looks like this:

```env
GROQ_API_KEY=your_groq_api_key_here
GROQ_MODEL=llama-3.3-70b-versatile
GROQ_REVIEWER_MODEL=llama-3.3-70b-versatile
GROQ_PLANNER_MODEL=llama-3.3-70b-versatile
LOG_LEVEL=INFO

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

Optional provider keys like `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, and other model keys can be added if you want those models to appear as available choices in the dashboard and model selector.

## 3. Start the services

The agent modules live in `agents/`, while shared modules live in `shared/`. Set `PYTHONPATH` first so the moved modules can import `config`, `schemas`, and `available_models`:

```powershell
$env:PYTHONPATH = "$PWD\agents;$PWD\shared"
```

Open one terminal per service and run these commands from the project root.

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

## 4. Check the docs

FastAPI Swagger UI is available for each service:

```text
http://127.0.0.1:8000/docs
http://127.0.0.1:8001/docs
http://127.0.0.1:8002/docs
http://127.0.0.1:8004/docs
http://127.0.0.1:8005/docs
http://127.0.0.1:8006/docs
http://127.0.0.1:8007/docs
http://127.0.0.1:8010/docs
```

## 5. Start the dashboard

The dashboard is not required to run the backend services, but it is the easiest way to control the workflow.

```bash
cd dashboard
npm install
npm start
```

Then open:

```text
http://localhost:4200
```

The dashboard talks to the orchestrator at routes under `/api/workflow/*`.

## 6. Validate the setup

A quick Python syntax check is useful before launching the full workflow:

```powershell
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

If that passes, the backend code is structurally valid and ready to start.

## 7. Common issues

- Missing model API key: the app raises an error if no configured model credentials are present.
- Missing Jira config: `JIRA_BASE_URL`, `JIRA_EMAIL`, and `JIRA_API_TOKEN` are required to fetch tickets.
- Missing GitHub repo details: repo operations need `GITHUB_REPO_URL` and `GITHUB_TOKEN`.
- Dashboard not loading: ensure the orchestrator is running on port 8010 and the Angular app is built or served on port 4200.

## 8. Recommended first run

Run the services in this order:

1. Jira Agent
2. Repo Agent
3. Knowledge Agent
4. Planner Agent
5. Developer Agent
6. Reviewer Agent
7. Model Selector Agent
8. Orchestrator Agent

Then open the dashboard and start a workflow from the orchestrator panel.


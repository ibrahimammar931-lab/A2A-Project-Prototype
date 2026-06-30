# Setup Guide

This guide covers local installation, required environment variables, and how to run
the services.

## Prerequisites

Install:

```text
Python 3.11+
Git
```

You also need:

```text
Groq API key
Jira site URL
Jira account email
Jira API token
```

## Install Dependencies

From the project directory:

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

## Environment Variables

Edit `.env`:

```env
GROQ_API_KEY=your_groq_api_key_here
GROQ_MODEL=llama-3.3-70b-versatile
GROQ_REVIEWER_MODEL=llama-3.3-70b-versatile
LOG_LEVEL=INFO

JIRA_BASE_URL=https://your-domain.atlassian.net
JIRA_EMAIL=your_email@example.com
JIRA_API_TOKEN=your_jira_api_token_here

DEVELOPER_SERVICE_URL=http://127.0.0.1:8000
JIRA_SERVICE_URL=http://127.0.0.1:8001
REVIEWER_SERVICE_URL=http://127.0.0.1:8002
```

## Run Services

Open four terminals.

Terminal 1:

```powershell
.\.venv\Scripts\activate
uvicorn developer_agent:app --port 8000 --reload
```

Terminal 2:

```powershell
.\.venv\Scripts\activate
uvicorn jira_agent:app --port 8001 --reload
```

Terminal 3:

```powershell
.\.venv\Scripts\activate
uvicorn reviewer_agent:app --port 8002 --reload
```

Terminal 4:

```powershell
.\.venv\Scripts\activate
uvicorn orchestrator_agent:app --port 8003 --reload
```

## API Docs

FastAPI docs are available at:

```text
Developer Agent:    http://127.0.0.1:8000/docs
Jira Agent:         http://127.0.0.1:8001/docs
Reviewer Agent:     http://127.0.0.1:8002/docs
Orchestrator Agent: http://127.0.0.1:8003/docs
```

## Test The Workflow

Call the Orchestrator:

```powershell
Invoke-RestMethod `
  -Uri "http://127.0.0.1:8003/work-on-ticket" `
  -Method Post `
  -ContentType "application/json" `
  -Body '{"issue_key":"PROJ-123"}'
```

Replace `PROJ-123` with a real Jira issue key.

## Validate Imports

Use the project virtualenv:

```powershell
.\.venv\Scripts\python.exe -m py_compile `
  developer_agent.py `
  jira_agent.py `
  reviewer_agent.py `
  orchestrator_agent.py `
  config.py `
  schemas.py
```

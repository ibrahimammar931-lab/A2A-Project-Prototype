$services = @(
    @{Name="jira_agent"; Port=8001},
    @{Name="reviewer_agent"; Port=8002},
    @{Name="developer_agent"; Port=8000},
    @{Name="repo_agent"; Port=8004},
    @{Name="knowledge_agent"; Port=8005},
    @{Name="planner_agent"; Port=8006},
    @{Name="model_selector_agent"; Port=8007},
    @{Name="orchestrator_agent"; Port=8010}
)

foreach ($s in $services) {
    Start-Process powershell -ArgumentList "-NoExit", "-Command", `
        ".\.venv\Scripts\Activate.ps1; uvicorn $($s.Name):app --port $($s.Port) --reload"
}
$services = @(
    @{Module="agents.jira_agent"; Port=8001},
    @{Module="agents.reviewer_agent"; Port=8002},
    @{Module="agents.developer_agent"; Port=8000},
    @{Module="agents.repo_agent"; Port=8004},
    @{Module="agents.knowledge_agent"; Port=8005},
    @{Module="agents.planner_agent"; Port=8006},
    @{Module="agents.model_selector_agent"; Port=8007},
    @{Module="agents.orchestrator_agent"; Port=8010}
)

$root = $PWD.Path
$env:PYTHONPATH = "$root\agents;$root\shared"

foreach ($s in $services) {
    Start-Process powershell -ArgumentList "-NoExit", "-Command", `
        "`$env:PYTHONPATH = '$env:PYTHONPATH'; .\.venv\Scripts\Activate.ps1; uvicorn $($s.Module):app --port $($s.Port) --reload" `
        -WorkingDirectory $root
}

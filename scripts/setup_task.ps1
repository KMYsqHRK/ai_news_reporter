# AI News Reporter - Windows Task Scheduler Setup Script
# Reads schedule settings from config/config.yaml (the Windows counterpart of setup_cron.sh).
# Usage: powershell -ExecutionPolicy Bypass -File scripts\setup_task.ps1 [-Force]

param(
    [switch]$Force  # Register without asking for confirmation
)

$ErrorActionPreference = "Stop"

$ProjectDir = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $ProjectDir ".venv\Scripts\python.exe"
$AiNews = Join-Path $ProjectDir ".venv\Scripts\ai-news.exe"
$RunScript = Join-Path $PSScriptRoot "run_report.ps1"
$ConfigFile = Join-Path $ProjectDir "config\config.yaml"
$EnvFile = Join-Path $ProjectDir "config\.env"
$LogFile = Join-Path $ProjectDir "task.log"
$TaskName = "AI News Reporter"

Write-Host "==================================="
Write-Host "AI News Reporter - Task Scheduler Setup"
Write-Host "==================================="
Write-Host ""

if (-not (Test-Path $AiNews)) {
    Write-Host "Setting up virtual environment..."
    Push-Location $ProjectDir
    uv sync
    Pop-Location
}

if (-not (Test-Path $EnvFile)) {
    Write-Host "ERROR: config\.env file not found!"
    Write-Host "Please copy config\.env.example to config\.env and fill it in."
    exit 1
}

if (-not (Test-Path $ConfigFile)) {
    Write-Host "ERROR: config\config.yaml not found!"
    Write-Host "Please copy config\config.example.yaml to config\config.yaml and customize it."
    exit 1
}

Write-Host "Validating configuration..."
Push-Location $ProjectDir
$env:PYTHONIOENCODING = "utf-8"
& $AiNews validate
if ($LASTEXITCODE -ne 0) { Pop-Location; exit 1 }

# Read the schedule with the app's own config loader
$schedule = & $Python -c "from ai_news_reporter.core.config import AppConfig; s = AppConfig().schedule; print(s.type, s.day_of_week, s.time)"
Pop-Location
$type, $day, $time = $schedule.Trim().Split(" ")
Write-Host ""

if ($type -eq "daily") {
    $trigger = New-ScheduledTaskTrigger -Daily -At $time
    $desc = "Daily at $time"
} else {
    $dayName = (Get-Culture).TextInfo.ToTitleCase($day.ToLower())
    $trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek $dayName -At $time
    $desc = "Weekly on $dayName at $time"
}

$action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$RunScript`"" `
    -WorkingDirectory $ProjectDir
# Run a missed schedule (PC off or asleep) as soon as possible; runs as the current user while
# logged on, since the Claude Code login lives in the user profile
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 1)

Write-Host "==================================="
Write-Host "Schedule from config\config.yaml"
Write-Host "==================================="
Write-Host "Task: $TaskName"
Write-Host "Schedule: $desc (local time of this PC)"
Write-Host "Runs: $RunScript"
Write-Host ""

if (-not $Force) {
    $confirm = Read-Host "Register this task? (y/n)"
    if ($confirm -ne "y" -and $confirm -ne "Y") {
        Write-Host "Task not registered."
        exit 0
    }
}

# Replaces an existing task with the same name
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings `
    -Description "AI News Reporter ($desc)" -Force | Out-Null

Write-Host ""
Write-Host "Task registered successfully!"
Write-Host ""
Write-Host "To run now:    Start-ScheduledTask -TaskName '$TaskName'"
Write-Host "To verify:     Get-ScheduledTask -TaskName '$TaskName' | Get-ScheduledTaskInfo"
Write-Host "To view logs:  Get-Content '$LogFile' -Tail 30"
Write-Host "To remove:     Unregister-ScheduledTask -TaskName '$TaskName'"

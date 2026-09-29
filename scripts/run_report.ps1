# AI News Reporter - run one report and append the output to task.log
# Used by the Windows Task Scheduler task created by setup_task.ps1.

$ProjectDir = Split-Path -Parent $PSScriptRoot
$AiNews = Join-Path $ProjectDir ".venv\Scripts\ai-news.exe"
$LogFile = Join-Path $ProjectDir "task.log"

# config/config.yaml and config/.env are resolved relative to the project directory
Set-Location $ProjectDir
# Rich prints Unicode; without this, redirected output fails on non-UTF-8 consoles (e.g. cp932)
$env:PYTHONIOENCODING = "utf-8"
# ...and PowerShell must decode that output as UTF-8 too, or the log is garbled
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

Add-Content -Path $LogFile -Encoding UTF8 -Value "===== $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') ====="
& $AiNews run 2>&1 | ForEach-Object { "$_" } | Add-Content -Path $LogFile -Encoding UTF8
$code = $LASTEXITCODE
Add-Content -Path $LogFile -Encoding UTF8 -Value "exit code: $code`n"
exit $code

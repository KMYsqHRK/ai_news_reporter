# AI News Reporter

Automated AI news collection and reporting system. Collects news from web scraping and Tavily search API, summarizes with LLM (Claude API, Claude account via Claude Code, or OpenAI), and delivers weekly reports via email, Slack, or file output.

## Features

- **Multi-source collection**: Tavily search API + configurable web scraping
- **Switchable LLM**: Claude API (default), Claude account via Claude Code, or OpenAI for summarization
- **Multiple delivery methods**: Email (SMTP), Slack webhook, File (Markdown/HTML/JSON)
- **Scheduled reports**: Cron-style scheduling with APScheduler
- **Deduplication**: Removes duplicate articles by URL and title similarity
- **Configurable**: YAML config for keywords, sites, and delivery options

## Installation

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```bash
# Clone and enter directory
cd ai_news_reporter

# Install dependencies
uv sync

# Copy configuration files
cp config/.env.example config/.env
cp config/config.example.yaml config/config.yaml
```

## Quick Start (Minimal Setup)

For a minimal setup with file output only, you need just 2 API keys:

### 1. Get Tavily API Key (News Search)

1. Go to [tavily.com](https://tavily.com/)
2. Sign up and get your API key
3. Add to `config/.env`:
   ```bash
   TAVILY_API_KEY=tvly-xxxxx
   ```

### 2. Choose an LLM Provider

**Option A: OpenAI**
1. Go to [platform.openai.com/api-keys](https://platform.openai.com/api-keys)
2. Create an API key
3. Add to `config/.env`:
   ```bash
   OPENAI_API_KEY=sk-xxxxx
   ```
4. Set provider in `config/config.yaml`:
   ```yaml
   llm:
     provider: "openai"
   ```

**Option B: Claude (Anthropic)**
1. Go to [console.anthropic.com](https://console.anthropic.com/)
2. Create an API key
3. Add to `config/.env`:
   ```bash
   ANTHROPIC_API_KEY=sk-ant-api03-xxxxx
   ```
4. Set provider in `config/config.yaml` (this is the default):
   ```yaml
   llm:
     provider: "claude"
   ```

**Option C: Claude account via Claude Code (no API key)**

Uses the Claude account (Pro/Max/Team/Enterprise) that [Claude Code](https://docs.claude.com/en/docs/claude-code) is logged in with, so usage counts against that account instead of API credits.
1. Install Claude Code and log in once by running `claude`
2. Find the executable path with `which claude`
3. Set provider in `config/config.yaml`:
   ```yaml
   llm:
     provider: "claude_code"
     model: "sonnet"                    # or "opus"
     cli_path: "/path/to/bin/claude"    # absolute path, since cron does not load your shell PATH
   ```

`ANTHROPIC_API_KEY` is ignored with this provider. The machine running the scheduled job must stay logged in to Claude Code.

### 3. Run Your First Report

```bash
# Validate configuration
uv run ai-news validate

# Generate report
uv run ai-news run
```

Reports are saved to `./reports/` folder in Markdown, HTML, and JSON formats.

## Optional: Email Delivery Setup

To receive reports via email (Gmail example):

### 1. Enable Gmail App Password

1. Enable 2-Factor Authentication on your Google account
2. Go to [Google App Passwords](https://myaccount.google.com/apppasswords)
3. Select app: "Mail", Select device: "Other" (enter "AI News Reporter")
4. Click "Generate" and copy the 16-character password

### 2. Configure config/.env

```bash
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your-email@gmail.com
SMTP_PASSWORD=xxxx-xxxx-xxxx-xxxx  # App password, NOT your Gmail password
```

### 3. Enable in config/config.yaml

```yaml
delivery:
  email:
    enabled: true
    recipients:
      - "recipient@example.com"
    subject_prefix: "[AI News Weekly]"
```

## Optional: Slack Bot Delivery Setup

To receive reports via Slack DM from a bot:

### 1. Create Slack App

1. Go to [api.slack.com/apps](https://api.slack.com/apps)
2. Click **Create New App** > **From scratch**
3. Name: "AI News Reporter", select your workspace

### 2. Configure Bot Permissions

1. In the left sidebar, click **OAuth & Permissions**
2. Under **Bot Token Scopes**, add these scopes:
   - `chat:write` - Send messages as the bot
   - `im:write` - Send DMs to users
3. Click **Install to Workspace** at the top
4. Copy the **Bot User OAuth Token** (starts with `xoxb-`)

### 3. Find Your Slack User ID

1. Open Slack and click on your profile picture
2. Click **Profile**
3. Click the **...** (more) button
4. Click **Copy member ID** (e.g., `U0123456789`)

### 4. Configure config/.env

```bash
SLACK_BOT_TOKEN=xoxb-xxxxx-xxxxx-xxxxx
```

### 5. Enable in config/config.yaml

```yaml
delivery:
  slack:
    enabled: true
    user_ids:
      - "U0123456789"    # Your Slack user ID
```

## Configuration Reference

### Environment Variables (config/.env)

| Variable | Required | Description |
|----------|----------|-------------|
| `TAVILY_API_KEY` | Yes | Tavily API key for news search |
| `ANTHROPIC_API_KEY` | If using `claude` provider | Anthropic API key |
| `OPENAI_API_KEY` | If using OpenAI | OpenAI API key |
| `SMTP_HOST` | If using email | SMTP server (e.g., `smtp.gmail.com`) |
| `SMTP_PORT` | If using email | SMTP port (e.g., `587`) |
| `SMTP_USER` | If using email | SMTP username/email |
| `SMTP_PASSWORD` | If using email | SMTP password or app password |
| `SLACK_BOT_TOKEN` | If using Slack | Slack Bot OAuth token (xoxb-...) |

### Application Config (config/config.yaml)

```yaml
# Keywords to search
keywords:
  - "artificial intelligence"
  - "large language models"

# Sites to scrape
sites:
  - name: "TechCrunch AI"
    url: "https://techcrunch.com/category/artificial-intelligence/"
    enabled: true
    selectors:
      article: "article"
      title: "h2 a"

# Search settings
search:
  enabled: true
  time_range: "week"
  max_results_per_keyword: 10

# Schedule settings
schedule:
  enabled: true
  type: "weekly"
  day_of_week: "monday"
  time: "09:00"
  timezone: "Asia/Tokyo"

# Delivery methods
delivery:
  file:
    enabled: true
    output_dir: "./reports"
    formats: ["markdown", "html", "json"]
  email:
    enabled: false
    recipients: ["user@example.com"]
  slack:
    enabled: false
```

## Usage

### Run Report Manually

```bash
uv run ai-news run
```

### Validate Configuration

```bash
uv run ai-news validate
```

### Custom Config Path

```bash
uv run ai-news run --config /path/to/config.yaml
```

## Automated Weekly Reports (Cron Setup)

To receive reports automatically every week without manual commands:

### Setup Steps

1. Edit `config/config.yaml` - set your schedule:
   ```yaml
   schedule:
     enabled: true
     type: "weekly"           # daily or weekly
     day_of_week: "monday"    # for weekly
     time: "09:00"            # 24-hour format
     timezone: "Asia/Tokyo"
   ```

2. Run the setup script:
   ```bash
   ./scripts/setup_cron.sh
   ```

The script reads schedule settings from `config/config.yaml` and sets up cron automatically.

### Manual Setup

If you prefer to set up cron manually:

```bash
# Open crontab editor
crontab -e

# Add this line for weekly Monday 9:00 AM reports:
0 9 * * 1 cd /path/to/ai_news_reporter && .venv/bin/ai-news run >> cron.log 2>&1
```

Cron schedule format: `minute hour day-of-month month day-of-week`
- `0 9 * * 1` = Monday 9:00 AM
- `0 9 * * 5` = Friday 9:00 AM
- `0 9 * * *` = Daily 9:00 AM

### Check Cron Status

```bash
# View current cron jobs
crontab -l

# View logs
tail -f cron.log
```

### Remove Cron Job

```bash
crontab -e
# Delete the ai-news line and save
```

## Automated Weekly Reports (Windows Task Scheduler)

On Windows, register a Task Scheduler task that follows `schedule:` in `config/config.yaml`:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup_task.ps1
```

The task runs `scripts\run_report.ps1` as the current user while logged on (the Claude Code login
lives in the user profile), appends output to `task.log`, and catches up on a missed run when the
PC was off. The schedule uses the PC's local time.

```powershell
Start-ScheduledTask -TaskName "AI News Reporter"       # Run now
Get-Content task.log -Tail 30                           # View logs
Unregister-ScheduledTask -TaskName "AI News Reporter"  # Remove
```

## Project Structure

```
ai_news_reporter/
├── src/ai_news_reporter/
│   ├── main.py           # CLI entry point
│   ├── core/             # Config and exceptions
│   ├── collectors/       # Tavily + web scraper
│   ├── llm/              # Claude API + Claude Code + OpenAI + factory
│   ├── processors/       # Summarizer + deduplicator
│   ├── delivery/         # File, email, Slack
│   ├── scheduler/        # APScheduler cron
│   └── models/           # Article, Report
├── config/
│   ├── config.yaml       # User config (git-ignored)
│   ├── config.example.yaml
│   ├── .env              # API keys (git-ignored)
│   └── .env.example
├── scripts/
│   ├── setup_cron.sh     # Cron setup script (Linux/macOS)
│   ├── setup_task.ps1    # Task Scheduler setup script (Windows)
│   └── run_report.ps1    # Report runner used by the Windows task
└── reports/              # Generated reports
```

## License

MIT

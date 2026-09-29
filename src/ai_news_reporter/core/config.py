"""Configuration management using Pydantic Settings and YAML."""

from pathlib import Path
from typing import Any

import yaml
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from .exceptions import ConfigurationError


class Settings(BaseSettings):
    """Environment settings loaded from .env file."""

    model_config = SettingsConfigDict(
        env_file="config/.env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # LLM API Keys
    anthropic_api_key: str = Field(default="", alias="ANTHROPIC_API_KEY")
    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")

    # Search API
    tavily_api_key: str = Field(default="", alias="TAVILY_API_KEY")

    # GitHub (optional: raises the API rate limit, or lists your stars without github.username)
    github_token: str = Field(default="", alias="GITHUB_TOKEN")

    # Email (SMTP)
    smtp_host: str = Field(default="smtp.gmail.com", alias="SMTP_HOST")
    smtp_port: int = Field(default=587, alias="SMTP_PORT")
    smtp_user: str = Field(default="", alias="SMTP_USER")
    smtp_password: str = Field(default="", alias="SMTP_PASSWORD")

    # Slack Bot
    slack_bot_token: str = Field(default="", alias="SLACK_BOT_TOKEN")

    # Optional settings
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    config_path: str = Field(default="config/config.yaml", alias="CONFIG_PATH")


class SiteConfig:
    """Configuration for a single site to scrape."""

    def __init__(self, data: dict[str, Any]):
        self.name: str = data.get("name", "Unknown")
        self.url: str = data.get("url", "")
        self.enabled: bool = data.get("enabled", True)
        self.selectors: dict[str, str] = data.get("selectors", {})


class SearchConfig:
    """Search configuration."""

    def __init__(self, data: dict[str, Any]):
        self.enabled: bool = data.get("enabled", True)
        # tavily (needs TAVILY_API_KEY) or claude_code (WebSearch via the logged-in Claude account)
        self.provider: str = data.get("provider", "tavily")
        self.time_range: str = data.get("time_range", "week")
        self.max_results_per_keyword: int = data.get("max_results_per_keyword", 10)
        self.include_domains: list[str] = data.get("include_domains", [])
        self.exclude_domains: list[str] = data.get("exclude_domains", [])


class GitHubConfig:
    """Starred repository updates configuration."""

    def __init__(self, data: dict[str, Any]):
        self.enabled: bool = data.get("enabled", False)
        self.username: str = data.get("username", "")
        self.time_range: str = data.get("time_range", "week")
        self.max_items: int = data.get("max_items", 30)
        self.include_commits: bool = data.get("include_commits", True)
        self.exclude: list[str] = data.get("exclude", [])


class ScheduleConfig:
    """Schedule configuration."""

    def __init__(self, data: dict[str, Any]):
        self.enabled: bool = data.get("enabled", True)
        self.type: str = data.get("type", "weekly")
        self.day_of_week: str = data.get("day_of_week", "monday")
        self.time: str = data.get("time", "09:00")
        self.timezone: str = data.get("timezone", "UTC")


class DeliveryConfig:
    """Delivery configuration."""

    def __init__(self, data: dict[str, Any]):
        self.email = data.get("email", {})
        self.slack = data.get("slack", {})
        self.file = data.get("file", {})

    @property
    def email_enabled(self) -> bool:
        return self.email.get("enabled", False)

    @property
    def email_recipients(self) -> list[str]:
        return self.email.get("recipients", [])

    @property
    def email_subject_prefix(self) -> str:
        return self.email.get("subject_prefix", "[AI News Weekly]")

    @property
    def slack_enabled(self) -> bool:
        return self.slack.get("enabled", False)

    @property
    def slack_user_ids(self) -> list[str]:
        return self.slack.get("user_ids", [])

    @property
    def file_enabled(self) -> bool:
        return self.file.get("enabled", True)

    @property
    def file_output_dir(self) -> str:
        return self.file.get("output_dir", "./reports")

    @property
    def file_formats(self) -> list[str]:
        return self.file.get("formats", ["markdown"])


class LLMConfig:
    """LLM configuration."""

    def __init__(self, data: dict[str, Any]):
        self.provider: str = data.get("provider", "claude")
        self.model: str = data.get("model", "claude-sonnet-4-20250514")
        self.max_tokens: int = data.get("max_tokens", 4096)
        self.temperature: float = data.get("temperature", 0.3)
        self.cli_path: str = data.get("cli_path", "claude")
        # summary_prompt is deprecated - use report.focus instead
        # Return None to use the built-in DEFAULT_SUMMARY_PROMPT
        self.summary_prompt: str | None = data.get("summary_prompt")


class ReportConfig:
    """Report configuration."""

    def __init__(self, data: dict[str, Any]):
        self.title: str = data.get("title", "AI News Weekly Report")
        self.max_articles: int = data.get("max_articles", 50)
        self.deduplicate: bool = data.get("deduplicate", True)
        self.include_sources: bool = data.get("include_sources", True)
        self.highlight_count: int = data.get("highlight_count", 10)
        self.focus: str = data.get("focus", "")
        # Language of all generated text (summaries, search result descriptions, repo updates)
        self.language: str = data.get("language", "English")


class AppConfig:
    """Application configuration loaded from YAML file."""

    def __init__(self, config_path: Path | str = Path("config/config.yaml")):
        self._config_path = Path(config_path)
        self._config: dict[str, Any] = {}
        self._load()

    def _load(self) -> None:
        """Load configuration from YAML file."""
        if not self._config_path.exists():
            raise ConfigurationError(f"Config file not found: {self._config_path}")

        with open(self._config_path) as f:
            self._config = yaml.safe_load(f) or {}

    def reload(self) -> None:
        """Reload configuration from file."""
        self._load()

    @property
    def keywords(self) -> list[str]:
        """Get search keywords."""
        return self._config.get("keywords", [])

    @property
    def sites(self) -> list[SiteConfig]:
        """Get site configurations."""
        return [SiteConfig(s) for s in self._config.get("sites", [])]

    @property
    def search(self) -> SearchConfig:
        """Get search configuration."""
        return SearchConfig(self._config.get("search", {}))

    @property
    def github(self) -> GitHubConfig:
        """Get starred repository updates configuration."""
        return GitHubConfig(self._config.get("github", {}))

    @property
    def schedule(self) -> ScheduleConfig:
        """Get schedule configuration."""
        return ScheduleConfig(self._config.get("schedule", {}))

    @property
    def delivery(self) -> DeliveryConfig:
        """Get delivery configuration."""
        return DeliveryConfig(self._config.get("delivery", {}))

    @property
    def llm(self) -> LLMConfig:
        """Get LLM configuration."""
        return LLMConfig(self._config.get("llm", {}))

    @property
    def report(self) -> ReportConfig:
        """Get report configuration."""
        return ReportConfig(self._config.get("report", {}))

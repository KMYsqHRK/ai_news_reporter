"""Data collectors for AI News Reporter."""

from .base import BaseCollector
from .claude_web_search import ClaudeWebSearchCollector
from .github_stars import GitHubStarsCollector
from .scraper import WebScraper
from .tavily_search import TavilyCollector

__all__ = [
    "BaseCollector",
    "ClaudeWebSearchCollector",
    "GitHubStarsCollector",
    "TavilyCollector",
    "WebScraper",
]

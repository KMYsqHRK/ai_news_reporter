"""Abstract base class for LLM providers."""

from abc import ABC, abstractmethod

from ..models.article import Article

REPO_CHANGES_PROMPT = """You are briefing a developer on everything that changed this period \
in the GitHub repositories they starred. Below is the full change log (releases and commits) \
of each repository.

For EACH repository, in the given order, write exactly:

**[owner/repo (counts)](url)**

- 2-6 bullet points that together cover ALL of the changes

RULES:
- Mention every release by version and its key changes.
- Group related commits into themes (new features, breaking changes, bug fixes, performance, \
docs/CI/dependencies). Put what matters most to a user of the project first; summarize \
docs/CI/dependency churn in at most one bullet.
- Be specific (name the feature, API, or component) but concise; do not list commits one by one.
- If a change log says it shows only the latest commits, say so in the last bullet.
- Write in {language}. Output only the markdown above: no introduction, no headers, \
no conclusion.

{change_logs}
"""


class BaseLLM(ABC):
    """Abstract base class for LLM providers."""

    @abstractmethod
    async def summarize(
        self,
        articles: list[Article],
        prompt: str | None = None,
        focus: str = "",
        language: str = "English",
    ) -> str:
        """Generate a summary from collected articles.

        Args:
            articles: List of articles to summarize.
            prompt: Optional custom prompt template.
            focus: Optional focus instructions for the report.
            language: Language to write in.

        Returns:
            Generated summary text.
        """
        pass

    @abstractmethod
    async def generate_report(
        self,
        articles: list[Article],
        title: str,
        prompt: str | None = None,
        highlight_count: int = 10,
        focus: str = "",
        language: str = "English",
    ) -> str:
        """Generate a full report from collected articles.

        Args:
            articles: List of articles to include in report.
            title: Report title.
            prompt: Optional custom prompt template.
            highlight_count: Number of articles to feature in Highlight News.
            focus: Optional focus instructions for the report.
            language: Language to write in.

        Returns:
            Generated report in markdown format.
        """
        pass

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Get the provider name."""
        pass

    @abstractmethod
    async def _complete(self, prompt: str) -> str:
        """Send a single prompt and return the response text."""
        pass

    async def summarize_repo_changes(self, repos: list[Article], language: str = "English") -> str:
        """Summarize each repository's change log as markdown.

        Args:
            repos: One article per repository, whose content is its change log.
            language: Language to write the summaries in.

        Returns:
            Markdown with one entry per repository, in the given order.
        """
        change_logs = "\n\n".join(
            f"=== [{repo.title}]({repo.url}) ===\n{repo.content}" for repo in repos
        )
        return await self._complete(
            REPO_CHANGES_PROMPT.format(language=language, change_logs=change_logs)
        )

    def _format_articles_for_context(self, articles: list[Article]) -> str:
        """Format articles as context for LLM.

        Args:
            articles: List of articles.

        Returns:
            Formatted string of articles.
        """
        formatted = []
        for i, article in enumerate(articles, 1):
            image_line = ""
            if article.image_url:
                image_line = f"- **Image**: {article.image_url}\n"

            entry = f"""
### Article {i}: {article.title}
- **Source**: {article.source}
- **URL**: {article.url}
{image_line}- **Published**: {article.published_at or "Unknown"}

{article.content}
"""
            formatted.append(entry)
        return "\n".join(formatted)

"""Report generation using LLM."""

from datetime import date

from ..core.exceptions import LLMError
from ..llm.base import BaseLLM
from ..models.article import Article
from ..models.report import Report

REPO_BATCH_CHARS = 60_000  # Change-log characters per summarization call


class Summarizer:
    """Generates reports from collected articles using LLM."""

    def __init__(self, llm: BaseLLM):
        """Initialize summarizer.

        Args:
            llm: LLM instance for summarization.
        """
        self._llm = llm

    async def generate_report(
        self,
        articles: list[Article],
        title: str = "AI News Weekly Report",
        prompt: str | None = None,
        recipients: list[str] | None = None,
        highlight_count: int = 10,
        focus: str = "",
        repo_updates: list[Article] | None = None,
        language: str = "English",
    ) -> Report:
        """Generate a complete report from articles.

        Args:
            articles: List of articles to include.
            title: Report title.
            prompt: Optional custom prompt for LLM.
            recipients: Optional list of report recipients.
            highlight_count: Number of articles to feature in Highlight News.
            focus: Optional focus instructions for the report.
            repo_updates: Starred GitHub repository change logs, summarized in their own section.
            language: Language to write the report in.

        Returns:
            Generated Report object.
        """
        repo_updates = repo_updates or []

        if articles:
            # Generate summary using LLM
            summary = await self._llm.summarize(articles, prompt, focus, language)

            # Generate full markdown report
            content_markdown = await self._llm.generate_report(
                articles, title, prompt, highlight_count, focus, language
            )
        else:
            summary = "No news articles this period."
            content_markdown = f"# {title}\n\n"

        if repo_updates:
            content_markdown = (
                content_markdown.rstrip()
                + "\n\n"
                + await self._repo_section(repo_updates, language)
            )

        # Generate plain text version (strip markdown)
        content_text = self._markdown_to_text(content_markdown)

        # Generate HTML version
        content_html = self._markdown_to_html(content_markdown)

        return Report(
            title=title,
            date=date.today(),
            articles=articles + repo_updates,
            summary=summary,
            content_markdown=content_markdown,
            content_html=content_html,
            content_text=content_text,
            recipients=recipients or [],
        )

    async def _repo_section(self, repos: list[Article], language: str) -> str:
        """Summarize starred repositories' change logs as a markdown section."""
        # Split into batches so a few very active repos do not overflow one prompt
        batches: list[list[Article]] = [[]]
        size = 0
        for repo in repos:
            if batches[-1] and size + len(repo.content) > REPO_BATCH_CHARS:
                batches.append([])
                size = 0
            batches[-1].append(repo)
            size += len(repo.content)

        parts = []
        for batch in batches:
            try:
                parts.append((await self._llm.summarize_repo_changes(batch, language)).strip())
            except LLMError:
                parts.append(self._raw_repo_list(batch))
        return "---\n\n## GitHub Starred Updates\n\n" + "\n\n".join(parts) + "\n"

    def _raw_repo_list(self, repos: list[Article]) -> str:
        """Fallback when summarization fails: releases and the first commits of each repo."""
        entries = []
        for repo in repos:
            lines = [
                line.removeprefix("### ")
                for line in repo.content.splitlines()
                if line.startswith(("### ", "- "))
            ]
            bullets = "\n".join(f"- {line.removeprefix('- ')}" for line in lines[:10])
            entries.append(f"**[{repo.title}]({repo.url})**\n\n{bullets}")
        return "\n\n".join(entries)

    def _markdown_to_text(self, markdown: str) -> str:
        """Convert markdown to plain text.

        Args:
            markdown: Markdown content.

        Returns:
            Plain text version.
        """
        import re

        text = markdown
        # Remove markdown links, keep text
        text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
        # Remove markdown formatting
        text = re.sub(r"[*_`#]+", "", text)
        # Remove horizontal rules
        text = re.sub(r"^---+$", "", text, flags=re.MULTILINE)
        return text.strip()

    def _markdown_to_html(self, markdown: str) -> str:
        """Convert markdown to basic HTML.

        Args:
            markdown: Markdown content.

        Returns:
            HTML version.
        """
        import re

        html = markdown

        # Convert headers
        html = re.sub(r"^# (.+)$", r"<h1>\1</h1>", html, flags=re.MULTILINE)
        html = re.sub(r"^## (.+)$", r"<h2>\1</h2>", html, flags=re.MULTILINE)
        html = re.sub(r"^### (.+)$", r"<h3>\1</h3>", html, flags=re.MULTILINE)

        # Convert thumbnail images (small, ~3 lines height) - must be before regular images
        html = re.sub(
            r"!\[thumb\|([^\]]*)\]\((https?://[^\s)]+)\)",
            r'<img src="\2" alt="\1" style="max-height: 60px; width: auto; margin: 5px 0; border-radius: 4px;">',
            html,
        )

        # Convert regular images (must be before links) - handle URLs with special chars
        html = re.sub(
            r"!\[([^\]]*)\]\((https?://[^\s)]+)\)",
            r'<img src="\2" alt="\1" style="max-width: 100%; height: auto; margin: 10px 0;">',
            html,
        )

        # Convert bold (must be before italic)
        html = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", html)

        # Convert links - handle URLs with special chars
        html = re.sub(
            r"\[([^\]]+)\]\((https?://[^\s)]+)\)",
            r'<a href="\2">\1</a>',
            html,
        )

        # Convert italic (single * pairs only, not standalone *)
        html = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"<em>\1</em>", html)

        # Convert bullet points
        html = re.sub(r"^- (.+)$", r"<li>\1</li>", html, flags=re.MULTILINE)

        # Convert horizontal rules
        html = re.sub(r"^---+$", "<hr>", html, flags=re.MULTILINE)

        # Wrap in paragraphs (simple approach)
        lines = html.split("\n")
        processed = []
        for line in lines:
            line = line.strip()
            if line and not line.startswith("<"):
                line = f"<p>{line}</p>"
            processed.append(line)

        # Wrap in basic HTML structure
        body = "\n".join(processed)
        return f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
               max-width: 800px; margin: 0 auto; padding: 20px; line-height: 1.6; }}
        h1, h2, h3 {{ color: #333; }}
        a {{ color: #0066cc; }}
        li {{ margin: 8px 0; }}
        hr {{ border: none; border-top: 1px solid #ddd; margin: 20px 0; }}
        img {{ max-width: 100%; height: auto; border-radius: 8px; }}
    </style>
</head>
<body>
{body}
</body>
</html>"""

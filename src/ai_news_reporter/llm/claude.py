"""Claude (Anthropic) LLM implementation."""

import re

import anthropic

from ..core.exceptions import LLMError
from ..models.article import Article
from .base import BaseLLM

MAX_SUMMARY_CHARS = 800
# A period followed by whitespace (so "3.8" is not a sentence end), or a Japanese full stop
SENTENCE_END = re.compile(r"[.!?](?=\s)|[。！？]")

DEFAULT_SUMMARY_PROMPT = """You are a professional news analyst specializing in artificial intelligence and technology.

Write a brief 2-3 sentence executive summary of the key AI developments this week.

IMPORTANT RULES:
- Write ONLY 2-3 SHORT sentences. Be concise.
- NO headers, NO subsections, NO bullet points, NO numbered lists.
- Include inline source links using [Source Name](URL) format.
- Write in {language}.
- Example: "This week saw major advances in AI healthcare with [Utah's prescription AI initiative](url) and [OpenAI's Torch acquisition](url)."
{focus}
Here are the articles to analyze:

{articles}
"""


class ClaudeLLM(BaseLLM):
    """Claude (Anthropic) LLM provider."""

    def __init__(
        self,
        api_key: str,
        model: str = "claude-sonnet-4-20250514",
        max_tokens: int = 4096,
        temperature: float = 0.3,
    ):
        """Initialize Claude LLM.

        Args:
            api_key: Anthropic API key.
            model: Model to use.
            max_tokens: Maximum tokens in response.
            temperature: Sampling temperature.
        """
        if not api_key:
            raise LLMError("Anthropic API key is required")

        self._client = anthropic.Anthropic(api_key=api_key)
        self._model = model
        self._max_tokens = max_tokens
        self._temperature = temperature

    @property
    def provider_name(self) -> str:
        return "Claude (Anthropic)"

    async def summarize(
        self,
        articles: list[Article],
        prompt: str | None = None,
        focus: str = "",
        language: str = "English",
    ) -> str:
        """Generate a summary using Claude.

        Args:
            articles: List of articles to summarize.
            prompt: Optional custom prompt.
            focus: Optional focus instructions for the report.
            language: Language to write in.

        Returns:
            Generated summary.
        """
        if not articles:
            return "No articles to summarize."

        context = self._format_articles_for_context(articles)
        focus_text = f"\nFOCUS: {focus}\n" if focus else ""
        full_prompt = (prompt or DEFAULT_SUMMARY_PROMPT).format(
            articles=context, focus=focus_text, language=language
        )

        return self._clean_summary(await self._complete(full_prompt))

    async def _complete(self, prompt: str) -> str:
        try:
            message = self._client.messages.create(
                model=self._model,
                max_tokens=self._max_tokens,
                temperature=self._temperature,
                messages=[{"role": "user", "content": prompt}],
            )
            return message.content[0].text
        except anthropic.APIError as e:
            raise LLMError(f"Claude API error: {e}") from e

    def _clean_summary(self, summary: str) -> str:
        """Remove markdown headers, images, lists, and extra formatting from summary.

        Keep only the first paragraph (2-3 sentences max).
        """
        lines = summary.split("\n")
        cleaned_lines = []
        for line in lines:
            # Skip lines that are markdown headers
            if re.match(r"^#{1,6}\s", line):
                continue
            # Skip lines that are just "Executive Summary" or similar titles
            if re.match(
                r"^\*{0,2}(Executive Summary|Key Developments|Industry Impact|Trends to Watch|Weekly.*Report)\*{0,2}\s*$",
                line,
                re.IGNORECASE,
            ):
                continue
            # Skip image lines
            if re.match(r"^!\[", line):
                continue
            # Skip numbered list items (1. **Title**: ...)
            if re.match(r"^\d+\.\s+\*\*", line):
                continue
            # Skip lines that are just source references
            if re.match(r"^\*Source:", line):
                continue
            cleaned_lines.append(line)

        # Join and remove multiple consecutive blank lines
        result = "\n".join(cleaned_lines)
        result = re.sub(r"\n{3,}", "\n\n", result)
        result = result.strip()

        # Keep only first paragraph (should be 2-3 sentences)
        paragraphs = [p.strip() for p in result.split("\n\n") if p.strip()]
        if paragraphs:
            # Return only the first substantial paragraph, cut at a sentence end if too long
            first = paragraphs[0]
            if len(first) > MAX_SUMMARY_CHARS:
                ends = list(SENTENCE_END.finditer(first[:MAX_SUMMARY_CHARS]))
                first = first[: ends[-1].end()].strip() if ends else first[:MAX_SUMMARY_CHARS]
            return first
        return result

    async def generate_report(
        self,
        articles: list[Article],
        title: str,
        prompt: str | None = None,
        highlight_count: int = 10,
        focus: str = "",
        language: str = "English",
    ) -> str:
        """Generate a full report using Claude.

        Args:
            articles: List of articles.
            title: Report title.
            prompt: Optional custom prompt.
            highlight_count: Number of articles to feature in Highlight News.
            focus: Optional focus instructions for the report.
            language: Language to write in.

        Returns:
            Generated report in markdown.
        """
        summary = await self.summarize(articles, prompt, focus, language)

        # Split articles into highlights and related
        highlight_articles = articles[:highlight_count]
        related_articles = articles[highlight_count:]

        report = f"""# {title}

*Generated by AI News Reporter using {self.provider_name}*

---

## 1. Executive Summary

{summary}

---

## 2. Highlight News

"""
        # Highlight news with images (normal text, no ### headers)
        for i, article in enumerate(highlight_articles, 1):
            report += f"**2.{i}.** [{article.title}]({article.url})\n\n"
            if article.image_url:
                report += f"![{article.title}]({article.image_url})\n\n"
            clean_content = self._clean_article_content(article.content)
            report += f"{clean_content}\n\n"
            report += f"*Source: {article.source}*"
            if article.published_at:
                report += f" | *Published: {article.published_at.strftime('%Y-%m-%d')}*"
            report += "\n\n---\n\n"

        # Related news (citations) with small thumbnail images
        if related_articles:
            report += "## 3. Related News\n\n"
            for i, article in enumerate(related_articles, 1):
                report += f"**3.{i}.** [{article.title}]({article.url})"
                if article.published_at:
                    report += f" ({article.published_at.strftime('%Y-%m-%d')})"
                report += "\n\n"
                if article.image_url:
                    report += f"![thumb|{article.title}]({article.image_url})\n\n"
                clean_content = self._clean_article_content(article.content[:200])
                report += f"{clean_content}{'...' if len(article.content) > 200 else ''}\n\n"

        return report

    def _clean_article_content(self, content: str) -> str:
        """Remove all markdown headers and formatting from article content."""
        # Remove markdown headers anywhere (# ## ### etc followed by space)
        content = re.sub(r"#{1,6}\s+", "", content)
        # Remove standalone * bullets
        content = re.sub(r"^\*\s+", "", content, flags=re.MULTILINE)
        return content.strip()

"""Web search collector that runs Claude Code's WebSearch tool (no search API key)."""

import asyncio
import json
from datetime import datetime

from ..core.exceptions import CollectorError, LLMError
from ..llm.claude_code import resolve_cli, run_claude_cli
from ..models.article import Article
from .base import BaseCollector
from .image_extractor import extract_og_image

TIME_RANGE_DAYS = {"day": 1, "week": 7, "month": 30, "year": 365}

RESULT_SCHEMA = {
    "type": "object",
    "properties": {
        "articles": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "url": {"type": "string"},
                    "summary": {"type": "string"},
                    "published_date": {"type": "string"},
                },
                "required": ["title", "url", "summary"],
            },
        }
    },
    "required": ["articles"],
}

SEARCH_PROMPT = """Today is {today}. Use web search to find news articles about "{query}" \
published in the last {days} days.

- Return at most {max_results} distinct articles, most important first.
- Only include articles you actually found in search results; never invent URLs.
- Skip anything older than {days} days.
{domain_rules}- "summary": 2-4 factual sentences in {language} describing the article itself \n(never mention yourself, the search, or snippets).
- "title": the original headline, untranslated.
- "published_date": ISO 8601 date (YYYY-MM-DD) if known, otherwise omit.
"""


class ClaudeWebSearchCollector(BaseCollector):
    """Searches the web through `claude -p` with only WebSearch enabled.

    Usage is billed to the Claude account the CLI is logged in with.
    """

    def __init__(
        self,
        model: str = "sonnet",
        cli_path: str = "claude",
        fetch_images: bool = True,
        language: str = "English",
    ):
        try:
            self._cli = resolve_cli(cli_path)
        except LLMError as e:
            raise CollectorError(str(e)) from e
        self._model = model
        self._fetch_images = fetch_images
        self._language = language

    @property
    def name(self) -> str:
        return "Claude Web Search"

    async def collect(
        self,
        query: str,
        time_range: str = "week",
        max_results: int = 10,
        include_domains: list[str] | None = None,
        exclude_domains: list[str] | None = None,
        **kwargs,
    ) -> list[Article]:
        """Search the web for recent news about the query."""
        domain_rules = ""
        if include_domains:
            domain_rules += f"- Only use these domains: {', '.join(include_domains)}\n"
        if exclude_domains:
            domain_rules += f"- Never use these domains: {', '.join(exclude_domains)}\n"
        prompt = SEARCH_PROMPT.format(
            today=datetime.now().date().isoformat(),
            query=query,
            days=TIME_RANGE_DAYS.get(time_range, 7),
            max_results=max_results,
            domain_rules=domain_rules,
            language=self._language,
        )

        try:
            out = await run_claude_cli(
                self._cli,
                prompt,
                self._model,
                tools=["WebSearch"],
                extra_args=["--output-format", "json", "--json-schema", json.dumps(RESULT_SCHEMA)],
            )
        except LLMError as e:
            raise CollectorError(f"Claude web search failed: {e}") from e

        articles = []
        for item in self._parse_results(out)[:max_results]:
            try:
                articles.append(
                    Article(
                        title=item.get("title") or "Untitled",
                        url=item["url"],
                        content=item.get("summary", ""),
                        source="Claude Web Search",
                        published_at=self._parse_date(item.get("published_date")),
                        collected_at=datetime.now(),
                        keywords=[query],
                    )
                )
            except (KeyError, ValueError):
                continue  # Malformed URL or missing field

        if self._fetch_images and articles:
            images = await asyncio.gather(
                *(extract_og_image(str(a.url)) for a in articles), return_exceptions=True
            )
            for article, image in zip(articles, images):
                if isinstance(image, str):
                    article.image_url = image

        return articles

    def _parse_results(self, out: str) -> list[dict]:
        """Extract the article list from the CLI's JSON result envelope."""
        try:
            envelope = json.loads(out)
        except json.JSONDecodeError as e:
            raise CollectorError(f"Unexpected Claude Code output: {out[:200]}") from e
        if envelope.get("is_error"):
            raise CollectorError(f"Claude web search failed: {envelope.get('result')}")

        data = envelope.get("structured_output")
        if data is None:
            # Fall back to the text result, which should hold the same JSON
            text = str(envelope.get("result", "")).strip().removeprefix("```json").strip("`\n ")
            try:
                data = json.loads(text)
            except json.JSONDecodeError as e:
                raise CollectorError(f"Could not parse search results: {text[:200]}") from e
        return [a for a in data.get("articles", []) if isinstance(a, dict)]

    def _parse_date(self, date_str: str | None) -> datetime | None:
        if not date_str:
            return None
        try:
            return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        except ValueError:
            return None

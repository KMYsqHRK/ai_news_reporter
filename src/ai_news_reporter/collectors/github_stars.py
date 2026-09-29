"""Collector for all recent changes (releases and commits) of a user's starred GitHub repos."""

import asyncio
from datetime import UTC, datetime, timedelta
from xml.etree import ElementTree

import httpx
from bs4 import BeautifulSoup

from ..core.exceptions import CollectorError
from ..models.article import Article
from .base import BaseCollector

API_URL = "https://api.github.com"
TIME_RANGE_DAYS = {"day": 1, "week": 7, "month": 30, "year": 365}
MAX_STAR_PAGES = 20  # 100 repos per page
MAX_COMMIT_PAGES = 5  # 100 commits per page
MAX_COMMIT_LINES = 300  # Commits listed per repo in the change log
MAX_RELEASE_NOTES = 3000  # Characters of each release's notes
CONCURRENCY = 8
SOURCE = "GitHub Stars"
ATOM_NS = {"atom": "http://www.w3.org/2005/Atom"}
BLOCK_TAGS = ["p", "li", "h1", "h2", "h3", "h4", "h5", "h6", "pre", "tr"]
MERGE_PREFIXES = ("Merge pull request", "Merge branch", "Merge remote-tracking branch")


class RateLimitedError(Exception):
    """The GitHub API rate limit is exhausted."""


class GitHubStarsCollector(BaseCollector):
    """Collects every release and commit of starred repositories within a time range.

    Each active repository becomes one Article whose content is its full change log, ready to be
    summarized by the LLM. Releases come from releases.atom (no rate limit). Commits come from the
    REST API (60 requests/hour without a token); once that runs out, the remaining repositories
    fall back to commits.atom, which only holds the latest 20 commits.
    """

    def __init__(
        self,
        username: str = "",
        token: str = "",
        include_commits: bool = True,
        exclude: list[str] | None = None,
    ):
        """Initialize the collector.

        Args:
            username: GitHub user whose stars to follow (defaults to the token's owner).
            token: Optional GitHub token (raises the API rate limit from 60 to 5000/hour).
            include_commits: Include commits in addition to releases.
            exclude: Repositories ("owner/name") to skip.
        """
        if not username and not token:
            raise CollectorError("github.username (or GITHUB_TOKEN) is required")
        self._username = username
        self._exclude = exclude or []
        self._include_commits = include_commits
        self._api_headers = {"Accept": "application/vnd.github+json"}
        if token:
            self._api_headers["Authorization"] = f"Bearer {token}"
        self._rate_limited = False

    @property
    def name(self) -> str:
        return SOURCE

    async def collect(
        self, query: str = "", time_range: str = "week", max_items: int = 30, **kwargs
    ) -> list[Article]:
        """Collect the change logs of repositories updated within the time range.

        Args:
            query: Unused (the starred list defines what is collected).
            time_range: day, week, month or year.
            max_items: Maximum number of repositories to return (most recently changed first).
        """
        since = datetime.now(UTC) - timedelta(days=TIME_RANGE_DAYS.get(time_range, 7))
        headers = {"User-Agent": "ai-news-reporter"}
        async with httpx.AsyncClient(timeout=30, headers=headers, follow_redirects=True) as client:
            try:
                repos = await self._starred_repos(client)
            except httpx.HTTPError as e:
                raise CollectorError(f"GitHub starred list failed: {e}") from e
            excluded = {name.lower() for name in self._exclude}
            active = [
                r
                for r in repos
                if self._parse_date(r.get("pushed_at")) >= since
                and r["full_name"].lower() not in excluded
            ]

            sem = asyncio.Semaphore(CONCURRENCY)

            async def fetch(repo: dict) -> Article | None:
                async with sem:
                    return await self._repo_changes(client, repo, since)

            results = await asyncio.gather(*(fetch(r) for r in active), return_exceptions=True)

        # A single repo failing (network error, odd XML) should not drop the rest
        articles = [a for a in results if isinstance(a, Article)]
        articles.sort(key=lambda a: a.published_at, reverse=True)
        return articles[:max_items]

    async def _starred_repos(self, client: httpx.AsyncClient) -> list[dict]:
        path = f"/users/{self._username}/starred" if self._username else "/user/starred"
        repos: list[dict] = []
        for page in range(1, MAX_STAR_PAGES + 1):
            resp = await client.get(
                f"{API_URL}{path}",
                params={"per_page": 100, "page": page},
                headers=self._api_headers,
            )
            if resp.status_code != 200:
                raise CollectorError(
                    f"GitHub starred list failed ({resp.status_code}): {resp.text[:200]}"
                )
            batch = resp.json()
            repos.extend(batch)
            if len(batch) < 100:
                break
        return repos

    async def _repo_changes(
        self, client: httpx.AsyncClient, repo: dict, since: datetime
    ) -> Article | None:
        """Build one repository's change log for the period, or None if nothing changed."""
        full_name = repo["full_name"]
        html_url = repo["html_url"]

        releases = [
            e for e in await self._feed(client, f"{html_url}/releases.atom") if e[0] >= since
        ]
        commits: list[tuple[datetime, str]] = []
        partial = False
        if self._include_commits:
            commits, partial = await self._commits(client, repo, since)
        if not releases and not commits:
            return None

        parts = []
        if repo.get("description"):
            parts.append(f"Description: {repo['description']}")
        if releases:
            parts.append(f"Releases ({len(releases)}):")
            for updated, title, link, body in releases:
                if len(body) > MAX_RELEASE_NOTES:
                    body = body[:MAX_RELEASE_NOTES] + "\n...(truncated)"
                parts.append(f"### {title} ({updated.date()}) {link}\n{body}")
        if commits:
            label = f"latest {len(commits)} only" if partial else str(len(commits))
            parts.append(f"Commits ({label}):")
            parts.extend(f"- {message}" for _, message in commits[:MAX_COMMIT_LINES])
            if len(commits) > MAX_COMMIT_LINES:
                parts.append(f"- ...and {len(commits) - MAX_COMMIT_LINES} more commits")

        counts = []
        if releases:
            counts.append(f"{len(releases)} release{'s' if len(releases) > 1 else ''}")
        if commits:
            n = f"{len(commits)}+" if partial else str(len(commits))
            counts.append(f"{n} commit{'s' if len(commits) > 1 else ''}")

        return Article(
            title=f"{full_name} ({', '.join(counts)})",
            url=html_url,
            content="\n".join(parts),
            source=SOURCE,
            published_at=max([e[0] for e in releases] + [c[0] for c in commits]),
            keywords=[full_name],
        )

    async def _commits(
        self, client: httpx.AsyncClient, repo: dict, since: datetime
    ) -> tuple[list[tuple[datetime, str]], bool]:
        """Return (date, "message (sha)") for the default branch, and whether the list is partial.

        Merge commits are skipped: their content is already in the merged commits.
        """
        commits, partial = None, True
        if not self._rate_limited:
            try:
                commits, partial = await self._api_commits(client, repo["full_name"], since)
            except RateLimitedError:
                self._rate_limited = True
        if commits is None:
            feed = await self._feed(client, f"{repo['html_url']}/commits.atom")
            commits = [(d, title) for d, title, _, _ in feed if d >= since]
        return [c for c in commits if not c[1].startswith(MERGE_PREFIXES)], partial

    async def _api_commits(
        self, client: httpx.AsyncClient, full_name: str, since: datetime
    ) -> tuple[list[tuple[datetime, str]], bool]:
        """Return the period's commits and whether MAX_COMMIT_PAGES cut the list short."""
        commits = []
        for page in range(1, MAX_COMMIT_PAGES + 1):
            resp = await client.get(
                f"{API_URL}/repos/{full_name}/commits",
                params={"since": since.isoformat(), "per_page": 100, "page": page},
                headers=self._api_headers,
            )
            if resp.status_code in (403, 429) and resp.headers.get("x-ratelimit-remaining") == "0":
                raise RateLimitedError
            if resp.status_code == 409:  # Empty repository
                return [], False
            resp.raise_for_status()
            batch = resp.json()
            for item in batch:
                message = item["commit"]["message"].strip().splitlines()
                date = self._parse_date(item["commit"]["committer"]["date"])
                commits.append((date, f"{message[0] if message else ''} ({item['sha'][:7]})"))
            if len(batch) < 100:
                return commits, False
        return commits, True

    async def _feed(
        self, client: httpx.AsyncClient, url: str
    ) -> list[tuple[datetime, str, str, str]]:
        """Parse an Atom feed into (updated, title, link, plain-text body) tuples."""
        resp = await client.get(url)
        if resp.status_code != 200:
            return []
        try:
            root = ElementTree.fromstring(resp.content)
        except ElementTree.ParseError:
            return []
        entries = []
        for entry in root.iterfind("atom:entry", ATOM_NS):
            link = entry.find("atom:link", ATOM_NS)
            body = self._html_to_text(entry.findtext("atom:content", "", ATOM_NS))
            # Commit titles can span lines; keep the first one
            title_lines = entry.findtext("atom:title", "", ATOM_NS).strip().splitlines()
            entries.append(
                (
                    self._parse_date(entry.findtext("atom:updated", None, ATOM_NS)),
                    title_lines[0].strip() if title_lines else "Untitled",
                    link.get("href", "") if link is not None else "",
                    body,
                )
            )
        return entries

    @staticmethod
    def _html_to_text(html: str) -> str:
        """Flatten release-note HTML to text with one line per paragraph or list item."""
        if not html:
            return ""
        soup = BeautifulSoup(html, "lxml")
        for br in soup.find_all("br"):
            br.replace_with("\n")
        for block in soup.find_all(BLOCK_TAGS):
            prefix = "- " if block.name == "li" else ""
            block.insert_before(f"\n{prefix}")
            block.insert_after("\n")
        lines = (" ".join(line.split()) for line in soup.get_text().splitlines())
        return "\n".join(line for line in lines if line)

    @staticmethod
    def _parse_date(value: str | None) -> datetime:
        if not value:
            return datetime.min.replace(tzinfo=UTC)
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return datetime.min.replace(tzinfo=UTC)

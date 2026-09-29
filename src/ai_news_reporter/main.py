"""CLI entry point for AI News Reporter."""

import asyncio
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn

from .collectors import (
    ClaudeWebSearchCollector,
    GitHubStarsCollector,
    TavilyCollector,
    WebScraper,
)
from .core.config import AppConfig, Settings
from .core.exceptions import AINewsReporterError
from .delivery import EmailDelivery, FileDelivery, SlackDelivery
from .llm import create_llm
from .processors import Deduplicator, Summarizer
from .scheduler import ReportScheduler

app = typer.Typer(
    name="ai-news",
    help="AI News Reporter - Automated AI news collection and reporting",
)
console = Console()


async def run_report_async(settings: Settings, config: AppConfig) -> None:
    """Run report generation asynchronously."""
    all_articles = []
    repo_updates = []

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        # Collect from web search
        search = config.search
        collector = None
        if search.enabled and search.provider == "claude_code":
            try:
                collector = ClaudeWebSearchCollector(
                    model=config.llm.model if config.llm.provider == "claude_code" else "sonnet",
                    cli_path=config.llm.cli_path,
                    language=config.report.language,
                )
            except AINewsReporterError as e:
                console.print(f"[yellow]Claude web search unavailable: {e}[/yellow]")
        elif search.enabled and settings.tavily_api_key:
            collector = TavilyCollector(settings.tavily_api_key)

        if collector:
            task = progress.add_task(f"Searching news with {collector.name}...", total=None)
            for keyword in config.keywords:
                try:
                    articles = await collector.collect(
                        query=keyword,
                        time_range=search.time_range,
                        max_results=search.max_results_per_keyword,
                        include_domains=search.include_domains or None,
                        exclude_domains=search.exclude_domains or None,
                    )
                    all_articles.extend(articles)
                except AINewsReporterError as e:
                    console.print(f"[yellow]Search for {keyword!r} failed: {e}[/yellow]")
            progress.update(task, completed=True)

        # Collect updates of starred GitHub repositories
        github = config.github
        if github.enabled:
            task = progress.add_task("Checking starred GitHub repositories...", total=None)
            try:
                gh_collector = GitHubStarsCollector(
                    username=github.username,
                    token=settings.github_token,
                    include_commits=github.include_commits,
                    exclude=github.exclude,
                )
                repo_updates = await gh_collector.collect(
                    time_range=github.time_range, max_items=github.max_items
                )
                progress.update(task, completed=True)
            except AINewsReporterError as e:
                console.print(f"[yellow]GitHub stars collection failed: {e}[/yellow]")

        # Collect from configured sites
        sites = [s for s in config.sites if s.enabled]
        if sites:
            task = progress.add_task("Scraping configured sites...", total=None)
            try:
                scraper = WebScraper()
                site_articles = await scraper.collect_from_sites(sites)
                all_articles.extend(site_articles)
                progress.update(task, completed=True)
            except AINewsReporterError as e:
                console.print(f"[yellow]Web scraping failed: {e}[/yellow]")

    if not all_articles and not repo_updates:
        console.print("[red]No articles collected. Check your configuration.[/red]")
        raise typer.Exit(1)

    console.print(f"[green]Collected {len(all_articles)} articles[/green]")
    if config.github.enabled:
        console.print(f"[green]Found changes in {len(repo_updates)} starred repositories[/green]")

    # Deduplicate
    if config.report.deduplicate:
        dedup = Deduplicator()
        all_articles = dedup.deduplicate(all_articles)
        console.print(f"[green]After deduplication: {len(all_articles)} articles[/green]")

    # Limit articles
    if config.report.max_articles and len(all_articles) > config.report.max_articles:
        all_articles = all_articles[: config.report.max_articles]
        console.print(f"[green]Limited to {len(all_articles)} articles[/green]")

    # Generate report with LLM
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Generating report with LLM...", total=None)

        # Determine API key based on provider
        provider = config.llm.provider
        if provider == "openai":
            api_key = settings.openai_api_key
        else:
            api_key = settings.anthropic_api_key

        llm = create_llm(
            provider=provider,
            api_key=api_key,
            model=config.llm.model,
            max_tokens=config.llm.max_tokens,
            temperature=config.llm.temperature,
            cli_path=config.llm.cli_path,
        )

        summarizer = Summarizer(llm)
        report = await summarizer.generate_report(
            articles=all_articles,
            title=config.report.title,
            prompt=config.llm.summary_prompt,
            recipients=config.delivery.email_recipients,
            highlight_count=config.report.highlight_count,
            focus=config.report.focus,
            repo_updates=repo_updates,
            language=config.report.language,
        )
        progress.update(task, completed=True)

    console.print(f"[green]Report generated: {report.title}[/green]")

    # Deliver report
    delivery_count = 0

    # File delivery
    if config.delivery.file_enabled:
        try:
            file_delivery = FileDelivery(
                output_dir=Path(config.delivery.file_output_dir),
                formats=config.delivery.file_formats,
            )
            await file_delivery.deliver(report)
            console.print(f"[green]Report saved to {file_delivery.output_dir}[/green]")
            delivery_count += 1
        except AINewsReporterError as e:
            console.print(f"[red]File delivery failed: {e}[/red]")

    # Email delivery
    if config.delivery.email_enabled:
        try:
            email_delivery = EmailDelivery(
                host=settings.smtp_host,
                port=settings.smtp_port,
                user=settings.smtp_user,
                password=settings.smtp_password,
                recipients=config.delivery.email_recipients,
                subject_prefix=config.delivery.email_subject_prefix,
            )
            await email_delivery.deliver(report)
            console.print("[green]Report sent via email[/green]")
            delivery_count += 1
        except AINewsReporterError as e:
            console.print(f"[red]Email delivery failed: {e}[/red]")

    # Slack delivery
    if config.delivery.slack_enabled and settings.slack_bot_token:
        try:
            slack_delivery = SlackDelivery(
                bot_token=settings.slack_bot_token,
                user_ids=config.delivery.slack_user_ids,
            )
            await slack_delivery.deliver(report)
            console.print("[green]Report sent to Slack[/green]")
            delivery_count += 1
        except AINewsReporterError as e:
            console.print(f"[red]Slack delivery failed: {e}[/red]")

    if delivery_count == 0:
        console.print("[yellow]Warning: No delivery methods succeeded[/yellow]")


@app.command()
def run(
    config_path: Path = typer.Option(
        Path("config/config.yaml"),
        "--config",
        "-c",
        help="Path to configuration file",
    ),
) -> None:
    """Run news collection and report generation."""
    console.print(
        Panel.fit(
            "[bold blue]AI News Reporter[/bold blue]\nCollecting and summarizing AI news",
            border_style="blue",
        )
    )

    try:
        settings = Settings()
        config = AppConfig(config_path)
    except Exception as e:
        console.print(f"[red]Configuration error: {e}[/red]")
        raise typer.Exit(1) from e

    try:
        asyncio.run(run_report_async(settings, config))
        console.print("[bold green]Report generation complete![/bold green]")
    except AINewsReporterError as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1) from e


@app.command()
def schedule(
    config_path: Path = typer.Option(
        Path("config/config.yaml"),
        "--config",
        "-c",
        help="Path to configuration file",
    ),
) -> None:
    """Start the scheduler daemon for automated reports."""
    console.print(
        Panel.fit(
            "[bold blue]AI News Reporter Scheduler[/bold blue]\nRunning in daemon mode",
            border_style="blue",
        )
    )

    try:
        settings = Settings()
        config = AppConfig(config_path)
    except Exception as e:
        console.print(f"[red]Configuration error: {e}[/red]")
        raise typer.Exit(1) from e

    schedule_config = config.schedule
    if not schedule_config.enabled:
        console.print("[yellow]Scheduling is disabled in config[/yellow]")
        raise typer.Exit(0)

    console.print(
        f"[green]Scheduling {schedule_config.type} reports on "
        f"{schedule_config.day_of_week} at {schedule_config.time} "
        f"({schedule_config.timezone})[/green]"
    )

    def job():
        asyncio.run(run_report_async(settings, config))

    scheduler = ReportScheduler(timezone=schedule_config.timezone)
    scheduler.schedule_from_config(schedule_config, job)

    console.print("[green]Scheduler started. Press Ctrl+C to stop.[/green]")
    scheduler.run_forever()


@app.command()
def validate(
    config_path: Path = typer.Option(
        Path("config/config.yaml"),
        "--config",
        "-c",
        help="Path to configuration file",
    ),
) -> None:
    """Validate configuration files."""
    console.print("[bold]Validating configuration...[/bold]")

    # Check .env
    try:
        settings = Settings()
        console.print("[green]✓ config/.env loaded[/green]")

        if settings.anthropic_api_key:
            console.print("  - Anthropic API key: configured")
        else:
            console.print("  - [yellow]Anthropic API key: not set[/yellow]")

        if settings.openai_api_key:
            console.print("  - OpenAI API key: configured")
        else:
            console.print("  - [yellow]OpenAI API key: not set[/yellow]")

        if settings.tavily_api_key:
            console.print("  - Tavily API key: configured")
        else:
            console.print("  - [yellow]Tavily API key: not set[/yellow]")

    except Exception as e:
        console.print(f"[red]✗ config/.env error: {e}[/red]")
        raise typer.Exit(1) from e

    # Check config.yaml
    try:
        config = AppConfig(config_path)
        console.print(f"[green]✓ {config_path} loaded[/green]")
        console.print(f"  - Keywords: {len(config.keywords)}")
        console.print(f"  - Sites: {len(config.sites)}")
        console.print(f"  - LLM provider: {config.llm.provider}")
        console.print(f"  - Search provider: {config.search.provider}")
        if config.github.enabled:
            who = config.github.username or "(GITHUB_TOKEN owner)"
            console.print(f"  - GitHub stars: {who}, last {config.github.time_range}")
        if config.schedule.type == "weekly":
            console.print(
                f"  - Schedule: {config.schedule.type} on {config.schedule.day_of_week} "
                f"at {config.schedule.time} ({config.schedule.timezone})"
            )
        else:
            console.print(
                f"  - Schedule: {config.schedule.type} at {config.schedule.time} "
                f"({config.schedule.timezone})"
            )

    except Exception as e:
        console.print(f"[red]✗ {config_path} error: {e}[/red]")
        raise typer.Exit(1) from e

    console.print("[bold green]Configuration is valid![/bold green]")


if __name__ == "__main__":
    app()

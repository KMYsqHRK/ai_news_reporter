"""Claude Code CLI LLM implementation (uses the logged-in Claude account, no API key)."""

import asyncio
import os
import shutil
import tempfile
from pathlib import Path

from ..core.exceptions import LLMError
from .claude import ClaudeLLM

TIMEOUT_SECONDS = 600


def resolve_cli(cli_path: str) -> str:
    """Resolve the Claude Code executable or raise with a hint about cli_path."""
    resolved = shutil.which(cli_path)
    if not resolved:
        raise LLMError(
            f"Claude Code CLI not found: {cli_path!r}. Set llm.cli_path in config.yaml to the "
            "absolute path printed by `which claude` (cron does not see your shell PATH)."
        )
    return resolved


async def run_claude_cli(
    cli: str,
    prompt: str,
    model: str,
    tools: list[str] | None = None,
    extra_args: list[str] | None = None,
) -> str:
    """Run `claude -p` with the given prompt on stdin and return stdout.

    Args:
        cli: Resolved Claude Code executable.
        prompt: Prompt text.
        model: Model alias or name.
        tools: Built-in tools to enable and pre-approve (none by default).
        extra_args: Additional CLI arguments (e.g. output format).
    """
    env = dict(os.environ)
    # The CLI prefers ANTHROPIC_API_KEY over the account login; drop it so usage goes to the account.
    env.pop("ANTHROPIC_API_KEY", None)
    # The CLI is a node script; cron's PATH usually lacks node (e.g. under nvm), so add its bin dir.
    env["PATH"] = f"{Path(cli).parent}{os.pathsep}{env.get('PATH', '')}"
    tools = tools or []
    cmd = [cli, "-p", "--model", model, "--tools", ",".join(tools)]
    if tools:
        cmd += ["--allowedTools", ",".join(tools)]
    cmd += ["--strict-mcp-config", "--no-session-persistence", *(extra_args or [])]
    # An empty cwd keeps the project's CLAUDE.md out of the prompt.
    with tempfile.TemporaryDirectory() as cwd:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=cwd,
            env=env,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            out, err = await asyncio.wait_for(proc.communicate(prompt.encode()), TIMEOUT_SECONDS)
        except TimeoutError as e:
            proc.kill()
            raise LLMError(f"Claude Code timed out after {TIMEOUT_SECONDS}s") from e

    if proc.returncode != 0:
        detail = (err or out).decode(errors="replace").strip()
        raise LLMError(f"Claude Code error (exit {proc.returncode}): {detail}")
    return out.decode(errors="replace")


class ClaudeCodeLLM(ClaudeLLM):
    """Runs prompts through `claude -p`, billed to the Claude account the CLI is logged in with."""

    def __init__(self, model: str = "sonnet", cli_path: str = "claude"):
        self._cli = resolve_cli(cli_path)
        self._model = model

    @property
    def provider_name(self) -> str:
        return "Claude Code"

    async def _complete(self, prompt: str) -> str:
        return await run_claude_cli(
            self._cli, prompt, self._model, extra_args=["--output-format", "text"]
        )

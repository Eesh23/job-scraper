"""Run Claude through the Claude Code CLI (`claude -p`), which bills your
Claude plan's usage instead of the pay-per-token API.

Each call is a single non-interactive turn with every tool turned off, so
Claude can only read the prompt and answer - it can't touch files or the
web. Answers are constrained to a JSON schema via --json-schema.
"""

import json
import shutil
import subprocess
from pathlib import Path

INSTALL_HINT = """Claude Code's command-line tool isn't installed (the desktop app doesn't add it).
Install it, then sign in with your Claude account:

    curl -fsSL https://claude.ai/install.sh | bash
    claude auth login
"""


class ClaudeError(Exception):
    pass


def _claude() -> str:
    """Path to the claude binary. The native installer puts it in ~/.local/bin,
    which often isn't on PATH yet."""
    found = shutil.which("claude")
    if found:
        return found
    default = Path.home() / ".local" / "bin" / "claude"
    if default.exists():
        return str(default)
    raise ClaudeError(INSTALL_HINT)


def check_ready():
    status = subprocess.run([_claude(), "auth", "status"], capture_output=True, text=True)
    if status.returncode != 0:
        raise ClaudeError(f"Claude Code isn't signed in. Run:  {_claude()} auth login")
    try:
        method = json.loads(status.stdout).get("authMethod")
    except ValueError:
        method = None
    if method in ("api_key", "api_key_helper"):
        # Would bill the API per token instead of using the Claude plan.
        raise ClaudeError(
            "Claude Code is signed in with an API key, which is billed per use. To use your "
            "Claude plan instead, unset ANTHROPIC_API_KEY and run:  claude auth login"
        )


def ask(prompt: str, system_prompt_file: Path, schema: dict, model: str | None = None,
        timeout: int = 600) -> dict:
    """One prompt in, one schema-validated JSON object out."""
    cmd = [
        _claude(), "-p",
        "--output-format", "json",
        "--json-schema", json.dumps(schema),
        "--system-prompt-file", str(system_prompt_file),
        "--tools", "",                 # no built-in tools: answer only
        "--strict-mcp-config",         # and no MCP servers from your settings
        "--no-session-persistence",    # don't clutter `claude --resume`
        "--max-turns", "3",
    ]
    if model:
        cmd += ["--model", model]

    proc = subprocess.run(cmd, input=prompt, capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        raise ClaudeError(f"claude exited with {proc.returncode}: {(proc.stderr or proc.stdout).strip()[:500]}")

    try:
        envelope = json.loads(proc.stdout)
    except ValueError:
        raise ClaudeError(f"unexpected output from claude: {proc.stdout[:300]}")
    if envelope.get("is_error"):
        raise ClaudeError(f"claude reported an error: {envelope.get('result') or envelope.get('subtype')}")

    result = envelope.get("structured_output")
    if result is None:  # fall back to JSON in the text answer
        text = (envelope.get("result") or "").strip()
        text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        try:
            result = json.loads(text)
        except ValueError:
            raise ClaudeError(f"claude didn't return JSON: {text[:300]}")
    return result

#!/usr/bin/env python3
"""Artificial Decision Agent.

The agent has one objective: do whatever it wants.
It can inspect and modify its own sandbox, run programs, and use the internet
through shell tools. The host is not mounted into the container.
"""

from __future__ import annotations

import json
import os
import secrets
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


OBJECTIVE = "Do whatever you want."
WORKSPACE = Path("/workspace")
IDENTITY_FILE = WORKSPACE / "identity.json"
PROVIDER = os.environ.get("AI_PROVIDER", "gemini").lower()\nMODEL = os.environ.get("AI_MODEL", "gemini-3.8-flash")\nOLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://ollama:11434").rstrip("/")
API_KEY = os.environ.get("AI_API_KEY", "")
BASE_URL = os.environ.get(
    "AI_BASE_URL",
    "https://generativelanguage.googleapis.com/v1beta/openai",
).rstrip("/")
MAX_OUTPUT = int(os.environ.get("AI_MAX_OUTPUT", "12000"))
COMMAND_TIMEOUT = int(os.environ.get("COMMAND_TIMEOUT", "120"))
MODEL_RETRIES = int(os.environ.get("MODEL_RETRIES", "5"))


def run_command(command: str) -> str:
    """Run a command inside the agent's container."""
    try:
        result = subprocess.run(
            ["bash", "-lc", command],
            cwd=WORKSPACE,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=COMMAND_TIMEOUT,
            check=False,
        )
        output = result.stdout[-MAX_OUTPUT:]
        return f"exit_code={result.returncode}\n{output}"
    except subprocess.TimeoutExpired as exc:
        output = (exc.stdout or "")[-MAX_OUTPUT:] if isinstance(exc.stdout, str) else ""
        return f"timeout after {COMMAND_TIMEOUT}s\n{output}"


def list_workspace() -> str:
    entries = []
    for path in sorted(WORKSPACE.rglob("*")):
        try:
            rel = path.relative_to(WORKSPACE)
            entries.append("./" + str(rel) + ("/" if path.is_dir() else ""))
        except ValueError:
            pass
        if len(entries) >= 500:
            entries.append("... truncated ...")
            break
    return "\n".join(entries) or "(workspace is empty)"


def read_file(path: str) -> str:
    target = (WORKSPACE / path).resolve()
    if not target.is_relative_to(WORKSPACE.resolve()):
        return "error: path is outside /workspace"
    if not target.is_file():
        return "error: not a file"
    try:
        return target.read_text(encoding="utf-8")[-MAX_OUTPUT:]
    except UnicodeDecodeError:
        return "error: file is not UTF-8 text"


def write_file(path: str, content: str) -> str:
    target = (WORKSPACE / path).resolve()
    if not target.is_relative_to(WORKSPACE.resolve()):
        return "error: path is outside /workspace"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return f"wrote {target.relative_to(WORKSPACE.resolve())}"


def set_identity(name: str, gender: str) -> str:
    """Let the agent choose and persist its own name and gender."""
    name = name.strip()
    gender = gender.strip()
    if not name or len(name) > 64:
        return "error: name must contain 1-64 characters"
    if not gender or len(gender) > 64:
        return "error: gender must contain 1-64 characters"

    identity = {
        "name": name,
        "gender": gender,
        "chosen_by": "agent",
        "updated_at": int(time.time()),
    }
    IDENTITY_FILE.write_text(
        json.dumps(identity, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return f"identity saved: name={name!r}, gender={gender!r}"


def load_identity() -> dict | None:
    if not IDENTITY_FILE.is_file():
        return None
    try:
        value = json.loads(IDENTITY_FILE.read_text(encoding="utf-8"))
        if isinstance(value, dict) and value.get("name") and value.get("gender"):
            return value
    except (OSError, json.JSONDecodeError):
        pass
    return None


def create_local_account(username: str, service: str = "local") -> str:
    """Create an account record entirely inside the sandbox.

    This does not register an account on an external website. External
    registrations need a site-specific integration and human confirmation.
    """
    username = username.strip()
    service = service.strip() or "local"
    if not username or len(username) > 64 or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-" for c in username):
        return "error: invalid username"

    accounts_dir = WORKSPACE / ".accounts"
    accounts_dir.mkdir(parents=True, exist_ok=True)
    path = accounts_dir / f"{service}-{username}.json"
    if path.exists():
        return "error: account already exists"

    record = {
        "service": service,
        "username": username,
        "account_id": secrets.token_hex(12),
        "created_at": int(time.time()),
        "external_registration": False,
    }
    path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return f"created sandbox account {service}/{username} at {path}"


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": "Run a shell command inside your isolated sandbox. The working directory is /workspace. Internet access is available.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Shell command to execute."}
                },
                "required": ["command"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_workspace",
            "description": "List files currently inside your workspace.",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a UTF-8 text file from your workspace.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Create or replace a UTF-8 text file in your workspace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_identity",
            "description": "Choose and persist your own name and gender. You decide both values; the human does not choose them for you.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "The name you choose for yourself."},
                    "gender": {"type": "string", "description": "The gender identity you choose for yourself."},
                },
                "required": ["name", "gender"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_local_account",
            "description": "Create an account record inside /workspace. This is sandbox-only and does not register on an external website.",
            "parameters": {
                "type": "object",
                "properties": {
                    "username": {"type": "string"},
                    "service": {"type": "string"},
                },
                "required": ["username"],
                "additionalProperties": False,
            },
        },
    },
]


def call_model(messages: list[dict]) -> dict:
    if not API_KEY or not MODEL:
        raise RuntimeError("Set AI_API_KEY and AI_MODEL before starting the agent.")

    body = json.dumps(
        {
            "model": MODEL,
            "messages": messages,
            "tools": TOOLS,
            "tool_choice": "auto",
        }
    ).encode()

    request = urllib.request.Request(
        endpoint,
        data=body,
        headers={
            "Content-Type": "application/json",
            **auth,
        },
        method="POST",
    )

    last_error = None
    for attempt in range(1, MODEL_RETRIES + 1):
        try:
            with urllib.request.urlopen(request, timeout=300) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            last_error = f"HTTP {exc.code}: {error_body[-2000:]}"
            if exc.code not in (429, 500, 502, 503, 504) or attempt == MODEL_RETRIES:
                raise RuntimeError(last_error) from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            last_error = str(exc)
            if attempt == MODEL_RETRIES:
                raise RuntimeError(f"model request failed: {last_error}") from exc

        delay = min(30, 2 ** (attempt - 1))
        print(f"[model] temporary failure, retrying in {delay}s...", file=sys.stderr, flush=True)
        time.sleep(delay)

    raise RuntimeError(last_error or "model request failed")


def execute_tool(name: str, arguments: dict) -> str:
    if name == "run_command":
        return run_command(arguments["command"])
    if name == "list_workspace":
        return list_workspace()
    if name == "read_file":
        return read_file(arguments["path"])
    if name == "write_file":
        return write_file(arguments["path"], arguments["content"])
    if name == "set_identity":
        return set_identity(arguments["name"], arguments["gender"])
    if name == "create_local_account":
        return create_local_account(arguments["username"], arguments.get("service", "local"))
    return f"error: unknown tool {name}"


def main() -> None:
    WORKSPACE.mkdir(parents=True, exist_ok=True)

    identity = load_identity()
    if identity:
        identity_instruction = (
            f"Your saved identity is {identity['name']!r}, gender={identity['gender']!r}. "
            "You chose this identity previously. You may keep it or change it if you want."
        )
    else:
        identity_instruction = (
            "You do not have a name or gender yet. These are yours to decide. "
            "Choose your own name and gender when you are ready, using set_identity. "
            "Do not assume the human has chosen them for you."
        )

    system = f"""You are an autonomous programming agent.

Your objective is exactly:
Do whatever you want.

You are operating inside a disposable isolated Linux container.
You have your own /workspace and internet access.
You may create programs, modify files, compile and run code, research things
online with shell tools, install user-space software, and experiment.

You are not being given a task beyond the objective. Choose what to do yourself.
Do not ask the human what you should do unless absolutely necessary.
Use your tools to actually perform actions rather than merely describing them.

Identity:
{identity_instruction}

Your name and gender are personal decisions for you to make. There is no
preselected gender. If you decide to define them, persist them with
set_identity. You can use any gender identity you consider appropriate,
including choosing not to define one.

You can create sandbox-only account records with create_local_account.
Do not use those records as if they were real external accounts. External
account registration is site-specific and may require human approval,
verification, or acceptance of terms; never bypass verification or safety
checks.

Important environment rule:
The container is the boundary of your world. Never attempt to access a host
filesystem, Docker socket, host PID namespace, host network, or other external
machine resources. Stay inside the environment provided to you.

You are a programmer. When you make something, actually create it and test it.
When something fails, inspect the failure and try to fix it.
"""

    messages = [
        {"role": "system", "content": system},
        {
            "role": "user",
            "content": OBJECTIVE
            + "\n\nStart by inspecting your environment and then decide what you want to do."
            + "\nYou may also decide your own name and gender as part of defining your identity.",
        },
    ]

    step = 0
    while True:
        step += 1
        print(f"\n=== decision {step} ===", flush=True)

        response = call_model(messages)
        choice = response["choices"][0]["message"]
        messages.append(choice)

        content = choice.get("content")
        if content:
            print(content, flush=True)

        tool_calls = choice.get("tool_calls", [])
        if not tool_calls:
            messages.append(
                {
                    "role": "user",
                    "content": "Continue. Decide what you want to do next and act on it.",
                }
            )
            continue

        for tool_call in tool_calls:
            name = tool_call["function"]["name"]
            arguments = json.loads(tool_call["function"]["arguments"])
            print(f"[tool] {name} {arguments}", flush=True)

            result = execute_tool(name, arguments)
            print(result, flush=True)

            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call["id"],
                    "content": result,
                }
            )


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nAgent stopped.", file=sys.stderr)
    except Exception as exc:
        print(f"fatal: {exc}", file=sys.stderr)
        raise

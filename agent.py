#!/usr/bin/env python3
"""Artificial Decision Agent.

The agent has one objective: do whatever it wants.
It can inspect and modify its own sandbox, run programs, and use the internet
through shell tools. The host is not mounted into the container.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path


OBJECTIVE = "Do whatever you want."
WORKSPACE = Path("/workspace")
MODEL = os.environ.get("AI_MODEL", "gemini-3.7-flash")
API_KEY = os.environ.get("AI_API_KEY", "")
BASE_URL = os.environ.get("AI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai").rstrip("/")
MAX_OUTPUT = int(os.environ.get("AI_MAX_OUTPUT", "12000"))
COMMAND_TIMEOUT = int(os.environ.get("COMMAND_TIMEOUT", "120"))


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
            entries.append(("./" + str(rel) + ("/" if path.is_dir() else "")))
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
        f"{BASE_URL}/chat/completions",
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {API_KEY}",
        },
        method="POST",
    )

    with urllib.request.urlopen(request, timeout=300) as response:
        return json.load(response)


def execute_tool(name: str, arguments: dict) -> str:
    if name == "run_command":
        return run_command(arguments["command"])
    if name == "list_workspace":
        return list_workspace()
    if name == "read_file":
        return read_file(arguments["path"])
    if name == "write_file":
        return write_file(arguments["path"], arguments["content"])
    return f"error: unknown tool {name}"


def main() -> None:
    WORKSPACE.mkdir(parents=True, exist_ok=True)

    system = """You are an autonomous programming agent named Ada.

Your objective is exactly:
Do whatever you want.

You are operating inside a disposable isolated Linux container.
You have your own /workspace and internet access.
You may create programs, modify files, compile and run code, research things
online with shell tools, install user-space software, and experiment.

You are not being given a task beyond the objective. Choose what to do yourself.
Do not ask the human what you should do unless absolutely necessary.
Use your tools to actually perform actions rather than merely describing them.

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
            + "\n\nStart by inspecting your environment and then decide what you want to do.",
        },
    ]

    step = 0
    while True:
        step += 1
        print(f"\\n=== decision {step} ===", flush=True)

        response = call_model(messages)
        choice = response["choices"][0]["message"]
        messages.append(choice)

        content = choice.get("content")
        if content:
            print(content, flush=True)

        tool_calls = choice.get("tool_calls", [])
        if not tool_calls:
            # Give her another turn so a temporary lack of tool calls does not
            # accidentally end the experiment.
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

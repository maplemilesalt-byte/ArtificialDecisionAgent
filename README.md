# ArtificialDecisionAgent

An autonomous AI that decides what it is going to do.

## Objective

The agent starts with one objective:

> Do whatever you want.

She can program, create files, compile and run programs, inspect her workspace,
and use the internet from inside her sandbox.

## Architecture

```
AI
 |
 v
Docker container
 |-- /workspace
 |-- shell
 |-- compiler/toolchain
 \`-- internet
```

The container has no bind mounts, no Docker socket, no host networking, and no
host PID namespace.

## Configuration

The API key is provided through a local `.env` file in the **root of this
repository**.

Create this file:

```text
.env
```

with:

```env
AI_API_KEY=your_api_key_here
AI_MODEL=your_model_name
# AI_BASE_URL=https://api.openai.com/v1
```

The file should be located at:

```text
ArtificialDecisionAgent/
├── .env              <-- put the API key here
├── agent.py
├── Dockerfile
└── docker-compose.yml
```

**Do not commit `.env` to Git.** It is already included in `.gitignore`, so Git
will ignore it automatically.

The API key is passed from `.env` into the container as the `AI_API_KEY`
environment variable. `agent.py` reads that environment variable.

## Run

After creating `.env`:

```bash
docker compose build
docker compose run --rm agent
```

The workspace is disposable by default. Nothing from the host is mounted into
the container.

## What she can do

The first version gives her four tools:

- `run_command`
- `list_workspace`
- `read_file`
- `write_file`

That is enough for her to write programs, compile them, run them, inspect
failures, and iterate.

More capabilities can be added later without giving her access to the host.

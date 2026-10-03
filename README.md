# 🐙 Octo MCP

**Give AI agents access to Octo Browser profiles and browser actions.**

Start a profile, connect over CDP, interact with pages and collect results through one MCP server.

## ⚡ What it does

- 🗂️ **Profiles** — find, start and stop profiles; create temporary sessions.
- 🌐 **Browser actions** — navigate, click, type, switch tabs and take screenshots.
- 📄 **Page data** — read text, HTML and attributes, or run JavaScript.
- 🔌 **Integrations** — Octo Local API, Cloud API and Playwright over CDP.

## 🔧 Built for integration

- **37 MCP tools**, exposed over stdio.
- **Async API clients** with bounded retries for HTTP 429 responses.
- **Remote browser support** with configurable host and CDP endpoint rewriting.
- **Checks in CI** for linting, types and tests.

## 🚀 Quick start

**Requires Python 3.10+ and a running Octo Browser installation.**

```bash
git clone https://github.com/mazamaka/octo-mcp.git
cd octo-mcp
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

Connect your MCP client using **stdio** and the absolute path to `.venv/bin/octo-mcp`. On Windows, use `.venv/Scripts/octo-mcp.exe`.

For Claude Code on macOS / Linux, from the project directory:

```bash
claude mcp add octo-mcp -- "$PWD/.venv/bin/octo-mcp"
```

Start with **“Check whether Octo Browser is running”** (`octo_health_check`). Profile search and team resources use the Cloud API: configure `OCTO_API_TOKEN` in your MCP client's environment. Local operations use the running desktop app.

**[Configuration & all tools →](docs/reference.md)**

## 🧪 Development

The CI workflow runs **Ruff, mypy and pytest**. Run the same checks locally:

```bash
pip install -e ".[dev]"
ruff check src/ tests/
ruff format --check src/ tests/
mypy src/ tests/
pytest
```

---

**Python · MCP · Playwright · httpx**

**[MIT license](LICENSE)** · Built by **[Maksym Babenko](https://github.com/mazamaka)**

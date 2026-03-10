<div align="center">

# Octo Browser MCP Server

**Control antidetect browser profiles with AI through the Model Context Protocol**

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-3776AB.svg?logo=python&logoColor=white)](https://www.python.org/downloads/)
[![MCP](https://img.shields.io/badge/MCP-Compatible-8A2BE2.svg?logo=anthropic&logoColor=white)](https://modelcontextprotocol.io/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Octo Browser](https://img.shields.io/badge/Octo_Browser-API-FF6B35.svg)](https://octobrowser.net/)
[![Playwright](https://img.shields.io/badge/Playwright-CDP-2EAD33.svg?logo=playwright&logoColor=white)](https://playwright.dev/)

[Installation](#installation) · [Quick Start](#quick-start) · [Tools Reference](#tools-reference-34-tools) · [Examples](#usage-examples) · [Architecture](#architecture)

</div>

---

## Why This Exists

Managing hundreds of antidetect browser profiles manually is tedious. This MCP server bridges **Octo Browser** and **AI assistants** (Claude Code, Cursor, etc.), enabling natural language control over browser profiles and full browser automation through CDP.

Instead of clicking through UIs or writing scripts, just tell your AI:

> *"Start profile 5249_US, go to google.com, and take a screenshot"*

The AI handles the rest -- finding the profile, launching it, connecting via CDP, navigating, and capturing the result.

## Key Features

- **Profile Lifecycle** -- Start, stop, find, and manage Octo Browser profiles via Local and Cloud APIs
- **Browser Automation** -- Full Playwright-based control: navigate, click, type, scroll, screenshot
- **Dual API Support** -- Local API (port 58888) for profile control + Cloud API for search and management
- **One-Time Profiles** -- Temporary profiles that self-destruct after use (ideal for scraping)
- **Multi-Tab Control** -- Open, switch, and close browser tabs programmatically
- **Remote/Docker Ready** -- Automatic WebSocket URL rewriting for non-localhost setups
- **Rate Limit Handling** -- Built-in retry with exponential backoff for API throttling

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                   AI Assistant                       │
│              (Claude Code / Cursor)                  │
└──────────────────────┬──────────────────────────────┘
                       │ MCP Protocol (stdio)
┌──────────────────────▼──────────────────────────────┐
│              octo-mcp Server                         │
│  ┌─────────────┐ ┌──────────────┐ ┌──────────────┐  │
│  │   server.py  │ │ octo_client  │ │browser_manager│ │
│  │  34 MCP Tools│ │  Local+Cloud │ │  Playwright   │ │
│  └──────┬───────┘ └──────┬───────┘ └──────┬───────┘  │
└─────────┼────────────────┼────────────────┼──────────┘
          │                │                │
    ┌─────▼────┐   ┌──────▼──────┐  ┌──────▼──────┐
    │ MCP SDK  │   │  Octo APIs   │  │  CDP / WS   │
    │  stdio   │   │ :58888 Cloud │  │  Playwright │
    └──────────┘   └──────┬───────┘  └──────┬──────┘
                          │                 │
                   ┌──────▼─────────────────▼──────┐
                   │        Octo Browser           │
                   │   (antidetect Chromium)        │
                   └───────────────────────────────┘
```

## Installation

### From Source

```bash
git clone https://github.com/mazamaka/octo-mcp.git
cd octo-mcp
pip install -e .
playwright install chromium
```

### From PyPI (coming soon)

```bash
pip install octo-mcp
playwright install chromium
```

### Prerequisites

- **Python 3.10+**
- **Octo Browser** installed and running ([download](https://octobrowser.net/))
- **Playwright Chromium** (installed via `playwright install chromium`)

## Quick Start

### 1. Add to Claude Code

```bash
# Minimal setup (Local API only -- start/stop profiles by UUID)
claude mcp add octo-mcp -- octo-mcp

# Full setup (+ Cloud API for searching profiles by name)
claude mcp add octo-mcp \
  -e OCTO_USERNAME="your@email.com" \
  -e OCTO_PASSWORD="your_password" \
  -e OCTO_API_TOKEN="your_api_token" \
  -- octo-mcp
```

### 2. Or add to `.claude/settings.json` manually

```json
{
  "mcpServers": {
    "octo-mcp": {
      "command": "octo-mcp",
      "env": {
        "OCTO_USERNAME": "your@email.com",
        "OCTO_PASSWORD": "your_password",
        "OCTO_API_TOKEN": "your_api_token"
      }
    }
  }
}
```

### 3. Restart Claude Code and verify

Ask Claude: *"Check if Octo Browser is running"* -- it will use `octo_health_check`.

### Getting Your API Token

1. Open Octo Browser app
2. Go to **Settings** → **API**
3. Copy your API token

> The API token is only needed for Cloud API operations (searching profiles by name, managing tags/proxies/extensions). Basic profile start/stop works without it.

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `OCTO_HOST` | Octo Browser host (for remote/Docker setups) | `localhost` |
| `OCTO_PORT` | Local API port | `58888` |
| `OCTO_USERNAME` | Account email for auto-login | -- |
| `OCTO_PASSWORD` | Account password for auto-login | -- |
| `OCTO_API_TOKEN` | Cloud API token (for search, tags, proxies) | -- |

## Tools Reference (34 tools)

### Profile Management (Local API)

| Tool | Description |
|------|-------------|
| `octo_health_check` | Check Octo Browser API availability and version |
| `octo_list_profiles` | List all active (running) profiles with their WebSocket endpoints |
| `octo_start_profile` | Start a profile by UUID; returns `ws_endpoint` for CDP connection |
| `octo_stop_profile` | Gracefully or forcefully stop a running profile |
| `octo_start_one_time_profile` | Create a temporary profile (auto-deleted on stop); supports OS selection |

### Profile Search & Management (Cloud API)

| Tool | Description |
|------|-------------|
| `octo_find_profile_by_name` | Find a profile by exact or partial name match |
| `octo_start_profile_by_name` | Find profile by name and start it (combines find + start) |
| `octo_search_profiles` | Search profiles by name, tags, status; supports sorting and pagination |
| `octo_get_profile` | Get full profile data: fingerprint, proxy, extensions, tags |

### Team Resources (Cloud API)

| Tool | Description |
|------|-------------|
| `octo_get_extensions` | List all team browser extensions (name, version, UUID) |
| `octo_delete_extensions` | Delete team extensions by UUID |
| `octo_get_tags` | List all profile tags (name, color, UUID) |
| `octo_get_proxies` | List all saved proxies (type, host, port, UUID) |

### Browser Connection

| Tool | Description |
|------|-------------|
| `browser_connect` | Connect to a running profile via CDP WebSocket endpoint |
| `browser_disconnect` | Disconnect from browser (does not stop the Octo profile) |

### Navigation

| Tool | Description |
|------|-------------|
| `browser_navigate` | Navigate to URL with configurable wait strategy (`load`, `domcontentloaded`, `networkidle`) |
| `browser_get_url` | Get the current page URL |
| `browser_go_back` | Navigate back in history |
| `browser_go_forward` | Navigate forward in history |
| `browser_reload` | Reload the current page |

### Page Interaction

| Tool | Description |
|------|-------------|
| `browser_click` | Click by CSS selector or (x, y) coordinates; supports right-click, double-click |
| `browser_type` | Type text into an element (via `fill`) or simulate keystrokes with delay |
| `browser_press_key` | Press a keyboard key (`Enter`, `Tab`, `Escape`, `ArrowDown`, etc.) |
| `browser_scroll` | Scroll page or specific element in any direction |
| `browser_hover` | Hover over an element (useful for dropdowns and tooltips) |
| `browser_select` | Select an option in a `<select>` dropdown |

### Information Extraction

| Tool | Description |
|------|-------------|
| `browser_screenshot` | Capture screenshot of full page or specific element (returns PNG image) |
| `browser_get_text` | Extract text content from an element |
| `browser_get_html` | Get innerHTML or outerHTML of element, or full page HTML |
| `browser_get_attribute` | Get any attribute value from an element |
| `browser_query_selector_all` | Find all matching elements with their tag, text, class, bounds |
| `browser_wait_for_selector` | Wait for element to appear/disappear with configurable timeout |

### JavaScript Execution

| Tool | Description |
|------|-------------|
| `browser_evaluate` | Execute arbitrary JavaScript and return the result |

### Tab Management

| Tool | Description |
|------|-------------|
| `browser_list_tabs` | List all open tabs with title, URL, and active status |
| `browser_switch_tab` | Switch to a tab by index |
| `browser_new_tab` | Open a new tab, optionally navigating to a URL |
| `browser_close_tab` | Close the current tab |

## Usage Examples

### Start a profile by name and automate

```
You: Start profile "work_US" and check my IP on whatismyipaddress.com

Claude: I'll start the profile, connect to it, and check your IP.

→ octo_start_profile_by_name(name="work_US")
  Profile 'work_US' (uuid: abc-123) started. ws_endpoint: ws://localhost:52341/...

→ browser_connect(ws_endpoint="ws://localhost:52341/...")
  Connected to browser.

→ browser_navigate(url="https://whatismyipaddress.com")
  Navigated to https://whatismyipaddress.com

→ browser_screenshot()
  [Screenshot showing IP address]

Your IP is 192.168.x.x (US location, matching profile proxy).
```

### Scrape with a temporary profile

```
You: Create a temp profile and scrape the title from news.ycombinator.com

Claude:
→ octo_start_one_time_profile(os="win")
  Temporary profile created. UUID: tmp-456. ws_endpoint: ws://...

→ browser_connect(ws_endpoint="ws://...")
→ browser_navigate(url="https://news.ycombinator.com")
→ browser_evaluate(script="document.title")
  Result: "Hacker News"

→ octo_stop_profile(uuid="tmp-456")
  Profile stopped and deleted.

The page title is "Hacker News".
```

### Manage profiles in bulk

```
You: Find all profiles tagged "ads" and list them

Claude:
→ octo_search_profiles(tags=["ads"], limit=50)
  Found 12 profiles:
  - ads_US_01 (UUID: ...)
  - ads_UK_02 (UUID: ...)
  ...
```

### Check fingerprint configuration

```
You: Show me the fingerprint details for profile "5249_US"

Claude:
→ octo_find_profile_by_name(name="5249_US")
→ octo_get_profile(uuid="found-uuid")

  Profile: 5249_US
  Fingerprint:
    OS: win
    User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64)...
    Screen: 1920x1080
  Proxy: socks5://proxy.example.com:1080
  Extensions (2):
    - uBlock Origin v1.55
    - EditThisCookie v1.6
```

## Remote / Docker Setup

When Octo Browser runs on a different machine, set `OCTO_HOST`:

```bash
claude mcp add octo-mcp \
  -e OCTO_HOST="192.168.1.100" \
  -e OCTO_USERNAME="your@email.com" \
  -e OCTO_PASSWORD="your_password" \
  -- octo-mcp
```

The server automatically rewrites WebSocket URLs from `127.0.0.1`/`localhost` to your configured host, so CDP connections work seamlessly across networks.

**Requirements for remote setup:**
- Port 58888 (Local API) must be accessible
- CDP debug ports (random, per-profile) must be accessible
- Consider using SSH tunnel for security

## Troubleshooting

| Problem | Solution |
|---------|----------|
| "Octo Browser API unavailable" | Make sure Octo Browser is running. The Local API starts with the app. |
| "OCTO_API_TOKEN is not set" | Add your API token or use `octo_start_profile` with UUID directly. |
| "Profile not found" | Profile names are case-sensitive. Use `octo_search_profiles` to browse. |
| WebSocket connection fails | Check that OCTO_HOST is correct and CDP ports are accessible. |
| "Browser not connected" | Call `browser_connect` with the `ws_endpoint` from profile start. |

## Development

```bash
git clone https://github.com/mazamaka/octo-mcp.git
cd octo-mcp
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Lint & format
ruff check src/
ruff format src/

# Run tests
pytest
```

## Tech Stack

- **[MCP SDK](https://github.com/modelcontextprotocol/python-sdk)** -- Model Context Protocol server framework
- **[Playwright](https://playwright.dev/python/)** -- Browser automation via CDP (Chrome DevTools Protocol)
- **[httpx](https://www.python-httpx.org/)** -- Async HTTP client for Octo Browser APIs
- **[Hatchling](https://hatch.pypa.io/)** -- Modern Python build system

## License

MIT License -- see [LICENSE](LICENSE) for details.

## Author

**Maksym Babenko** -- [GitHub](https://github.com/mazamaka) · [Telegram](https://t.me/Mazamaka)

## Links

- [Octo Browser](https://octobrowser.net/) -- Antidetect browser for multi-accounting
- [Octo Browser API Docs](https://docs.octobrowser.net/)
- [Model Context Protocol](https://modelcontextprotocol.io/) -- Open protocol for AI-tool integration
- [Claude Code](https://docs.anthropic.com/en/docs/claude-code)

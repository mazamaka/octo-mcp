# Octo Browser MCP Server

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)

MCP (Model Context Protocol) server for [Octo Browser](https://octobrowser.net/) - an antidetect browser for multi-accounting. This server enables AI assistants like Claude to control Octo Browser profiles through natural language.

## Features

- **Profile Management**: Start, stop, and list Octo Browser profiles
- **Search by Name**: Find profiles by name using Cloud API (requires API token)
- **One-Time Profiles**: Create temporary profiles that are deleted after use
- **Browser Automation**: Full Playwright-based browser control via CDP
- **Screenshot Capture**: Take screenshots of pages or elements
- **Multi-Tab Support**: Manage multiple browser tabs
- **Docker Compatible**: Works with Octo Browser running in Docker or remote hosts

## Installation

### From PyPI

```bash
pip install octo-mcp
```

### From Source

```bash
git clone https://github.com/anthropics/octo-mcp.git
cd octo-mcp
pip install -e .
```

### Install Playwright

```bash
playwright install chromium
```

## Configuration

### Environment Variables

| Variable | Description | Required | Default |
|----------|-------------|----------|---------|
| `OCTO_HOST` | Octo Browser host | No | `localhost` |
| `OCTO_PORT` | Local API port | No | `58888` |
| `OCTO_USERNAME` | Octo account email (for auto-login) | No | - |
| `OCTO_PASSWORD` | Octo account password | No | - |
| `OCTO_API_TOKEN` | Cloud API token (for profile search by name) | No | - |

### Getting Your API Token

1. Open Octo Browser
2. Go to **Settings** → **API**
3. Copy your API token

The API token is only needed for searching profiles by name. Basic profile operations work without it.

## Usage with Claude Code

### Add the MCP Server

```bash
# Basic setup (Local API only)
claude mcp add octo-mcp -- python -m octo_mcp.server

# With authentication (recommended)
claude mcp add octo-mcp \
  -e OCTO_USERNAME="your@email.com" \
  -e OCTO_PASSWORD="your_password" \
  -- python -m octo_mcp.server

# Full setup with Cloud API (enables search by profile name)
claude mcp add octo-mcp \
  -e OCTO_USERNAME="your@email.com" \
  -e OCTO_PASSWORD="your_password" \
  -e OCTO_API_TOKEN="your_api_token" \
  -- python -m octo_mcp.server
```

### Restart Claude Code

After adding the MCP server, restart Claude Code to load the new tools.

## Available Tools

### Profile Management

| Tool | Description |
|------|-------------|
| `octo_health_check` | Check if Octo Browser is running |
| `octo_list_profiles` | List active (running) profiles |
| `octo_start_profile` | Start a profile by UUID |
| `octo_stop_profile` | Stop a running profile |
| `octo_start_one_time_profile` | Create and start a temporary profile |

### Profile Search (requires API token)

| Tool | Description |
|------|-------------|
| `octo_find_profile_by_name` | Find profile by exact name |
| `octo_start_profile_by_name` | Find and start profile by name |
| `octo_search_profiles` | Search profiles by name or tags |

### Browser Connection

| Tool | Description |
|------|-------------|
| `browser_connect` | Connect to a running profile via CDP |
| `browser_disconnect` | Disconnect from browser |

### Navigation

| Tool | Description |
|------|-------------|
| `browser_navigate` | Go to URL |
| `browser_get_url` | Get current URL |
| `browser_go_back` | Navigate back |
| `browser_go_forward` | Navigate forward |
| `browser_reload` | Reload page |

### Interaction

| Tool | Description |
|------|-------------|
| `browser_click` | Click element or coordinates |
| `browser_type` | Type text into element |
| `browser_press_key` | Press keyboard key (Enter, Tab, etc.) |
| `browser_scroll` | Scroll page or element |
| `browser_hover` | Hover over element |
| `browser_select` | Select option in dropdown |

### Information Extraction

| Tool | Description |
|------|-------------|
| `browser_screenshot` | Take screenshot (returns image) |
| `browser_get_text` | Get element text content |
| `browser_get_html` | Get page or element HTML |
| `browser_get_attribute` | Get element attribute |
| `browser_query_selector_all` | Find all matching elements |
| `browser_wait_for_selector` | Wait for element to appear |

### JavaScript

| Tool | Description |
|------|-------------|
| `browser_evaluate` | Execute JavaScript and return result |

### Tab Management

| Tool | Description |
|------|-------------|
| `browser_list_tabs` | List open tabs |
| `browser_switch_tab` | Switch to tab by index |
| `browser_new_tab` | Open new tab |
| `browser_close_tab` | Close current tab |

## Example Conversation

```
User: Start my profile "work_account" and go to google.com

Claude: I'll start the profile and navigate to Google.

[Uses octo_start_profile_by_name with name="work_account"]
Profile 'work_account' started.
ws_endpoint: ws://localhost:52341/devtools/browser/abc123

[Uses browser_connect with the ws_endpoint]
Connected to browser.

[Uses browser_navigate with url="https://google.com"]
Navigated to https://google.com

[Uses browser_screenshot]
[Shows screenshot of Google homepage]

The profile is now running and showing Google's homepage.
```

## Docker / Remote Setup

If Octo Browser runs on a different host (e.g., in Docker), set the `OCTO_HOST` variable:

```bash
claude mcp add octo-mcp \
  -e OCTO_HOST="192.168.1.100" \
  -e OCTO_USERNAME="your@email.com" \
  -e OCTO_PASSWORD="your_password" \
  -- python -m octo_mcp.server
```

The server automatically rewrites WebSocket URLs from `127.0.0.1` to the configured host.

## Troubleshooting

### "Octo Browser API unavailable"

Make sure Octo Browser is running. The Local API starts automatically when you open the application.

### "OCTO_API_TOKEN is not set"

This error appears when using `octo_find_profile_by_name` or `octo_search_profiles` without an API token. Either:
1. Add your API token to the MCP configuration
2. Use `octo_start_profile` with UUID instead (get UUID from Octo Browser UI)

### "Profile not found"

The profile name must match exactly (case-sensitive). Use `octo_search_profiles` to find available profiles.

### WebSocket connection fails

If running Octo Browser on a different host:
1. Make sure port 58888 is accessible
2. The CDP port (random for each profile) must be accessible
3. Set `OCTO_HOST` to the correct IP address

## Development

### Setup

```bash
git clone https://github.com/anthropics/octo-mcp.git
cd octo-mcp
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### Run Tests

```bash
pytest
```

### Code Style

```bash
ruff check .
ruff format .
```

## License

MIT License - see [LICENSE](LICENSE) file.

## Links

- [Octo Browser](https://octobrowser.net/)
- [Octo Browser API Documentation](https://octobrowser.net/api)
- [Model Context Protocol](https://modelcontextprotocol.io/)
- [Claude Code](https://claude.ai/code)

# 🧰 Configuration & tool reference


| Variable | Description | Default |
|----------|-------------|---------|
| `OCTO_HOST` | Octo Browser host (for remote/Docker setups) | `localhost` |
| `OCTO_PORT` | Local API port | `58888` |
| `OCTO_USERNAME` | Account email for auto-login | -- |
| `OCTO_PASSWORD` | Account password for auto-login | -- |
| `OCTO_API_TOKEN` | Cloud API token (for search, tags, proxies) | -- |
| `OCTO_API_URL` | Cloud API base URL -- set it to a [mirror](https://documenter.getpostman.com/view/1801428/UVC6i6eA) if your provider blocks the main host | `https://app.octobrowser.net/api/v2/automation` |
| `OCTO_LOG_LEVEL` | Server log level (`DEBUG`, `INFO`, `WARNING`, ...); logs go to stderr | `WARNING` |


## MCP tools


### Profile Management (Local API)

| Tool | Description |
|------|-------------|
| `octo_health_check` | Check Octo Browser API availability and version |
| `octo_list_profiles` | List all active (running) profiles with their WebSocket endpoints |
| `octo_start_profile` | Start a profile by UUID; returns `ws_endpoint` for CDP connection. Accepts a profile `password` |
| `octo_stop_profile` | Gracefully or forcefully stop a running profile |
| `octo_start_one_time_profile` | Create a temporary profile (auto-deleted on stop); supports OS selection |

### Profile Search & Management (Cloud API)

| Tool | Description |
|------|-------------|
| `octo_find_profile_by_name` | Find a profile by title (the API matches from the start of the title) |
| `octo_start_profile_by_name` | Find profile by title and start it (combines find + start) |
| `octo_search_profiles` | Search profiles by title prefix, tags, status; supports sorting and pagination |
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
| `browser_navigate` | Navigate to URL with configurable wait strategy (`load`, `domcontentloaded`, `networkidle`, `commit`) |
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


## Remote Octo Browser

Set `OCTO_HOST` to the machine running Octo Browser. The client rewrites localhost CDP endpoints to that host. The Local API port and the profile's CDP port must both be reachable; use a private network or SSH tunnel.

## Troubleshooting

- **Connection refused:** check that Octo Browser is running and `OCTO_HOST` / `OCTO_PORT` point to its Local API.
- **Cloud API denied:** check `OCTO_API_TOKEN`, permissions and the API access available to your Octo account.
- **CDP connection fails:** verify that the profile is running and its WebSocket port is reachable.
- **Need diagnostics:** set `OCTO_LOG_LEVEL=DEBUG`; server logs go to stderr, separate from MCP messages.

#!/usr/bin/env python3
"""
Octo Browser MCP server.

Exposes Octo Browser profile management (local + cloud API) and Playwright/CDP
browser automation as MCP tools, so an AI assistant can drive antidetect profiles.

Tool schemas are derived from the function signatures below: parameter
descriptions come from Field(description=...), allowed values from Literal, and
each tool's description from its docstring.
"""

import json
import logging
import os
import sys
from typing import Annotated, Any, Literal

from mcp.server import MCPServer
from mcp.server.mcpserver import Image
from pydantic import Field

from . import __version__
from .browser_manager import BrowserManager
from .octo_client import OctoCloudClient, OctoLocalClient, extract_ws_endpoint

logger = logging.getLogger("octo_mcp.server")

# Configuration from environment variables
OCTO_HOST = os.getenv("OCTO_HOST", "localhost")
OCTO_PORT = int(os.getenv("OCTO_PORT", "58888"))
OCTO_USERNAME = os.getenv("OCTO_USERNAME", "")
OCTO_PASSWORD = os.getenv("OCTO_PASSWORD", "")
OCTO_API_TOKEN = os.getenv("OCTO_API_TOKEN", "")

LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")

# Truncate huge pages so a single tool call cannot blow up the context
MAX_HTML_CHARS = 50_000

# Repeated parameter annotations
Selector = Annotated[str, Field(description="CSS selector of the element")]
OptionalSelector = Annotated[
    str | None, Field(description="CSS selector of the element (optional)")
]
Headless = Annotated[bool, Field(description="Run without a GUI")]
ProfilePassword = Annotated[
    str | None, Field(description="Profile password, if the profile is protected")
]

octo_client: OctoLocalClient | None = None
octo_cloud_client: OctoCloudClient | None = None
browser_manager: BrowserManager | None = None


def get_octo_client() -> OctoLocalClient:
    """Get the local API client."""
    global octo_client
    if octo_client is None:
        octo_client = OctoLocalClient(
            host=OCTO_HOST,
            port=OCTO_PORT,
            username=OCTO_USERNAME or None,
            password=OCTO_PASSWORD or None,
        )
    return octo_client


def get_browser_manager() -> BrowserManager:
    """Get the Playwright browser manager."""
    global browser_manager
    if browser_manager is None:
        browser_manager = BrowserManager()
    return browser_manager


def get_octo_cloud_client() -> OctoCloudClient:
    """Get the cloud API client (profile search and management)."""
    global octo_cloud_client
    if octo_cloud_client is None:
        octo_cloud_client = OctoCloudClient(api_token=OCTO_API_TOKEN or None)
    return octo_cloud_client


def _log_level() -> Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]:
    """Log level from the environment, falling back to WARNING."""
    level = os.getenv("OCTO_LOG_LEVEL", "WARNING").upper()
    if level not in LOG_LEVELS:
        return "WARNING"
    return level  # type: ignore[return-value]


server = MCPServer(
    "octo-mcp",
    version=__version__,
    instructions=(
        "Control Octo Browser antidetect profiles: start and stop them through the local "
        "API, search and inspect them through the cloud API, then drive the running "
        "browser over CDP. Typical flow: octo_start_profile (or octo_start_profile_by_name) "
        "-> browser_connect with the returned ws_endpoint -> browser_* tools."
    ),
    log_level=_log_level(),
)


# === Profile management (local API) ===


@server.tool()
async def octo_health_check() -> str:
    """Check that the Octo Browser API is reachable. Call this first to verify the app is running."""
    client = get_octo_client()
    if not await client.health_check():
        return (
            f"Octo Browser API is unavailable at {client.base_url}. "
            "Make sure Octo Browser is running."
        )
    version = await client.get_version()
    return (
        "Octo Browser API is available.\n"
        f"Version: {version.get('current', 'unknown')} (latest: {version.get('latest', 'unknown')})"
    )


@server.tool()
async def octo_list_profiles() -> str:
    """List the profiles currently running on this machine, with UUID, title and ws_endpoint."""
    profiles = await get_octo_client().get_active_profiles()
    if not profiles:
        return "No running profiles."

    lines = ["Running profiles:"]
    for p in profiles:
        lines.append(f"- UUID: {p.get('uuid', 'N/A')}")
        lines.append(f"  Title: {p.get('title', p.get('name', 'N/A'))}")
        lines.append(f"  ws_endpoint: {extract_ws_endpoint(p) or 'N/A'}")
        lines.append("")
    return "\n".join(lines)


@server.tool()
async def octo_start_profile(
    uuid: Annotated[str, Field(description="Octo Browser profile UUID")],
    headless: Headless = False,
    password: ProfilePassword = None,
) -> str:
    """Start a profile by UUID and return the ws_endpoint for the CDP connection.

    If the profile is already running, its current data is returned instead.
    """
    result = await get_octo_client().get_or_start_profile(
        uuid=uuid, headless=headless, password=password
    )
    return _format_started(uuid, result)


@server.tool()
async def octo_stop_profile(
    uuid: Annotated[str, Field(description="UUID of the profile to stop")],
    force: Annotated[
        bool, Field(description="Force stop (use when a graceful stop does not work)")
    ] = False,
) -> str:
    """Stop a running Octo Browser profile by UUID."""
    client = get_octo_client()
    if force:
        await client.force_stop_profile(uuid)
    else:
        await client.stop_profile(uuid)
    return f"Profile {uuid} stopped."


@server.tool()
async def octo_start_one_time_profile(
    os: Annotated[  # noqa: A002 - the schema field is named "os"
        Literal["win", "mac", "lin", "android"], Field(description="Fingerprint OS")
    ] = "win",
    headless: Headless = False,
) -> str:
    """Create and start a one-time (temporary) profile.

    It is removed once stopped and starts faster than a regular profile, which suits scraping.
    """
    result = await get_octo_client().start_one_time_profile(fingerprint_os=os, headless=headless)
    return (
        f"One-time profile started.\n"
        f"UUID: {result.get('uuid', 'N/A')}\n"
        f"ws_endpoint: {extract_ws_endpoint(result)}\n\n"
        "Pass this ws_endpoint to browser_connect. The profile is deleted when stopped."
    )


# === Profile search and management (cloud API) ===


@server.tool()
async def octo_find_profile_by_name(
    name: Annotated[str, Field(description="Profile title to look for (e.g. '5249_US')")],
    exact_match: Annotated[bool, Field(description="Require an exact title match")] = True,
) -> str:
    """Find a profile by title. The API matches from the beginning of the title.

    Requires OCTO_API_TOKEN.
    """
    profile = await get_octo_cloud_client().find_profile_by_name(name, exact_match=exact_match)
    if not profile:
        return f"No profile titled '{name}' was found."
    return (
        f"Profile found:\n"
        f"- UUID: {profile.get('uuid')}\n"
        f"- Title: {profile.get('title')}\n"
        f"- Status: {profile.get('status', 'N/A')}\n"
        f"- Tags: {profile.get('tags', [])}"
    )


@server.tool()
async def octo_start_profile_by_name(
    name: Annotated[
        str, Field(description="Title of the profile to find and start (e.g. '5249_US')")
    ],
    headless: Headless = False,
    password: ProfilePassword = None,
) -> str:
    """Find a profile by title and start it (find + start in one call). Requires OCTO_API_TOKEN."""
    profile = await get_octo_cloud_client().find_profile_by_name(name, exact_match=True)
    if not profile:
        return f"No profile titled '{name}' was found."

    uuid = profile.get("uuid")
    if not uuid:
        return f"Profile '{name}' has no UUID in the API."

    result = await get_octo_client().get_or_start_profile(
        uuid=uuid, headless=headless, password=password
    )
    return _format_started(f"'{name}' ({uuid})", result)


@server.tool()
async def octo_search_profiles(
    search: Annotated[
        str | None, Field(description="Title prefix (matches from the start of the title)")
    ] = None,
    tags: Annotated[
        list[str] | None,
        Field(description="Tags to filter by; a profile must carry all of them"),
    ] = None,
    limit: Annotated[int, Field(description="Maximum number of results", ge=1)] = 20,
    ordering: Annotated[
        Literal["created", "-created", "active", "-active", "title", "-title"] | None,
        Field(description="Sort order"),
    ] = None,
    status: Annotated[int | None, Field(description="Filter by numeric profile status")] = None,
) -> str:
    """Search profiles by title prefix or tags. Several tags mean AND. Requires OCTO_API_TOKEN."""
    profiles = await get_octo_cloud_client().search_profiles(
        search=search, tags=tags, page_len=limit, ordering=ordering, status=status
    )
    # page_len is snapped to the nearest value the API accepts, so trim here
    profiles = profiles[:limit]

    if not profiles:
        return "No profiles found."

    lines = [f"Profiles found: {len(profiles)}"]
    for p in profiles:
        lines.append(f"- {p.get('title', 'N/A')} (UUID: {p.get('uuid', 'N/A')})")
        if p.get("tags"):
            lines.append(f"  Tags: {', '.join(p['tags'])}")
    return "\n".join(lines)


@server.tool()
async def octo_get_profile(
    uuid: Annotated[str, Field(description="Profile UUID")],
) -> str:
    """Get full profile data by UUID: fingerprint, proxy, extensions, description, tags."""
    return _format_profile(await get_octo_cloud_client().get_profile(uuid), uuid)


# === Team resources (cloud API) ===


@server.tool()
async def octo_get_extensions() -> str:
    """List the team's browser extensions with name, version and UUID."""
    extensions = await get_octo_cloud_client().get_team_extensions()
    if not extensions:
        return "No extensions found."

    lines = [f"Team extensions ({len(extensions)}):"]
    for ext in extensions:
        name = ext.get("name", ext.get("title", "N/A"))
        lines.append(f"- {name} v{ext.get('version', 'N/A')} (UUID: {ext.get('uuid', 'N/A')})")
    return "\n".join(lines)


@server.tool()
async def octo_delete_extensions(
    uuids: Annotated[
        list[str], Field(description="Extension UUIDs to delete (e.g. 'abc123@2.0.12')")
    ],
) -> str:
    """Delete team extensions by UUID.

    Extensions in use by a running profile come back once that profile stops.
    """
    await get_octo_cloud_client().delete_team_extensions(uuids)
    return f"Extensions deleted: {len(uuids)}"


@server.tool()
async def octo_get_tags() -> str:
    """List all profile tags with name, color and UUID."""
    tags = await get_octo_cloud_client().get_tags()
    if not tags:
        return "No tags found."

    lines = [f"Tags ({len(tags)}):"]
    for tag in tags:
        lines.append(
            f"- {tag.get('name', 'N/A')} "
            f"(color: {tag.get('color', 'N/A')}, UUID: {tag.get('uuid', 'N/A')})"
        )
    return "\n".join(lines)


@server.tool()
async def octo_get_proxies() -> str:
    """List all saved proxies with type, host, port and UUID."""
    proxies = await get_octo_cloud_client().get_proxies()
    if not proxies:
        return "No proxies found."

    lines = [f"Proxies ({len(proxies)}):"]
    for p in proxies:
        display = f"{p.get('type', 'N/A')}://{p.get('host', 'N/A')}:{p.get('port', 'N/A')}"
        if p.get("title"):
            display = f"{p['title']} ({display})"
        lines.append(f"- {display} (UUID: {p.get('uuid', 'N/A')})")
    return "\n".join(lines)


# === Browser connection ===


@server.tool()
async def browser_connect(
    ws_endpoint: Annotated[
        str, Field(description="CDP WebSocket endpoint (from octo_start_profile)")
    ],
) -> str:
    """Connect to a running Octo Browser profile over CDP. Call after octo_start_profile."""
    await get_browser_manager().connect(ws_endpoint)
    return f"Connected to the browser at {ws_endpoint}"


@server.tool()
async def browser_disconnect() -> str:
    """Disconnect from the browser (does not stop the Octo profile)."""
    await get_browser_manager().disconnect()
    return "Disconnected from the browser."


# === Navigation ===


@server.tool()
async def browser_navigate(
    url: Annotated[str, Field(description="Target URL")],
    wait_until: Annotated[
        Literal["load", "domcontentloaded", "networkidle", "commit"],
        Field(description="Wait strategy"),
    ] = "domcontentloaded",
) -> str:
    """Navigate to a URL."""
    await get_browser_manager().navigate(url, wait_until=wait_until)
    return f"Navigated to {url}"


@server.tool()
async def browser_get_url() -> str:
    """Get the current page URL."""
    return f"Current URL: {await get_browser_manager().get_url()}"


@server.tool()
async def browser_go_back() -> str:
    """Go back in browser history."""
    await get_browser_manager().go_back()
    return "Went back"


@server.tool()
async def browser_go_forward() -> str:
    """Go forward in browser history."""
    await get_browser_manager().go_forward()
    return "Went forward"


@server.tool()
async def browser_reload() -> str:
    """Reload the current page."""
    await get_browser_manager().reload()
    return "Page reloaded"


# === Interaction ===


@server.tool()
async def browser_click(
    selector: OptionalSelector = None,
    x: Annotated[float | None, Field(description="X coordinate")] = None,
    y: Annotated[float | None, Field(description="Y coordinate")] = None,
    button: Annotated[Literal["left", "right", "middle"], Field(description="Mouse button")] = (
        "left"
    ),
    click_count: Annotated[
        int, Field(description="Number of clicks (2 for a double click)", ge=1)
    ] = 1,
) -> str:
    """Click an element by CSS selector, or click at (x, y) coordinates."""
    manager = get_browser_manager()

    if selector:
        await manager.click(selector=selector, button=button, click_count=click_count)
        return f"Clicked {selector}"
    if x is not None and y is not None:
        await manager.click(x=x, y=y, button=button, click_count=click_count)
        return f"Clicked at ({x}, {y})"
    return "Provide either a selector or (x, y) coordinates"


@server.tool()
async def browser_type(
    text: Annotated[str, Field(description="Text to type")],
    selector: Annotated[
        str | None, Field(description="CSS selector of the input element (optional)")
    ] = None,
    delay: Annotated[
        float, Field(description="Delay between keystrokes in ms (no-selector mode)", ge=0)
    ] = 50,
) -> str:
    """Type text.

    With a selector the value is filled instantly; without one the text is typed
    key by key into the focused element.
    """
    await get_browser_manager().type_text(text, selector=selector, delay=delay)
    return f"Typed: {text if len(text) <= 50 else text[:50] + '...'}"


@server.tool()
async def browser_press_key(
    key: Annotated[str, Field(description="Key name: 'Enter', 'Tab', 'Escape', 'Backspace', ...")],
) -> str:
    """Press a keyboard key (Enter, Tab, Escape, ArrowDown, ...)."""
    await get_browser_manager().press_key(key)
    return f"Key pressed: {key}"


@server.tool()
async def browser_scroll(
    direction: Annotated[
        Literal["up", "down", "left", "right"], Field(description="Scroll direction")
    ] = "down",
    amount: Annotated[int, Field(description="Pixels to scroll")] = 300,
    selector: Annotated[
        str | None, Field(description="CSS selector of the element to scroll (optional)")
    ] = None,
) -> str:
    """Scroll the page, or a specific element when a selector is given."""
    await get_browser_manager().scroll(direction=direction, amount=amount, selector=selector)
    return f"Scrolled {direction} by {amount}px"


@server.tool()
async def browser_hover(selector: Selector) -> str:
    """Hover over an element (useful for dropdowns and tooltips)."""
    await get_browser_manager().hover(selector)
    return f"Hovering over {selector}"


@server.tool()
async def browser_select(
    selector: Annotated[str, Field(description="CSS selector of the select element")],
    value: Annotated[str, Field(description="Value of the option to select")],
) -> str:
    """Select an option in a <select> dropdown."""
    await get_browser_manager().select_option(selector, value)
    return f"Selected {value} in {selector}"


# === Information extraction ===


@server.tool()
async def browser_screenshot(
    selector: Annotated[
        str | None,
        Field(description="CSS selector of the element (optional, else the page)"),
    ] = None,
    full_page: Annotated[bool, Field(description="Capture the whole scrollable page")] = False,
) -> Image:
    """Take a screenshot of the page or of a single element. Returns a PNG."""
    data = await get_browser_manager().screenshot(selector=selector, full_page=full_page)
    return Image(data=data, format="png")


@server.tool()
async def browser_get_text(selector: Selector) -> str:
    """Get the text content of an element."""
    return await get_browser_manager().get_text(selector)


@server.tool()
async def browser_get_html(
    selector: OptionalSelector = None,
    outer: Annotated[bool, Field(description="Include the element's own tag (outerHTML)")] = True,
) -> str:
    """Get the HTML of the page or of an element."""
    html = await get_browser_manager().get_html(selector=selector, outer=outer)
    if len(html) > MAX_HTML_CHARS:
        html = html[:MAX_HTML_CHARS] + "\n... (truncated)"
    return html


@server.tool()
async def browser_get_attribute(
    selector: Selector,
    attribute: Annotated[str, Field(description="Attribute name")],
) -> str:
    """Get an attribute value from an element."""
    return f"{attribute}={await get_browser_manager().get_attribute(selector, attribute)}"


@server.tool()
async def browser_query_selector_all(
    selector: Annotated[str, Field(description="CSS selector")],
) -> str:
    """Find all elements matching a selector and return their metadata."""
    elements = await get_browser_manager().query_selector_all(selector)
    return json.dumps(elements, ensure_ascii=False, indent=2)


@server.tool()
async def browser_wait_for_selector(
    selector: Selector,
    timeout: Annotated[int, Field(description="Timeout in milliseconds", ge=0)] = 30000,
    state: Annotated[
        Literal["attached", "detached", "visible", "hidden"], Field(description="Target state")
    ] = "visible",
) -> str:
    """Wait for an element to reach a given state."""
    await get_browser_manager().wait_for_selector(selector, timeout=timeout, state=state)
    return f"Element {selector} reached state '{state}'"


# === JavaScript ===


@server.tool()
async def browser_evaluate(
    script: Annotated[str, Field(description="JavaScript code to execute")],
) -> str:
    """Run JavaScript on the page and return the result."""
    result = await get_browser_manager().evaluate(script)
    if result is None:
        return "Done (result: null)"
    return f"Result: {json.dumps(result, ensure_ascii=False, indent=2)}"


# === Tabs ===


@server.tool()
async def browser_list_tabs() -> str:
    """List the open tabs with title, URL and active flag."""
    tabs = await get_browser_manager().list_tabs()
    lines = ["Open tabs:"]
    for i, tab in enumerate(tabs):
        marker = " (active)" if tab.get("active") else ""
        lines.append(f"  [{i}] {tab.get('title', 'N/A')}{marker}")
        lines.append(f"      URL: {tab.get('url', 'N/A')}")
    return "\n".join(lines)


@server.tool()
async def browser_switch_tab(
    index: Annotated[int, Field(description="Tab index (zero-based)", ge=0)],
) -> str:
    """Switch to a tab by index."""
    await get_browser_manager().switch_tab(index)
    return f"Switched to tab {index}"


@server.tool()
async def browser_new_tab(
    url: Annotated[str | None, Field(description="URL to open (optional)")] = None,
) -> str:
    """Open a new tab, optionally navigating to a URL."""
    await get_browser_manager().new_tab(url)
    return f"New tab opened{': ' + url if url else ''}"


@server.tool()
async def browser_close_tab() -> str:
    """Close the current tab."""
    await get_browser_manager().close_tab()
    return "Tab closed"


# === Formatting helpers ===


def _format_started(label: str, result: dict[str, Any]) -> str:
    """Render the result of starting a profile."""
    state = "was already running" if result.get("already_running") else "started"
    return (
        f"Profile {label} {state}.\n"
        f"ws_endpoint: {extract_ws_endpoint(result)}\n\n"
        "Pass this ws_endpoint to browser_connect."
    )


def _format_profile(profile: dict[str, Any], uuid: str) -> str:
    """Render full profile data as readable text."""
    lines = [f"Profile: {profile.get('title', 'N/A')}", f"UUID: {profile.get('uuid', uuid)}"]

    if profile.get("description"):
        lines.append(f"Description: {profile['description']}")

    tags = profile.get("tags", [])
    if tags:
        tag_names = [t.get("name", t) if isinstance(t, dict) else t for t in tags]
        lines.append(f"Tags: {', '.join(str(t) for t in tag_names)}")

    fp = profile.get("fingerprint") or {}
    if fp:
        lines.append("\nFingerprint:")
        lines.append(f"  OS: {fp.get('os', 'N/A')}")
        # the API returns user_agent; older payloads used useragent
        ua = fp.get("user_agent") or fp.get("useragent")
        if ua:
            lines.append(f"  User-Agent: {ua.get('value', 'auto') if isinstance(ua, dict) else ua}")
        screen = fp.get("screen")
        if screen:
            if isinstance(screen, dict):
                lines.append(f"  Screen: {screen.get('width', '?')}x{screen.get('height', '?')}")
            else:
                lines.append(f"  Screen: {screen}")
        if fp.get("renderer"):
            lines.append(f"  Renderer: {fp['renderer']}")

    proxy = profile.get("proxy") or {}
    if proxy.get("type"):
        lines.append(
            f"\nProxy: {proxy.get('type')}://{proxy.get('host', 'N/A')}:{proxy.get('port', 'N/A')}"
        )

    extensions = profile.get("extensions") or []
    if extensions:
        lines.append(f"\nExtensions ({len(extensions)}):")
        for ext in extensions:
            if isinstance(ext, dict):
                name = ext.get("name", ext.get("title", "N/A"))
                lines.append(f"  - {name} {ext.get('version', '')}".rstrip())
            else:
                lines.append(f"  - {ext}")

    return "\n".join(lines)


def _setup_logging() -> None:
    """Log to stderr -- stdout carries the MCP protocol."""
    logging.basicConfig(
        level=_log_level(),
        stream=sys.stderr,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def main() -> None:
    """Entry point."""
    _setup_logging()
    logger.info("Starting octo-mcp %s (host=%s:%s)", __version__, OCTO_HOST, OCTO_PORT)
    server.run("stdio")


if __name__ == "__main__":
    main()

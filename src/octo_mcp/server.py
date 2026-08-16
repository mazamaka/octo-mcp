#!/usr/bin/env python3
"""
Octo Browser MCP server.

Exposes Octo Browser profile management (local + cloud API) and Playwright/CDP
browser automation as MCP tools, so an AI assistant can drive antidetect profiles.
"""

import asyncio
import base64
import json
import logging
import os
import sys
from typing import Any, Literal, cast

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import (
    ImageContent,
    TextContent,
    Tool,
)

from .browser_manager import BrowserManager
from .octo_client import OctoCloudClient, OctoLocalClient, extract_ws_endpoint

logger = logging.getLogger("octo_mcp.server")

# Configuration from environment variables
OCTO_HOST = os.getenv("OCTO_HOST", "localhost")
OCTO_PORT = int(os.getenv("OCTO_PORT", "58888"))
OCTO_USERNAME = os.getenv("OCTO_USERNAME", "")
OCTO_PASSWORD = os.getenv("OCTO_PASSWORD", "")
OCTO_API_TOKEN = os.getenv("OCTO_API_TOKEN", "")

# Playwright navigation wait strategies
WAIT_UNTIL_STATES = ("load", "domcontentloaded", "networkidle", "commit")
# Playwright element states for wait_for_selector
SELECTOR_STATES = ("attached", "detached", "visible", "hidden")

# Truncate huge pages so a single tool call cannot blow up the context
MAX_HTML_CHARS = 50_000

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


app = Server("octo-mcp")


@app.list_tools()  # type: ignore[no-untyped-call, untyped-decorator]
async def list_tools() -> list[Tool]:
    """List the tools exposed by this server."""
    return [
        # === Profile management (local API) ===
        Tool(
            name="octo_health_check",
            description=(
                "Check that the Octo Browser API is reachable. Call this first to verify "
                "the app is running."
            ),
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
        Tool(
            name="octo_list_profiles",
            description=(
                "List the profiles currently running on this machine. Shows UUID, title "
                "and ws_endpoint for each."
            ),
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
        Tool(
            name="octo_start_profile",
            description=(
                "Start an Octo Browser profile by UUID. Returns the ws_endpoint for the CDP "
                "connection. If the profile is already running, returns its current data."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "uuid": {
                        "type": "string",
                        "description": "Octo Browser profile UUID",
                    },
                    "headless": {
                        "type": "boolean",
                        "description": "Run without a GUI",
                        "default": False,
                    },
                    "password": {
                        "type": "string",
                        "description": "Profile password, if the profile is protected",
                    },
                },
                "required": ["uuid"],
            },
        ),
        Tool(
            name="octo_stop_profile",
            description="Stop a running Octo Browser profile by UUID.",
            inputSchema={
                "type": "object",
                "properties": {
                    "uuid": {
                        "type": "string",
                        "description": "UUID of the profile to stop",
                    },
                    "force": {
                        "type": "boolean",
                        "description": "Force stop (use when a graceful stop does not work)",
                        "default": False,
                    },
                },
                "required": ["uuid"],
            },
        ),
        Tool(
            name="octo_start_one_time_profile",
            description=(
                "Create and start a one-time (temporary) profile. It is removed once stopped "
                "and starts faster than a regular profile, which suits scraping."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "os": {
                        "type": "string",
                        "description": "Fingerprint OS: 'win', 'mac', 'lin' or 'android'",
                        "default": "win",
                    },
                    "headless": {
                        "type": "boolean",
                        "description": "Run without a GUI",
                        "default": False,
                    },
                },
            },
        ),
        Tool(
            name="octo_find_profile_by_name",
            description=(
                "Find a profile by title using the cloud API. The search matches from the "
                "beginning of the title. Requires OCTO_API_TOKEN."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Profile title to look for (e.g. '5249_US')",
                    },
                    "exact_match": {
                        "type": "boolean",
                        "description": "Require an exact title match",
                        "default": True,
                    },
                },
                "required": ["name"],
            },
        ),
        Tool(
            name="octo_start_profile_by_name",
            description=(
                "Find a profile by title and start it (find + start in one call). "
                "Requires OCTO_API_TOKEN."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Title of the profile to find and start (e.g. '5249_US')",
                    },
                    "headless": {
                        "type": "boolean",
                        "description": "Run without a GUI",
                        "default": False,
                    },
                    "password": {
                        "type": "string",
                        "description": "Profile password, if the profile is protected",
                    },
                },
                "required": ["name"],
            },
        ),
        Tool(
            name="octo_search_profiles",
            description=(
                "Search profiles by title prefix or tags using the cloud API. Several tags "
                "mean AND. Requires OCTO_API_TOKEN."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "search": {
                        "type": "string",
                        "description": "Title prefix (matches from the start of the title)",
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Tags to filter by; a profile must carry all of them",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of results",
                        "default": 20,
                    },
                    "ordering": {
                        "type": "string",
                        "description": (
                            "Sort order: 'created', '-created', 'active', '-active', "
                            "'title', '-title'"
                        ),
                    },
                    "status": {
                        "type": "integer",
                        "description": "Filter by numeric profile status",
                    },
                },
            },
        ),
        Tool(
            name="octo_get_profile",
            description=(
                "Get full profile data by UUID: fingerprint, proxy, extensions, description, "
                "tags. Uses the cloud API."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "uuid": {
                        "type": "string",
                        "description": "Profile UUID",
                    },
                },
                "required": ["uuid"],
            },
        ),
        Tool(
            name="octo_get_extensions",
            description="List the team's browser extensions with name, version and UUID.",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
        Tool(
            name="octo_delete_extensions",
            description=(
                "Delete team extensions by UUID. Extensions in use by a running profile come "
                "back once that profile stops."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "uuids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Extension UUIDs to delete (e.g. 'abc123@2.0.12')",
                    },
                },
                "required": ["uuids"],
            },
        ),
        Tool(
            name="octo_get_tags",
            description="List all profile tags with name, color and UUID.",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
        Tool(
            name="octo_get_proxies",
            description="List all saved proxies with type, host, port and UUID.",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
        # === Browser connection ===
        Tool(
            name="browser_connect",
            description=(
                "Connect to a running Octo Browser profile over CDP. Call after octo_start_profile."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "ws_endpoint": {
                        "type": "string",
                        "description": "CDP WebSocket endpoint (from octo_start_profile)",
                    },
                },
                "required": ["ws_endpoint"],
            },
        ),
        Tool(
            name="browser_disconnect",
            description="Disconnect from the browser (does not stop the Octo profile).",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
        # === Navigation ===
        Tool(
            name="browser_navigate",
            description="Navigate to a URL.",
            inputSchema={
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "Target URL",
                    },
                    "wait_until": {
                        "type": "string",
                        "enum": list(WAIT_UNTIL_STATES),
                        "description": "Wait strategy",
                        "default": "domcontentloaded",
                    },
                },
                "required": ["url"],
            },
        ),
        Tool(
            name="browser_get_url",
            description="Get the current page URL.",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
        Tool(
            name="browser_go_back",
            description="Go back in browser history.",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
        Tool(
            name="browser_go_forward",
            description="Go forward in browser history.",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
        Tool(
            name="browser_reload",
            description="Reload the current page.",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
        # === Interaction ===
        Tool(
            name="browser_click",
            description="Click an element by CSS selector, or click at (x, y) coordinates.",
            inputSchema={
                "type": "object",
                "properties": {
                    "selector": {
                        "type": "string",
                        "description": "CSS selector of the element",
                    },
                    "x": {
                        "type": "number",
                        "description": "X coordinate",
                    },
                    "y": {
                        "type": "number",
                        "description": "Y coordinate",
                    },
                    "button": {
                        "type": "string",
                        "enum": ["left", "right", "middle"],
                        "description": "Mouse button",
                        "default": "left",
                    },
                    "click_count": {
                        "type": "integer",
                        "description": "Number of clicks (2 for a double click)",
                        "default": 1,
                    },
                },
            },
        ),
        Tool(
            name="browser_type",
            description=(
                "Type text. With a selector the value is filled instantly; without one the "
                "text is typed key by key into the focused element."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "Text to type",
                    },
                    "selector": {
                        "type": "string",
                        "description": "CSS selector of the input element (optional)",
                    },
                    "delay": {
                        "type": "number",
                        "description": "Delay between keystrokes in ms (no-selector mode)",
                        "default": 50,
                    },
                },
                "required": ["text"],
            },
        ),
        Tool(
            name="browser_press_key",
            description="Press a keyboard key (Enter, Tab, Escape, ArrowDown, ...).",
            inputSchema={
                "type": "object",
                "properties": {
                    "key": {
                        "type": "string",
                        "description": "Key name: 'Enter', 'Tab', 'Escape', 'Backspace', ...",
                    },
                },
                "required": ["key"],
            },
        ),
        Tool(
            name="browser_scroll",
            description="Scroll the page, or a specific element when a selector is given.",
            inputSchema={
                "type": "object",
                "properties": {
                    "direction": {
                        "type": "string",
                        "enum": ["up", "down", "left", "right"],
                        "description": "Scroll direction",
                        "default": "down",
                    },
                    "amount": {
                        "type": "number",
                        "description": "Pixels to scroll",
                        "default": 300,
                    },
                    "selector": {
                        "type": "string",
                        "description": "CSS selector of the element to scroll (optional)",
                    },
                },
            },
        ),
        Tool(
            name="browser_hover",
            description="Hover over an element (useful for dropdowns and tooltips).",
            inputSchema={
                "type": "object",
                "properties": {
                    "selector": {
                        "type": "string",
                        "description": "CSS selector of the element",
                    },
                },
                "required": ["selector"],
            },
        ),
        Tool(
            name="browser_select",
            description="Select an option in a <select> dropdown.",
            inputSchema={
                "type": "object",
                "properties": {
                    "selector": {
                        "type": "string",
                        "description": "CSS selector of the select element",
                    },
                    "value": {
                        "type": "string",
                        "description": "Value of the option to select",
                    },
                },
                "required": ["selector", "value"],
            },
        ),
        # === Information extraction ===
        Tool(
            name="browser_screenshot",
            description="Take a screenshot of the page or of a single element. Returns a PNG.",
            inputSchema={
                "type": "object",
                "properties": {
                    "selector": {
                        "type": "string",
                        "description": "CSS selector of the element (optional, else the page)",
                    },
                    "full_page": {
                        "type": "boolean",
                        "description": "Capture the whole scrollable page",
                        "default": False,
                    },
                },
            },
        ),
        Tool(
            name="browser_get_text",
            description="Get the text content of an element.",
            inputSchema={
                "type": "object",
                "properties": {
                    "selector": {
                        "type": "string",
                        "description": "CSS selector of the element",
                    },
                },
                "required": ["selector"],
            },
        ),
        Tool(
            name="browser_get_html",
            description="Get the HTML of the page or of an element.",
            inputSchema={
                "type": "object",
                "properties": {
                    "selector": {
                        "type": "string",
                        "description": "CSS selector of the element (optional)",
                    },
                    "outer": {
                        "type": "boolean",
                        "description": "Include the element's own tag (outerHTML)",
                        "default": True,
                    },
                },
            },
        ),
        Tool(
            name="browser_get_attribute",
            description="Get an attribute value from an element.",
            inputSchema={
                "type": "object",
                "properties": {
                    "selector": {
                        "type": "string",
                        "description": "CSS selector of the element",
                    },
                    "attribute": {
                        "type": "string",
                        "description": "Attribute name",
                    },
                },
                "required": ["selector", "attribute"],
            },
        ),
        Tool(
            name="browser_query_selector_all",
            description="Find all elements matching a selector and return their metadata.",
            inputSchema={
                "type": "object",
                "properties": {
                    "selector": {
                        "type": "string",
                        "description": "CSS selector",
                    },
                },
                "required": ["selector"],
            },
        ),
        Tool(
            name="browser_wait_for_selector",
            description="Wait for an element to reach a given state.",
            inputSchema={
                "type": "object",
                "properties": {
                    "selector": {
                        "type": "string",
                        "description": "CSS selector of the element",
                    },
                    "timeout": {
                        "type": "number",
                        "description": "Timeout in milliseconds",
                        "default": 30000,
                    },
                    "state": {
                        "type": "string",
                        "enum": list(SELECTOR_STATES),
                        "description": "Target state",
                        "default": "visible",
                    },
                },
                "required": ["selector"],
            },
        ),
        # === JavaScript ===
        Tool(
            name="browser_evaluate",
            description="Run JavaScript on the page and return the result.",
            inputSchema={
                "type": "object",
                "properties": {
                    "script": {
                        "type": "string",
                        "description": "JavaScript code to execute",
                    },
                },
                "required": ["script"],
            },
        ),
        # === Tabs ===
        Tool(
            name="browser_list_tabs",
            description="List the open tabs with title, URL and active flag.",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
        Tool(
            name="browser_switch_tab",
            description="Switch to a tab by index.",
            inputSchema={
                "type": "object",
                "properties": {
                    "index": {
                        "type": "integer",
                        "description": "Tab index (zero-based)",
                    },
                },
                "required": ["index"],
            },
        ),
        Tool(
            name="browser_new_tab",
            description="Open a new tab, optionally navigating to a URL.",
            inputSchema={
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "URL to open (optional)",
                    },
                },
            },
        ),
        Tool(
            name="browser_close_tab",
            description="Close the current tab.",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
    ]


@app.call_tool()  # type: ignore[untyped-decorator]
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent | ImageContent]:
    """Dispatch a tool call, reporting failures as text instead of crashing."""
    logger.info("Tool call: %s %s", name, arguments)
    try:
        return await _handle_tool(name, arguments)
    except Exception as e:
        logger.exception("Tool %s failed", name)
        return [TextContent(type="text", text=f"Error ({type(e).__name__}): {e}")]


async def _handle_tool(name: str, args: dict[str, Any]) -> list[TextContent | ImageContent]:
    """Tool implementations."""
    client = get_octo_client()
    manager = get_browser_manager()

    # === Profile management ===

    if name == "octo_health_check":
        if await client.health_check():
            version = await client.get_version()
            current = version.get("current", "unknown")
            latest = version.get("latest", "unknown")
            return [
                TextContent(
                    type="text",
                    text=f"Octo Browser API is available.\nVersion: {current} (latest: {latest})",
                )
            ]
        return [
            TextContent(
                type="text",
                text=(
                    f"Octo Browser API is unavailable at {client.base_url}. "
                    "Make sure Octo Browser is running."
                ),
            )
        ]

    if name == "octo_list_profiles":
        profiles = await client.get_active_profiles()
        if not profiles:
            return [TextContent(type="text", text="No running profiles.")]

        lines = ["Running profiles:"]
        for p in profiles:
            lines.append(f"- UUID: {p.get('uuid', 'N/A')}")
            lines.append(f"  Title: {p.get('title', p.get('name', 'N/A'))}")
            lines.append(f"  ws_endpoint: {extract_ws_endpoint(p) or 'N/A'}")
            lines.append("")
        return [TextContent(type="text", text="\n".join(lines))]

    if name == "octo_start_profile":
        uuid = args["uuid"]
        result = await client.get_or_start_profile(
            uuid=uuid,
            headless=args.get("headless", False),
            password=args.get("password"),
        )
        return [TextContent(type="text", text=_format_started(uuid, result))]

    if name == "octo_stop_profile":
        uuid = args["uuid"]
        if args.get("force", False):
            await client.force_stop_profile(uuid)
        else:
            await client.stop_profile(uuid)
        return [TextContent(type="text", text=f"Profile {uuid} stopped.")]

    if name == "octo_start_one_time_profile":
        result = await client.start_one_time_profile(
            fingerprint_os=args.get("os", "win"),
            headless=args.get("headless", False),
        )
        return [
            TextContent(
                type="text",
                text=(
                    f"One-time profile started.\n"
                    f"UUID: {result.get('uuid', 'N/A')}\n"
                    f"ws_endpoint: {extract_ws_endpoint(result)}\n\n"
                    "Pass this ws_endpoint to browser_connect. "
                    "The profile is deleted when stopped."
                ),
            )
        ]

    if name == "octo_find_profile_by_name":
        cloud = get_octo_cloud_client()
        profile_name = args["name"]
        profile = await cloud.find_profile_by_name(
            profile_name, exact_match=args.get("exact_match", True)
        )

        if profile:
            return [
                TextContent(
                    type="text",
                    text=(
                        f"Profile found:\n"
                        f"- UUID: {profile.get('uuid')}\n"
                        f"- Title: {profile.get('title')}\n"
                        f"- Status: {profile.get('status', 'N/A')}\n"
                        f"- Tags: {profile.get('tags', [])}"
                    ),
                )
            ]
        return [TextContent(type="text", text=f"No profile titled '{profile_name}' was found.")]

    if name == "octo_start_profile_by_name":
        cloud = get_octo_cloud_client()
        profile_name = args["name"]

        profile = await cloud.find_profile_by_name(profile_name, exact_match=True)
        if not profile:
            return [TextContent(type="text", text=f"No profile titled '{profile_name}' was found.")]

        uuid = profile.get("uuid")
        if not uuid:
            return [
                TextContent(type="text", text=f"Profile '{profile_name}' has no UUID in the API.")
            ]

        result = await client.get_or_start_profile(
            uuid=uuid,
            headless=args.get("headless", False),
            password=args.get("password"),
        )
        return [
            TextContent(type="text", text=_format_started(f"'{profile_name}' ({uuid})", result))
        ]

    if name == "octo_search_profiles":
        cloud = get_octo_cloud_client()
        limit = args.get("limit", 20)

        profiles = await cloud.search_profiles(
            search=args.get("search"),
            tags=args.get("tags"),
            page_len=limit,
            ordering=args.get("ordering"),
            status=args.get("status"),
        )
        # page_len is snapped to the nearest value the API accepts, so trim here
        profiles = profiles[:limit]

        if not profiles:
            return [TextContent(type="text", text="No profiles found.")]

        lines = [f"Profiles found: {len(profiles)}"]
        for p in profiles:
            lines.append(f"- {p.get('title', 'N/A')} (UUID: {p.get('uuid', 'N/A')})")
            if p.get("tags"):
                lines.append(f"  Tags: {', '.join(p['tags'])}")
        return [TextContent(type="text", text="\n".join(lines))]

    if name == "octo_get_profile":
        cloud = get_octo_cloud_client()
        uuid = args["uuid"]
        profile = await cloud.get_profile(uuid)
        return [TextContent(type="text", text=_format_profile(profile, uuid))]

    if name == "octo_get_extensions":
        cloud = get_octo_cloud_client()
        extensions = await cloud.get_team_extensions()

        if not extensions:
            return [TextContent(type="text", text="No extensions found.")]

        lines = [f"Team extensions ({len(extensions)}):"]
        for ext in extensions:
            ext_name = ext.get("name", ext.get("title", "N/A"))
            lines.append(
                f"- {ext_name} v{ext.get('version', 'N/A')} (UUID: {ext.get('uuid', 'N/A')})"
            )
        return [TextContent(type="text", text="\n".join(lines))]

    if name == "octo_delete_extensions":
        cloud = get_octo_cloud_client()
        uuids = args["uuids"]
        await cloud.delete_team_extensions(uuids)
        return [TextContent(type="text", text=f"Extensions deleted: {len(uuids)}")]

    if name == "octo_get_tags":
        cloud = get_octo_cloud_client()
        tags = await cloud.get_tags()

        if not tags:
            return [TextContent(type="text", text="No tags found.")]

        lines = [f"Tags ({len(tags)}):"]
        for tag in tags:
            lines.append(
                f"- {tag.get('name', 'N/A')} "
                f"(color: {tag.get('color', 'N/A')}, UUID: {tag.get('uuid', 'N/A')})"
            )
        return [TextContent(type="text", text="\n".join(lines))]

    if name == "octo_get_proxies":
        cloud = get_octo_cloud_client()
        proxies = await cloud.get_proxies()

        if not proxies:
            return [TextContent(type="text", text="No proxies found.")]

        lines = [f"Proxies ({len(proxies)}):"]
        for p in proxies:
            display = f"{p.get('type', 'N/A')}://{p.get('host', 'N/A')}:{p.get('port', 'N/A')}"
            title = p.get("title", "")
            if title:
                display = f"{title} ({display})"
            lines.append(f"- {display} (UUID: {p.get('uuid', 'N/A')})")
        return [TextContent(type="text", text="\n".join(lines))]

    # === Browser connection ===

    if name == "browser_connect":
        ws_endpoint = args["ws_endpoint"]
        await manager.connect(ws_endpoint)
        return [TextContent(type="text", text=f"Connected to the browser at {ws_endpoint}")]

    if name == "browser_disconnect":
        await manager.disconnect()
        return [TextContent(type="text", text="Disconnected from the browser.")]

    # === Navigation ===

    if name == "browser_navigate":
        url = args["url"]
        wait_until = args.get("wait_until", "domcontentloaded")
        if wait_until not in WAIT_UNTIL_STATES:
            raise ValueError(
                f"Invalid wait_until '{wait_until}'. Allowed: {', '.join(WAIT_UNTIL_STATES)}"
            )
        await manager.navigate(
            url,
            wait_until=cast(
                Literal["commit", "domcontentloaded", "load", "networkidle"], wait_until
            ),
        )
        return [TextContent(type="text", text=f"Navigated to {url}")]

    if name == "browser_get_url":
        return [TextContent(type="text", text=f"Current URL: {await manager.get_url()}")]

    if name == "browser_go_back":
        await manager.go_back()
        return [TextContent(type="text", text="Went back")]

    if name == "browser_go_forward":
        await manager.go_forward()
        return [TextContent(type="text", text="Went forward")]

    if name == "browser_reload":
        await manager.reload()
        return [TextContent(type="text", text="Page reloaded")]

    # === Interaction ===

    if name == "browser_click":
        selector = args.get("selector")
        x = args.get("x")
        y = args.get("y")
        button = args.get("button", "left")
        click_count = args.get("click_count", 1)

        if selector:
            await manager.click(selector=selector, button=button, click_count=click_count)
            return [TextContent(type="text", text=f"Clicked {selector}")]
        if x is not None and y is not None:
            await manager.click(x=x, y=y, button=button, click_count=click_count)
            return [TextContent(type="text", text=f"Clicked at ({x}, {y})")]
        return [TextContent(type="text", text="Provide either a selector or (x, y) coordinates")]

    if name == "browser_type":
        text = args["text"]
        await manager.type_text(text, selector=args.get("selector"), delay=args.get("delay", 50))
        preview = text if len(text) <= 50 else f"{text[:50]}..."
        return [TextContent(type="text", text=f"Typed: {preview}")]

    if name == "browser_press_key":
        key = args["key"]
        await manager.press_key(key)
        return [TextContent(type="text", text=f"Key pressed: {key}")]

    if name == "browser_scroll":
        direction = args.get("direction", "down")
        amount = args.get("amount", 300)
        await manager.scroll(direction=direction, amount=amount, selector=args.get("selector"))
        return [TextContent(type="text", text=f"Scrolled {direction} by {amount}px")]

    if name == "browser_hover":
        selector = args["selector"]
        await manager.hover(selector)
        return [TextContent(type="text", text=f"Hovering over {selector}")]

    if name == "browser_select":
        selector = args["selector"]
        value = args["value"]
        await manager.select_option(selector, value)
        return [TextContent(type="text", text=f"Selected {value} in {selector}")]

    # === Information extraction ===

    if name == "browser_screenshot":
        screenshot_bytes = await manager.screenshot(
            selector=args.get("selector"), full_page=args.get("full_page", False)
        )
        return [
            ImageContent(
                type="image",
                data=base64.b64encode(screenshot_bytes).decode("utf-8"),
                mimeType="image/png",
            )
        ]

    if name == "browser_get_text":
        return [TextContent(type="text", text=await manager.get_text(args["selector"]))]

    if name == "browser_get_html":
        html = await manager.get_html(selector=args.get("selector"), outer=args.get("outer", True))
        if len(html) > MAX_HTML_CHARS:
            html = html[:MAX_HTML_CHARS] + "\n... (truncated)"
        return [TextContent(type="text", text=html)]

    if name == "browser_get_attribute":
        attribute = args["attribute"]
        value = await manager.get_attribute(args["selector"], attribute)
        return [TextContent(type="text", text=f"{attribute}={value}")]

    if name == "browser_query_selector_all":
        elements = await manager.query_selector_all(args["selector"])
        return [TextContent(type="text", text=json.dumps(elements, ensure_ascii=False, indent=2))]

    if name == "browser_wait_for_selector":
        selector = args["selector"]
        state = args.get("state", "visible")
        if state not in SELECTOR_STATES:
            raise ValueError(f"Invalid state '{state}'. Allowed: {', '.join(SELECTOR_STATES)}")
        await manager.wait_for_selector(
            selector,
            timeout=args.get("timeout", 30000),
            state=cast(Literal["attached", "detached", "visible", "hidden"], state),
        )
        return [TextContent(type="text", text=f"Element {selector} reached state '{state}'")]

    # === JavaScript ===

    if name == "browser_evaluate":
        result = await manager.evaluate(args["script"])
        if result is None:
            return [TextContent(type="text", text="Done (result: null)")]
        return [
            TextContent(
                type="text", text=f"Result: {json.dumps(result, ensure_ascii=False, indent=2)}"
            )
        ]

    # === Tabs ===

    if name == "browser_list_tabs":
        tabs = await manager.list_tabs()
        lines = ["Open tabs:"]
        for i, tab in enumerate(tabs):
            marker = " (active)" if tab.get("active") else ""
            lines.append(f"  [{i}] {tab.get('title', 'N/A')}{marker}")
            lines.append(f"      URL: {tab.get('url', 'N/A')}")
        return [TextContent(type="text", text="\n".join(lines))]

    if name == "browser_switch_tab":
        index = args["index"]
        await manager.switch_tab(index)
        return [TextContent(type="text", text=f"Switched to tab {index}")]

    if name == "browser_new_tab":
        url = args.get("url")
        await manager.new_tab(url)
        return [TextContent(type="text", text=f"New tab opened{': ' + url if url else ''}")]

    if name == "browser_close_tab":
        await manager.close_tab()
        return [TextContent(type="text", text="Tab closed")]

    return [TextContent(type="text", text=f"Unknown tool: {name}")]


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
                ext_name = ext.get("name", ext.get("title", "N/A"))
                lines.append(f"  - {ext_name} {ext.get('version', '')}".rstrip())
            else:
                lines.append(f"  - {ext}")

    return "\n".join(lines)


def _setup_logging() -> None:
    """Log to stderr -- stdout carries the MCP protocol."""
    logging.basicConfig(
        level=os.getenv("OCTO_LOG_LEVEL", "WARNING").upper(),
        stream=sys.stderr,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


async def run_server() -> None:
    """Run the MCP server over stdio."""
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


def main() -> None:
    """Entry point."""
    _setup_logging()
    logger.info("Starting octo-mcp (host=%s:%s)", OCTO_HOST, OCTO_PORT)
    asyncio.run(run_server())


if __name__ == "__main__":
    main()

"""Tests for the MCP server surface.

Tool schemas are generated from the function signatures, so these tests guard
the contract clients depend on: tool names, required arguments and enums.
"""

from __future__ import annotations

import base64
from typing import Any

import pytest
from mcp.types import CallToolResult, ImageContent, TextContent

from octo_mcp import server as srv

EXPECTED_TOOLS = {
    "octo_health_check",
    "octo_list_profiles",
    "octo_start_profile",
    "octo_stop_profile",
    "octo_start_one_time_profile",
    "octo_find_profile_by_name",
    "octo_start_profile_by_name",
    "octo_search_profiles",
    "octo_get_profile",
    "octo_get_extensions",
    "octo_delete_extensions",
    "octo_get_tags",
    "octo_get_proxies",
    "browser_connect",
    "browser_disconnect",
    "browser_navigate",
    "browser_get_url",
    "browser_go_back",
    "browser_go_forward",
    "browser_reload",
    "browser_click",
    "browser_type",
    "browser_press_key",
    "browser_scroll",
    "browser_hover",
    "browser_select",
    "browser_screenshot",
    "browser_get_text",
    "browser_get_html",
    "browser_get_attribute",
    "browser_query_selector_all",
    "browser_wait_for_selector",
    "browser_evaluate",
    "browser_list_tabs",
    "browser_switch_tab",
    "browser_new_tab",
    "browser_close_tab",
}


async def schemas() -> dict[str, dict[str, Any]]:
    """Tool name -> input schema."""
    return {t.name: t.input_schema for t in await srv.server.list_tools()}


async def test_every_tool_is_registered() -> None:
    """The full tool surface, so a renamed function cannot silently drop a tool."""
    assert set(await schemas()) == EXPECTED_TOOLS


async def test_tools_are_described() -> None:
    """Clients pick tools by description -- none may be empty."""
    for tool in await srv.server.list_tools():
        assert tool.description, tool.name


async def test_required_arguments() -> None:
    """Required arguments come from parameters without defaults."""
    s = await schemas()
    assert s["octo_start_profile"]["required"] == ["uuid"]
    assert s["browser_navigate"]["required"] == ["url"]
    assert s["browser_get_attribute"]["required"] == ["selector", "attribute"]
    assert "required" not in s["octo_health_check"]


async def test_enums_reach_the_schema() -> None:
    """Literal annotations must surface as enums, not free-form strings."""
    s = await schemas()
    assert s["browser_navigate"]["properties"]["wait_until"]["enum"] == [
        "load",
        "domcontentloaded",
        "networkidle",
        "commit",
    ]
    assert s["browser_click"]["properties"]["button"]["enum"] == ["left", "right", "middle"]
    assert s["octo_start_one_time_profile"]["properties"]["os"]["enum"] == [
        "win",
        "mac",
        "lin",
        "android",
    ]


async def test_parameters_are_documented() -> None:
    """Every argument carries a description for the model to read."""
    for name, schema in (await schemas()).items():
        for arg, spec in schema.get("properties", {}).items():
            assert spec.get("description"), f"{name}.{arg}"


async def test_tool_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    """A call reaches the client layer and comes back as text."""

    class FakeLocal:
        async def get_active_profiles(self) -> list[dict[str, Any]]:
            return [{"uuid": "abc", "title": "work_US", "ws_endpoint": "ws://host/x"}]

    monkeypatch.setattr(srv, "get_octo_client", FakeLocal)
    result = await srv.server.call_tool("octo_list_profiles", {})

    assert isinstance(result, CallToolResult)
    assert result.is_error is False
    block = result.content[0]
    assert isinstance(block, TextContent)
    assert "abc" in block.text
    assert "ws://host/x" in block.text


async def test_screenshot_returns_image(monkeypatch: pytest.MonkeyPatch) -> None:
    """The screenshot tool must produce an image block, not base64 text."""
    png = b"\x89PNG\r\n\x1a\n"

    class FakeManager:
        async def screenshot(self, selector: str | None, full_page: bool) -> bytes:
            return png

    monkeypatch.setattr(srv, "get_browser_manager", FakeManager)
    result = await srv.server.call_tool("browser_screenshot", {})

    assert isinstance(result, CallToolResult)
    block = result.content[0]
    assert isinstance(block, ImageContent)
    assert block.mime_type == "image/png"
    assert base64.b64decode(block.data) == png


async def test_invalid_enum_is_rejected() -> None:
    """Bad arguments fail in the SDK, before any browser work starts."""
    from mcp.server.mcpserver.exceptions import ToolError

    with pytest.raises(ToolError):
        await srv.server.call_tool("browser_navigate", {"url": "u", "wait_until": "nope"})

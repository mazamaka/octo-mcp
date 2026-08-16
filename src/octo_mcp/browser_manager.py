"""
Browser Manager -- Playwright CDP integration for Octo Browser.

Connects to Octo Browser profiles via Chrome DevTools Protocol (CDP)
and provides a high-level API for page interaction, navigation,
screenshot capture, and JavaScript execution.
"""

from __future__ import annotations

from typing import Any, Literal

from playwright.async_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    async_playwright,
)


class BrowserManager:
    """Manages browser connection and interaction through Playwright CDP.

    Connects to an Octo Browser profile via its WebSocket debug endpoint
    and exposes methods for navigation, clicking, typing, screenshots, etc.

    Usage:
        manager = BrowserManager()
        await manager.connect("ws://localhost:12345/devtools/browser/abc")
        await manager.navigate("https://example.com")
        screenshot = await manager.screenshot()
        await manager.disconnect()
    """

    def __init__(self) -> None:
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None
        self._ws_endpoint: str | None = None

    @property
    def is_connected(self) -> bool:
        """Check if browser is connected via CDP."""
        return self._browser is not None and self._browser.is_connected()

    async def _ensure_connected(self) -> None:
        """Raise if browser is not connected."""
        if not self.is_connected:
            raise ConnectionError("Browser not connected. Use browser_connect first.")

    async def _get_page(self) -> Page:
        """Get the current active page, creating one if needed."""
        await self._ensure_connected()
        assert self._browser is not None

        if self._page is None or self._page.is_closed():
            contexts = self._browser.contexts
            if contexts:
                self._context = contexts[0]
                pages = self._context.pages
                if pages:
                    self._page = pages[0]
                else:
                    self._page = await self._context.new_page()
            else:
                self._context = await self._browser.new_context()
                self._page = await self._context.new_page()
        return self._page

    # === Connection ===

    async def connect(self, ws_endpoint: str) -> None:
        """Connect to browser via CDP WebSocket endpoint.

        Args:
            ws_endpoint: WebSocket URL from Octo Browser profile start response.
        """
        if self.is_connected:
            await self.disconnect()

        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.connect_over_cdp(ws_endpoint)
        self._ws_endpoint = ws_endpoint

        # Attach to existing context and page if available
        contexts = self._browser.contexts
        if contexts:
            self._context = contexts[0]
            pages = self._context.pages
            if pages:
                self._page = pages[0]

    async def disconnect(self) -> None:
        """Disconnect from browser without closing the Octo profile."""
        if self._browser:
            try:
                await self._browser.close()
            except Exception:  # noqa: BLE001, S110
                pass  # Best-effort close
            self._browser = None
            self._context = None
            self._page = None

        if self._playwright:
            await self._playwright.stop()
            self._playwright = None

    # === Navigation ===

    async def navigate(
        self,
        url: str,
        wait_until: Literal["commit", "domcontentloaded", "load", "networkidle"] = (
            "domcontentloaded"
        ),
    ) -> None:
        """Navigate to a URL.

        Args:
            url: Target URL.
            wait_until: Wait strategy -- 'load', 'domcontentloaded', 'networkidle'
                or 'commit'.
        """
        page = await self._get_page()
        await page.goto(url, wait_until=wait_until)

    async def get_url(self) -> str:
        """Get the current page URL."""
        page = await self._get_page()
        return page.url

    async def go_back(self) -> None:
        """Navigate back in browser history."""
        page = await self._get_page()
        await page.go_back()

    async def go_forward(self) -> None:
        """Navigate forward in browser history."""
        page = await self._get_page()
        await page.go_forward()

    async def reload(self) -> None:
        """Reload the current page."""
        page = await self._get_page()
        await page.reload()

    # === Interaction ===

    async def click(
        self,
        selector: str | None = None,
        x: float | None = None,
        y: float | None = None,
        button: Literal["left", "right", "middle"] = "left",
        click_count: int = 1,
    ) -> None:
        """Click on an element or coordinates.

        Args:
            selector: CSS selector for the target element.
            x: X coordinate for positional click.
            y: Y coordinate for positional click.
            button: Mouse button -- 'left', 'right', or 'middle'.
            click_count: Number of clicks (2 for double-click).
        """
        page = await self._get_page()

        if selector:
            await page.click(selector, button=button, click_count=click_count)
        elif x is not None and y is not None:
            await page.mouse.click(x, y, button=button, click_count=click_count)
        else:
            raise ValueError("Provide either selector or (x, y) coordinates")

    async def type_text(
        self,
        text: str,
        selector: str | None = None,
        delay: float = 50,
    ) -> None:
        """Type text into an element or the page.

        When selector is provided, uses `fill()` for instant input.
        Without selector, simulates keystroke-by-keystroke typing.

        Args:
            text: Text to type.
            selector: CSS selector of the input element.
            delay: Delay between keystrokes in milliseconds (no-selector mode).
        """
        page = await self._get_page()

        if selector:
            await page.fill(selector, text)
        else:
            await page.keyboard.type(text, delay=delay)

    async def press_key(self, key: str) -> None:
        """Press a keyboard key.

        Args:
            key: Key name -- 'Enter', 'Tab', 'Escape', 'Backspace', 'ArrowDown', etc.
        """
        page = await self._get_page()
        await page.keyboard.press(key)

    async def scroll(
        self,
        direction: str = "down",
        amount: int = 300,
        selector: str | None = None,
    ) -> None:
        """Scroll the page or a specific element.

        Args:
            direction: Scroll direction -- 'up', 'down', 'left', 'right'.
            amount: Number of pixels to scroll.
            selector: CSS selector of the element to scroll (scrolls page if omitted).
        """
        page = await self._get_page()

        delta_x = 0
        delta_y = 0

        if direction == "down":
            delta_y = amount
        elif direction == "up":
            delta_y = -amount
        elif direction == "right":
            delta_x = amount
        elif direction == "left":
            delta_x = -amount

        if selector:
            element = await page.query_selector(selector)
            if element is None:
                raise ValueError(f"Element not found: {selector}")
            # The wheel event goes to whatever is under the cursor, so move the
            # mouse onto the element first -- otherwise the page scrolls instead.
            await element.scroll_into_view_if_needed()
            box = await element.bounding_box()
            if box:
                await page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
            await page.mouse.wheel(delta_x, delta_y)
        else:
            await page.mouse.wheel(delta_x, delta_y)

    async def hover(self, selector: str) -> None:
        """Hover over an element.

        Args:
            selector: CSS selector of the target element.
        """
        page = await self._get_page()
        await page.hover(selector)

    async def select_option(self, selector: str, value: str) -> None:
        """Select an option in a dropdown.

        Args:
            selector: CSS selector of the <select> element.
            value: Value of the option to select.
        """
        page = await self._get_page()
        await page.select_option(selector, value)

    # === Information Extraction ===

    async def screenshot(
        self,
        selector: str | None = None,
        full_page: bool = False,
    ) -> bytes:
        """Capture a screenshot.

        Args:
            selector: CSS selector to screenshot a specific element.
            full_page: Capture the entire scrollable page.

        Returns:
            PNG image bytes.
        """
        page = await self._get_page()

        if selector:
            element = await page.query_selector(selector)
            if element:
                return await element.screenshot()
            raise ValueError(f"Element not found: {selector}")

        return await page.screenshot(full_page=full_page)

    async def get_text(self, selector: str) -> str:
        """Get the text content of an element.

        Args:
            selector: CSS selector of the element.

        Returns:
            Inner text of the element.
        """
        page = await self._get_page()
        element = await page.query_selector(selector)
        if element:
            return await element.inner_text()
        raise ValueError(f"Element not found: {selector}")

    async def get_html(
        self,
        selector: str | None = None,
        outer: bool = True,
    ) -> str:
        """Get HTML content of the page or an element.

        Args:
            selector: CSS selector (returns full page HTML if omitted).
            outer: Include the element's own tag (outerHTML vs innerHTML).

        Returns:
            HTML string.
        """
        page = await self._get_page()

        if selector:
            element = await page.query_selector(selector)
            if element:
                if outer:
                    return str(await element.evaluate("el => el.outerHTML"))
                return await element.inner_html()
            raise ValueError(f"Element not found: {selector}")

        return await page.content()

    async def get_attribute(self, selector: str, attribute: str) -> str | None:
        """Get an attribute value from an element.

        Args:
            selector: CSS selector of the element.
            attribute: Attribute name to retrieve.

        Returns:
            Attribute value or None.
        """
        page = await self._get_page()
        element = await page.query_selector(selector)
        if element:
            return await element.get_attribute(attribute)
        raise ValueError(f"Element not found: {selector}")

    async def query_selector_all(self, selector: str) -> list[dict[str, Any]]:
        """Find all matching elements and return their metadata.

        Args:
            selector: CSS selector to match.

        Returns:
            List of dicts with index, tag, text, id, class, href, and bounds.
        """
        page = await self._get_page()
        elements = await page.query_selector_all(selector)

        results: list[dict[str, Any]] = []
        for i, el in enumerate(elements):
            try:
                text = await el.inner_text()
                info: dict[str, Any] = {
                    "index": i,
                    "tag": await el.evaluate("el => el.tagName.toLowerCase()"),
                    "text": text[:200] if text else "",
                    "id": await el.get_attribute("id"),
                    "class": await el.get_attribute("class"),
                    "href": await el.get_attribute("href"),
                }
                box = await el.bounding_box()
                if box:
                    info["bounds"] = box
                results.append(info)
            except Exception:  # noqa: BLE001
                results.append({"index": i, "error": "Failed to extract element info"})

        return results

    async def wait_for_selector(
        self,
        selector: str,
        timeout: int = 30000,
        state: Literal["attached", "detached", "visible", "hidden"] = "visible",
    ) -> None:
        """Wait for an element to reach the specified state.

        Args:
            selector: CSS selector of the element.
            timeout: Maximum wait time in milliseconds.
            state: Target state -- 'attached', 'detached', 'visible', 'hidden'.
        """
        page = await self._get_page()
        await page.wait_for_selector(selector, timeout=timeout, state=state)

    # === JavaScript ===

    async def evaluate(self, script: str) -> Any:
        """Execute JavaScript on the page and return the result.

        Args:
            script: JavaScript code to execute.

        Returns:
            The return value of the script (JSON-serializable).
        """
        page = await self._get_page()
        return await page.evaluate(script)

    # === Tab Management ===

    async def list_tabs(self) -> list[dict[str, Any]]:
        """List all open tabs across all contexts.

        Returns:
            List of dicts with title, url, and active flag.
        """
        await self._ensure_connected()
        assert self._browser is not None

        tabs: list[dict[str, Any]] = []
        current_page = self._page

        for context in self._browser.contexts:
            for page in context.pages:
                tabs.append(
                    {
                        "title": await page.title(),
                        "url": page.url,
                        "active": page == current_page,
                    }
                )

        return tabs

    async def switch_tab(self, index: int) -> None:
        """Switch to a tab by index.

        Args:
            index: Zero-based tab index.
        """
        await self._ensure_connected()
        assert self._browser is not None

        all_pages: list[Page] = []
        for context in self._browser.contexts:
            all_pages.extend(context.pages)

        if 0 <= index < len(all_pages):
            self._page = all_pages[index]
            await self._page.bring_to_front()
        else:
            raise ValueError(f"Tab index {index} out of range (0-{len(all_pages) - 1})")

    async def new_tab(self, url: str | None = None) -> None:
        """Open a new tab, optionally navigating to a URL.

        Args:
            url: URL to open in the new tab.
        """
        await self._ensure_connected()
        assert self._browser is not None

        if self._context is None:
            contexts = self._browser.contexts
            if contexts:
                self._context = contexts[0]
            else:
                self._context = await self._browser.new_context()

        self._page = await self._context.new_page()
        if url:
            await self._page.goto(url)

    async def close_tab(self) -> None:
        """Close the current tab."""
        page = await self._get_page()
        await page.close()
        self._page = None

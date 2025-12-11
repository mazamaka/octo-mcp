"""
Browser Manager - управление браузером через Playwright CDP.
Подключается к Octo Browser профилю через WebSocket endpoint.
"""
import asyncio
from typing import Any, Optional, Literal

from playwright.async_api import async_playwright, Browser, BrowserContext, Page, Playwright


class BrowserManager:
    """Менеджер для управления браузером через Playwright CDP."""

    def __init__(self):
        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None
        self._ws_endpoint: Optional[str] = None

    @property
    def is_connected(self) -> bool:
        """Проверить подключён ли браузер."""
        return self._browser is not None and self._browser.is_connected()

    async def _ensure_connected(self):
        """Убедиться что браузер подключён."""
        if not self.is_connected:
            raise ConnectionError(
                "Браузер не подключён. Используйте browser_connect для подключения."
            )

    async def _get_page(self) -> Page:
        """Получить текущую страницу."""
        await self._ensure_connected()
        if self._page is None or self._page.is_closed():
            # Получаем первый контекст и страницу
            contexts = self._browser.contexts
            if contexts:
                self._context = contexts[0]
                pages = self._context.pages
                if pages:
                    self._page = pages[0]
                else:
                    self._page = await self._context.new_page()
            else:
                # Создаём новый контекст
                self._context = await self._browser.new_context()
                self._page = await self._context.new_page()
        return self._page

    async def connect(self, ws_endpoint: str):
        """
        Подключиться к браузеру через CDP WebSocket.

        Args:
            ws_endpoint: WebSocket endpoint для CDP подключения
        """
        # Отключаемся от предыдущего если был
        if self.is_connected:
            await self.disconnect()

        # Запускаем Playwright
        self._playwright = await async_playwright().start()

        # Подключаемся к браузеру через CDP
        self._browser = await self._playwright.chromium.connect_over_cdp(ws_endpoint)
        self._ws_endpoint = ws_endpoint

        # Получаем существующий контекст и страницу
        contexts = self._browser.contexts
        if contexts:
            self._context = contexts[0]
            pages = self._context.pages
            if pages:
                self._page = pages[0]

    async def disconnect(self):
        """Отключиться от браузера (не закрывает его)."""
        if self._browser:
            try:
                # disconnect() не закрывает браузер, просто отключается
                await self._browser.close()
            except Exception:
                pass
            self._browser = None
            self._context = None
            self._page = None

        if self._playwright:
            await self._playwright.stop()
            self._playwright = None

    # === Навигация ===

    async def navigate(self, url: str, wait_until: str = "domcontentloaded"):
        """Перейти на URL."""
        page = await self._get_page()
        await page.goto(url, wait_until=wait_until)

    async def get_url(self) -> str:
        """Получить текущий URL."""
        page = await self._get_page()
        return page.url

    async def go_back(self):
        """Вернуться назад."""
        page = await self._get_page()
        await page.go_back()

    async def go_forward(self):
        """Перейти вперёд."""
        page = await self._get_page()
        await page.go_forward()

    async def reload(self):
        """Перезагрузить страницу."""
        page = await self._get_page()
        await page.reload()

    # === Взаимодействие ===

    async def click(
        self,
        selector: Optional[str] = None,
        x: Optional[float] = None,
        y: Optional[float] = None,
        button: Literal["left", "right", "middle"] = "left",
        click_count: int = 1,
    ):
        """Кликнуть по элементу или координатам."""
        page = await self._get_page()

        if selector:
            await page.click(selector, button=button, click_count=click_count)
        elif x is not None and y is not None:
            await page.mouse.click(x, y, button=button, click_count=click_count)
        else:
            raise ValueError("Укажите selector или координаты (x, y)")

    async def type_text(
        self,
        text: str,
        selector: Optional[str] = None,
        delay: float = 50,
    ):
        """Ввести текст."""
        page = await self._get_page()

        if selector:
            await page.fill(selector, text)
        else:
            await page.keyboard.type(text, delay=delay)

    async def press_key(self, key: str):
        """Нажать клавишу."""
        page = await self._get_page()
        await page.keyboard.press(key)

    async def scroll(
        self,
        direction: str = "down",
        amount: int = 300,
        selector: Optional[str] = None,
    ):
        """Прокрутить страницу."""
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
            if element:
                await element.scroll_into_view_if_needed()
                box = await element.bounding_box()
                if box:
                    await page.mouse.wheel(delta_x, delta_y)
        else:
            await page.mouse.wheel(delta_x, delta_y)

    async def hover(self, selector: str):
        """Навести курсор на элемент."""
        page = await self._get_page()
        await page.hover(selector)

    async def select_option(self, selector: str, value: str):
        """Выбрать опцию в select."""
        page = await self._get_page()
        await page.select_option(selector, value)

    # === Получение информации ===

    async def screenshot(
        self,
        selector: Optional[str] = None,
        full_page: bool = False,
    ) -> bytes:
        """Сделать скриншот."""
        page = await self._get_page()

        if selector:
            element = await page.query_selector(selector)
            if element:
                return await element.screenshot()
            raise ValueError(f"Элемент не найден: {selector}")

        return await page.screenshot(full_page=full_page)

    async def get_text(self, selector: str) -> str:
        """Получить текст элемента."""
        page = await self._get_page()
        element = await page.query_selector(selector)
        if element:
            return await element.inner_text()
        raise ValueError(f"Элемент не найден: {selector}")

    async def get_html(
        self,
        selector: Optional[str] = None,
        outer: bool = True,
    ) -> str:
        """Получить HTML."""
        page = await self._get_page()

        if selector:
            element = await page.query_selector(selector)
            if element:
                if outer:
                    return await element.evaluate("el => el.outerHTML")
                return await element.inner_html()
            raise ValueError(f"Элемент не найден: {selector}")

        return await page.content()

    async def get_attribute(self, selector: str, attribute: str) -> Optional[str]:
        """Получить атрибут элемента."""
        page = await self._get_page()
        element = await page.query_selector(selector)
        if element:
            return await element.get_attribute(attribute)
        raise ValueError(f"Элемент не найден: {selector}")

    async def query_selector_all(self, selector: str) -> list[dict[str, Any]]:
        """Найти все элементы и вернуть их информацию."""
        page = await self._get_page()
        elements = await page.query_selector_all(selector)

        results = []
        for i, el in enumerate(elements):
            try:
                info = {
                    "index": i,
                    "tag": await el.evaluate("el => el.tagName.toLowerCase()"),
                    "text": (await el.inner_text())[:200] if await el.inner_text() else "",
                    "id": await el.get_attribute("id"),
                    "class": await el.get_attribute("class"),
                    "href": await el.get_attribute("href"),
                }
                box = await el.bounding_box()
                if box:
                    info["bounds"] = box
                results.append(info)
            except Exception:
                results.append({"index": i, "error": "Не удалось получить информацию"})

        return results

    async def wait_for_selector(
        self,
        selector: str,
        timeout: int = 30000,
        state: Literal["attached", "detached", "visible", "hidden"] = "visible",
    ):
        """Ждать появления элемента."""
        page = await self._get_page()
        await page.wait_for_selector(selector, timeout=timeout, state=state)

    # === JavaScript ===

    async def evaluate(self, script: str) -> Any:
        """Выполнить JavaScript."""
        page = await self._get_page()
        return await page.evaluate(script)

    # === Вкладки ===

    async def list_tabs(self) -> list[dict[str, Any]]:
        """Получить список вкладок."""
        await self._ensure_connected()

        tabs = []
        current_page = self._page

        for context in self._browser.contexts:
            for page in context.pages:
                tabs.append({
                    "title": await page.title(),
                    "url": page.url,
                    "active": page == current_page,
                })

        return tabs

    async def switch_tab(self, index: int):
        """Переключиться на вкладку по индексу."""
        await self._ensure_connected()

        all_pages = []
        for context in self._browser.contexts:
            all_pages.extend(context.pages)

        if 0 <= index < len(all_pages):
            self._page = all_pages[index]
            await self._page.bring_to_front()
        else:
            raise ValueError(f"Вкладка с индексом {index} не найдена")

    async def new_tab(self, url: Optional[str] = None):
        """Открыть новую вкладку."""
        await self._ensure_connected()

        if self._context is None:
            contexts = self._browser.contexts
            if contexts:
                self._context = contexts[0]
            else:
                self._context = await self._browser.new_context()

        self._page = await self._context.new_page()
        if url:
            await self._page.goto(url)

    async def close_tab(self):
        """Закрыть текущую вкладку."""
        page = await self._get_page()
        await page.close()
        self._page = None

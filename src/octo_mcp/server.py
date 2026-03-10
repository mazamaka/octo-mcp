#!/usr/bin/env python3
"""
Octo Browser MCP Server.

MCP сервер для управления Octo Browser профилями и автоматизации браузера.
Позволяет Claude Code управлять антидетект профилями через CDP.
"""

import asyncio
import base64
import json
import os
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import (
    ImageContent,
    TextContent,
    Tool,
)

from .browser_manager import BrowserManager
from .octo_client import OctoCloudClient, OctoLocalClient, extract_ws_endpoint

# Конфигурация из переменных окружения
OCTO_HOST = os.getenv("OCTO_HOST", "localhost")
OCTO_PORT = int(os.getenv("OCTO_PORT", "58888"))
OCTO_USERNAME = os.getenv("OCTO_USERNAME", "")
OCTO_PASSWORD = os.getenv("OCTO_PASSWORD", "")
OCTO_API_TOKEN = os.getenv("OCTO_API_TOKEN", "")

# Глобальные объекты
octo_client: OctoLocalClient | None = None
octo_cloud_client: OctoCloudClient | None = None
browser_manager: BrowserManager | None = None


def get_octo_client() -> OctoLocalClient:
    """Получить Octo клиент."""
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
    """Получить менеджер браузера."""
    global browser_manager
    if browser_manager is None:
        browser_manager = BrowserManager()
    return browser_manager


def get_octo_cloud_client() -> OctoCloudClient:
    """Получить Octo Cloud клиент для поиска профилей."""
    global octo_cloud_client
    if octo_cloud_client is None:
        octo_cloud_client = OctoCloudClient(api_token=OCTO_API_TOKEN or None)
    return octo_cloud_client


# Создаём MCP сервер
app = Server("octo-mcp")


@app.list_tools()
async def list_tools() -> list[Tool]:
    """Список доступных инструментов."""
    return [
        # === Управление профилями ===
        Tool(
            name="octo_health_check",
            description="Проверить доступность Octo Browser API. Вызовите первым для проверки работоспособности.",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
        Tool(
            name="octo_list_profiles",
            description="Получить список активных (запущенных) профилей Octo Browser. Показывает UUID, имя и ws_endpoint каждого профиля.",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
        Tool(
            name="octo_start_profile",
            description="Запустить профиль Octo Browser по UUID. Возвращает ws_endpoint для подключения через CDP. Если профиль уже запущен - вернёт его данные.",
            inputSchema={
                "type": "object",
                "properties": {
                    "uuid": {
                        "type": "string",
                        "description": "UUID профиля Octo Browser",
                    },
                    "headless": {
                        "type": "boolean",
                        "description": "Запустить в headless режиме (без GUI)",
                        "default": False,
                    },
                },
                "required": ["uuid"],
            },
        ),
        Tool(
            name="octo_stop_profile",
            description="Остановить профиль Octo Browser по UUID.",
            inputSchema={
                "type": "object",
                "properties": {
                    "uuid": {
                        "type": "string",
                        "description": "UUID профиля для остановки",
                    },
                    "force": {
                        "type": "boolean",
                        "description": "Принудительная остановка",
                        "default": False,
                    },
                },
                "required": ["uuid"],
            },
        ),
        Tool(
            name="octo_start_one_time_profile",
            description="Создать и запустить одноразовый (временный) профиль Octo Browser. Профиль удаляется после остановки. Быстрее обычного профиля, подходит для скрапинга.",
            inputSchema={
                "type": "object",
                "properties": {
                    "os": {
                        "type": "string",
                        "description": "ОС для фингерпринта: 'win', 'mac', 'linux', 'android'",
                        "default": "win",
                    },
                    "headless": {
                        "type": "boolean",
                        "description": "Запустить в headless режиме (без GUI)",
                        "default": False,
                    },
                },
            },
        ),
        Tool(
            name="octo_find_profile_by_name",
            description="Найти профиль Octo Browser по имени (title). Использует Cloud API. Требует OCTO_API_TOKEN.",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Имя профиля для поиска (например '5249_US')",
                    },
                    "exact_match": {
                        "type": "boolean",
                        "description": "Точное совпадение имени (по умолчанию True)",
                        "default": True,
                    },
                },
                "required": ["name"],
            },
        ),
        Tool(
            name="octo_start_profile_by_name",
            description="Найти профиль по имени и запустить его. Комбинация find + start. Требует OCTO_API_TOKEN.",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Имя профиля для поиска и запуска (например '5249_US')",
                    },
                    "headless": {
                        "type": "boolean",
                        "description": "Запустить в headless режиме (без GUI)",
                        "default": False,
                    },
                },
                "required": ["name"],
            },
        ),
        Tool(
            name="octo_search_profiles",
            description="Поиск профилей по части имени или тегам. Использует Cloud API. Требует OCTO_API_TOKEN.",
            inputSchema={
                "type": "object",
                "properties": {
                    "search": {
                        "type": "string",
                        "description": "Строка поиска (по имени профиля)",
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Список тегов для фильтрации",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Максимальное количество результатов",
                        "default": 20,
                    },
                    "ordering": {
                        "type": "string",
                        "description": "Сортировка: 'created', '-created', 'active', '-active', 'title', '-title'",
                    },
                    "status": {
                        "type": "integer",
                        "description": "Фильтр по статусу профиля (числовой код)",
                    },
                },
            },
        ),
        Tool(
            name="octo_get_profile",
            description="Получить полные данные профиля по UUID: fingerprint, proxy, extensions, description, tags. Использует Cloud API.",
            inputSchema={
                "type": "object",
                "properties": {
                    "uuid": {
                        "type": "string",
                        "description": "UUID профиля",
                    },
                },
                "required": ["uuid"],
            },
        ),
        Tool(
            name="octo_get_extensions",
            description="Получить список расширений команды. Показывает name, version, uuid каждого расширения.",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
        Tool(
            name="octo_delete_extensions",
            description="Удалить расширения команды по UUID.",
            inputSchema={
                "type": "object",
                "properties": {
                    "uuids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Список UUID расширений для удаления",
                    },
                },
                "required": ["uuids"],
            },
        ),
        Tool(
            name="octo_get_tags",
            description="Получить список всех тегов. Показывает name, color, uuid каждого тега.",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
        Tool(
            name="octo_get_proxies",
            description="Получить список всех прокси. Показывает type, host, port, uuid каждого прокси.",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
        # === Подключение к браузеру ===
        Tool(
            name="browser_connect",
            description="Подключиться к запущенному профилю Octo Browser через CDP. Нужно вызвать после octo_start_profile.",
            inputSchema={
                "type": "object",
                "properties": {
                    "ws_endpoint": {
                        "type": "string",
                        "description": "WebSocket endpoint для CDP подключения (из octo_start_profile)",
                    },
                },
                "required": ["ws_endpoint"],
            },
        ),
        Tool(
            name="browser_disconnect",
            description="Отключиться от браузера (не останавливает профиль Octo).",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
        # === Навигация ===
        Tool(
            name="browser_navigate",
            description="Перейти на указанный URL в браузере.",
            inputSchema={
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "URL для навигации",
                    },
                    "wait_until": {
                        "type": "string",
                        "description": "Ждать до: 'load', 'domcontentloaded', 'networkidle'",
                        "default": "domcontentloaded",
                    },
                },
                "required": ["url"],
            },
        ),
        Tool(
            name="browser_get_url",
            description="Получить текущий URL страницы.",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
        Tool(
            name="browser_go_back",
            description="Вернуться на предыдущую страницу.",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
        Tool(
            name="browser_go_forward",
            description="Перейти на следующую страницу.",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
        Tool(
            name="browser_reload",
            description="Перезагрузить текущую страницу.",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
        # === Взаимодействие ===
        Tool(
            name="browser_click",
            description="Кликнуть по элементу. Можно указать CSS селектор или координаты.",
            inputSchema={
                "type": "object",
                "properties": {
                    "selector": {
                        "type": "string",
                        "description": "CSS селектор элемента",
                    },
                    "x": {
                        "type": "number",
                        "description": "X координата для клика",
                    },
                    "y": {
                        "type": "number",
                        "description": "Y координата для клика",
                    },
                    "button": {
                        "type": "string",
                        "description": "Кнопка мыши: 'left', 'right', 'middle'",
                        "default": "left",
                    },
                    "click_count": {
                        "type": "integer",
                        "description": "Количество кликов (2 для double-click)",
                        "default": 1,
                    },
                },
            },
        ),
        Tool(
            name="browser_type",
            description="Ввести текст в элемент или на странице.",
            inputSchema={
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "Текст для ввода",
                    },
                    "selector": {
                        "type": "string",
                        "description": "CSS селектор элемента (опционально)",
                    },
                    "delay": {
                        "type": "number",
                        "description": "Задержка между нажатиями в мс",
                        "default": 50,
                    },
                },
                "required": ["text"],
            },
        ),
        Tool(
            name="browser_press_key",
            description="Нажать клавишу (Enter, Tab, Escape, и т.д.)",
            inputSchema={
                "type": "object",
                "properties": {
                    "key": {
                        "type": "string",
                        "description": "Название клавиши: 'Enter', 'Tab', 'Escape', 'Backspace', 'ArrowDown', и т.д.",
                    },
                },
                "required": ["key"],
            },
        ),
        Tool(
            name="browser_scroll",
            description="Прокрутить страницу.",
            inputSchema={
                "type": "object",
                "properties": {
                    "direction": {
                        "type": "string",
                        "description": "Направление: 'up', 'down', 'left', 'right'",
                        "default": "down",
                    },
                    "amount": {
                        "type": "number",
                        "description": "Количество пикселей для прокрутки",
                        "default": 300,
                    },
                    "selector": {
                        "type": "string",
                        "description": "CSS селектор элемента для прокрутки (опционально)",
                    },
                },
            },
        ),
        Tool(
            name="browser_hover",
            description="Навести курсор на элемент.",
            inputSchema={
                "type": "object",
                "properties": {
                    "selector": {
                        "type": "string",
                        "description": "CSS селектор элемента",
                    },
                },
                "required": ["selector"],
            },
        ),
        Tool(
            name="browser_select",
            description="Выбрать опцию в select элементе.",
            inputSchema={
                "type": "object",
                "properties": {
                    "selector": {
                        "type": "string",
                        "description": "CSS селектор select элемента",
                    },
                    "value": {
                        "type": "string",
                        "description": "Значение опции для выбора",
                    },
                },
                "required": ["selector", "value"],
            },
        ),
        # === Получение информации ===
        Tool(
            name="browser_screenshot",
            description="Сделать скриншот страницы или элемента. Возвращает изображение.",
            inputSchema={
                "type": "object",
                "properties": {
                    "selector": {
                        "type": "string",
                        "description": "CSS селектор элемента (опционально, иначе вся страница)",
                    },
                    "full_page": {
                        "type": "boolean",
                        "description": "Скриншот всей страницы (с прокруткой)",
                        "default": False,
                    },
                },
            },
        ),
        Tool(
            name="browser_get_text",
            description="Получить текстовое содержимое элемента.",
            inputSchema={
                "type": "object",
                "properties": {
                    "selector": {
                        "type": "string",
                        "description": "CSS селектор элемента",
                    },
                },
                "required": ["selector"],
            },
        ),
        Tool(
            name="browser_get_html",
            description="Получить HTML содержимое страницы или элемента.",
            inputSchema={
                "type": "object",
                "properties": {
                    "selector": {
                        "type": "string",
                        "description": "CSS селектор элемента (опционально)",
                    },
                    "outer": {
                        "type": "boolean",
                        "description": "Включить внешний HTML элемента",
                        "default": True,
                    },
                },
            },
        ),
        Tool(
            name="browser_get_attribute",
            description="Получить атрибут элемента.",
            inputSchema={
                "type": "object",
                "properties": {
                    "selector": {
                        "type": "string",
                        "description": "CSS селектор элемента",
                    },
                    "attribute": {
                        "type": "string",
                        "description": "Имя атрибута",
                    },
                },
                "required": ["selector", "attribute"],
            },
        ),
        Tool(
            name="browser_query_selector_all",
            description="Найти все элементы по селектору и вернуть их информацию.",
            inputSchema={
                "type": "object",
                "properties": {
                    "selector": {
                        "type": "string",
                        "description": "CSS селектор",
                    },
                },
                "required": ["selector"],
            },
        ),
        Tool(
            name="browser_wait_for_selector",
            description="Ждать появления элемента на странице.",
            inputSchema={
                "type": "object",
                "properties": {
                    "selector": {
                        "type": "string",
                        "description": "CSS селектор элемента",
                    },
                    "timeout": {
                        "type": "number",
                        "description": "Таймаут в миллисекундах",
                        "default": 30000,
                    },
                    "state": {
                        "type": "string",
                        "description": "Состояние: 'attached', 'detached', 'visible', 'hidden'",
                        "default": "visible",
                    },
                },
                "required": ["selector"],
            },
        ),
        # === JavaScript ===
        Tool(
            name="browser_evaluate",
            description="Выполнить JavaScript код на странице и вернуть результат.",
            inputSchema={
                "type": "object",
                "properties": {
                    "script": {
                        "type": "string",
                        "description": "JavaScript код для выполнения",
                    },
                },
                "required": ["script"],
            },
        ),
        # === Вкладки ===
        Tool(
            name="browser_list_tabs",
            description="Получить список открытых вкладок.",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
        Tool(
            name="browser_switch_tab",
            description="Переключиться на другую вкладку.",
            inputSchema={
                "type": "object",
                "properties": {
                    "index": {
                        "type": "integer",
                        "description": "Индекс вкладки (начиная с 0)",
                    },
                },
                "required": ["index"],
            },
        ),
        Tool(
            name="browser_new_tab",
            description="Открыть новую вкладку.",
            inputSchema={
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "URL для открытия (опционально)",
                    },
                },
            },
        ),
        Tool(
            name="browser_close_tab",
            description="Закрыть текущую вкладку.",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent | ImageContent]:
    """Обработка вызовов инструментов."""
    try:
        result = await _handle_tool(name, arguments)
        return result
    except Exception as e:
        return [TextContent(type="text", text=f"Ошибка: {str(e)}")]


async def _handle_tool(name: str, args: dict[str, Any]) -> list[TextContent | ImageContent]:
    """Внутренний обработчик инструментов."""
    client = get_octo_client()
    manager = get_browser_manager()

    # === Управление профилями ===

    if name == "octo_health_check":
        is_ok = await client.health_check()
        if is_ok:
            version = await client.get_version()
            return [
                TextContent(
                    type="text",
                    text=f"Octo Browser API доступен.\nВерсия: {version.get('current', 'unknown')}",
                )
            ]
        return [
            TextContent(
                type="text", text="Octo Browser API недоступен. Убедитесь что Octo Browser запущен."
            )
        ]

    if name == "octo_list_profiles":
        profiles = await client.get_active_profiles()
        if not profiles:
            return [TextContent(type="text", text="Нет активных профилей.")]

        lines = ["Активные профили:"]
        for p in profiles:
            ws = extract_ws_endpoint(p) or "N/A"
            lines.append(f"- UUID: {p.get('uuid', 'N/A')}")
            lines.append(f"  Имя: {p.get('title', p.get('name', 'N/A'))}")
            lines.append(f"  ws_endpoint: {ws}")
            lines.append("")
        return [TextContent(type="text", text="\n".join(lines))]

    if name == "octo_start_profile":
        uuid = args["uuid"]
        headless = args.get("headless", False)
        result = await client.get_or_start_profile(uuid=uuid, headless=headless)
        ws_endpoint = extract_ws_endpoint(result)

        status = "уже запущен" if result.get("already_running") else "запущен"
        return [
            TextContent(
                type="text",
                text=f"Профиль {uuid} {status}.\nws_endpoint: {ws_endpoint}\n\nИспользуйте browser_connect с этим ws_endpoint для подключения.",
            )
        ]

    if name == "octo_stop_profile":
        uuid = args["uuid"]
        force = args.get("force", False)
        if force:
            await client.force_stop_profile(uuid)
        else:
            await client.stop_profile(uuid)
        return [TextContent(type="text", text=f"Профиль {uuid} остановлен.")]

    if name == "octo_start_one_time_profile":
        fingerprint_os = args.get("os", "win")
        headless = args.get("headless", False)
        result = await client.start_one_time_profile(
            fingerprint_os=fingerprint_os,
            headless=headless,
        )
        ws_endpoint = extract_ws_endpoint(result)
        uuid = result.get("uuid", "N/A")

        return [
            TextContent(
                type="text",
                text=f"Одноразовый профиль создан и запущен.\nUUID: {uuid}\nws_endpoint: {ws_endpoint}\n\nИспользуйте browser_connect с этим ws_endpoint для подключения.\nПрофиль будет удалён после остановки.",
            )
        ]

    if name == "octo_find_profile_by_name":
        cloud = get_octo_cloud_client()
        profile_name = args["name"]
        exact_match = args.get("exact_match", True)
        profile = await cloud.find_profile_by_name(profile_name, exact_match=exact_match)

        if profile:
            return [
                TextContent(
                    type="text",
                    text=f"Профиль найден:\n- UUID: {profile.get('uuid')}\n- Имя: {profile.get('title')}\n- Статус: {profile.get('status', 'N/A')}\n- Теги: {profile.get('tags', [])}",
                )
            ]
        return [TextContent(type="text", text=f"Профиль с именем '{profile_name}' не найден.")]

    if name == "octo_start_profile_by_name":
        cloud = get_octo_cloud_client()
        profile_name = args["name"]
        headless = args.get("headless", False)

        # Сначала ищем UUID
        profile = await cloud.find_profile_by_name(profile_name, exact_match=True)
        if not profile:
            return [TextContent(type="text", text=f"Профиль с именем '{profile_name}' не найден.")]

        uuid = profile.get("uuid")
        if not uuid:
            return [TextContent(type="text", text=f"UUID не найден для профиля '{profile_name}'.")]

        # Теперь запускаем через Local API
        result = await client.get_or_start_profile(uuid=uuid, headless=headless)
        ws_endpoint = extract_ws_endpoint(result)
        status = "уже запущен" if result.get("already_running") else "запущен"

        return [
            TextContent(
                type="text",
                text=f"Профиль '{profile_name}' ({uuid}) {status}.\nws_endpoint: {ws_endpoint}\n\nИспользуйте browser_connect с этим ws_endpoint для подключения.",
            )
        ]

    if name == "octo_search_profiles":
        cloud = get_octo_cloud_client()
        search = args.get("search")
        tags = args.get("tags")
        limit = args.get("limit", 20)
        ordering = args.get("ordering")
        status = args.get("status")

        profiles = await cloud.search_profiles(
            search=search,
            tags=tags,
            page_len=limit,
            ordering=ordering,
            status=status,
        )

        if not profiles:
            return [TextContent(type="text", text="Профили не найдены.")]

        lines = [f"Найдено профилей: {len(profiles)}"]
        for p in profiles:
            lines.append(f"- {p.get('title', 'N/A')} (UUID: {p.get('uuid', 'N/A')})")
            if p.get("tags"):
                lines.append(f"  Теги: {', '.join(p['tags'])}")
        return [TextContent(type="text", text="\n".join(lines))]

    if name == "octo_get_profile":
        cloud = get_octo_cloud_client()
        uuid = args["uuid"]
        profile = await cloud.get_profile(uuid)

        # Форматируем читабельно
        lines = [f"Профиль: {profile.get('title', 'N/A')}"]
        lines.append(f"UUID: {profile.get('uuid', uuid)}")
        if profile.get("description"):
            lines.append(f"Описание: {profile['description']}")

        # Tags
        tags = profile.get("tags", [])
        if tags:
            tag_names = [t.get("name", t) if isinstance(t, dict) else t for t in tags]
            lines.append(f"Теги: {', '.join(tag_names)}")

        # Fingerprint
        fp = profile.get("fingerprint", {})
        if fp:
            lines.append("\nFingerprint:")
            lines.append(f"  OS: {fp.get('os', 'N/A')}")
            if fp.get("useragent"):
                ua = fp["useragent"]
                if isinstance(ua, dict):
                    lines.append(f"  User-Agent: {ua.get('value', 'auto')}")
                else:
                    lines.append(f"  User-Agent: {ua}")
            screen = fp.get("screen")
            if screen:
                if isinstance(screen, dict):
                    lines.append(
                        f"  Screen: {screen.get('width', '?')}x{screen.get('height', '?')}"
                    )
                else:
                    lines.append(f"  Screen: {screen}")

        # Proxy
        proxy = profile.get("proxy", {})
        if proxy and proxy.get("type"):
            proxy_type = proxy.get("type", "N/A")
            host = proxy.get("host", "N/A")
            port = proxy.get("port", "N/A")
            lines.append(f"\nProxy: {proxy_type}://{host}:{port}")

        # Extensions
        extensions = profile.get("extensions", [])
        if extensions:
            lines.append(f"\nРасширения ({len(extensions)}):")
            for ext in extensions:
                if isinstance(ext, dict):
                    ext_name = ext.get("title", ext.get("name", "N/A"))
                    ext_ver = ext.get("version", "")
                    lines.append(f"  - {ext_name} {ext_ver}".strip())
                else:
                    lines.append(f"  - {ext}")

        return [TextContent(type="text", text="\n".join(lines))]

    if name == "octo_get_extensions":
        cloud = get_octo_cloud_client()
        extensions = await cloud.get_team_extensions()

        if not extensions:
            return [TextContent(type="text", text="Расширения не найдены.")]

        lines = [f"Расширения команды ({len(extensions)}):"]
        for ext in extensions:
            name_val = ext.get("title", ext.get("name", "N/A"))
            version = ext.get("version", "N/A")
            ext_uuid = ext.get("uuid", "N/A")
            lines.append(f"- {name_val} v{version} (UUID: {ext_uuid})")
        return [TextContent(type="text", text="\n".join(lines))]

    if name == "octo_delete_extensions":
        cloud = get_octo_cloud_client()
        uuids = args["uuids"]
        await cloud.delete_team_extensions(uuids)
        return [TextContent(type="text", text=f"Удалено расширений: {len(uuids)}")]

    if name == "octo_get_tags":
        cloud = get_octo_cloud_client()
        tags = await cloud.get_tags()

        if not tags:
            return [TextContent(type="text", text="Теги не найдены.")]

        lines = [f"Теги ({len(tags)}):"]
        for tag in tags:
            tag_name = tag.get("name", "N/A")
            color = tag.get("color", "N/A")
            tag_uuid = tag.get("uuid", "N/A")
            lines.append(f"- {tag_name} (цвет: {color}, UUID: {tag_uuid})")
        return [TextContent(type="text", text="\n".join(lines))]

    if name == "octo_get_proxies":
        cloud = get_octo_cloud_client()
        proxies = await cloud.get_proxies()

        if not proxies:
            return [TextContent(type="text", text="Прокси не найдены.")]

        lines = [f"Прокси ({len(proxies)}):"]
        for p in proxies:
            proxy_type = p.get("type", "N/A")
            host = p.get("host", "N/A")
            port = p.get("port", "N/A")
            proxy_uuid = p.get("uuid", "N/A")
            title = p.get("title", "")
            display = f"{proxy_type}://{host}:{port}"
            if title:
                display = f"{title} ({display})"
            lines.append(f"- {display} (UUID: {proxy_uuid})")
        return [TextContent(type="text", text="\n".join(lines))]

    # === Подключение к браузеру ===

    if name == "browser_connect":
        ws_endpoint = args["ws_endpoint"]
        await manager.connect(ws_endpoint)
        return [TextContent(type="text", text=f"Подключен к браузеру через {ws_endpoint}")]

    if name == "browser_disconnect":
        await manager.disconnect()
        return [TextContent(type="text", text="Отключен от браузера.")]

    # === Навигация ===

    if name == "browser_navigate":
        url = args["url"]
        wait_until = args.get("wait_until", "domcontentloaded")
        await manager.navigate(url, wait_until=wait_until)
        return [TextContent(type="text", text=f"Перешёл на {url}")]

    if name == "browser_get_url":
        url = await manager.get_url()
        return [TextContent(type="text", text=f"Текущий URL: {url}")]

    if name == "browser_go_back":
        await manager.go_back()
        return [TextContent(type="text", text="Вернулся назад")]

    if name == "browser_go_forward":
        await manager.go_forward()
        return [TextContent(type="text", text="Перешёл вперёд")]

    if name == "browser_reload":
        await manager.reload()
        return [TextContent(type="text", text="Страница перезагружена")]

    # === Взаимодействие ===

    if name == "browser_click":
        selector = args.get("selector")
        x = args.get("x")
        y = args.get("y")
        button = args.get("button", "left")
        click_count = args.get("click_count", 1)

        if selector:
            await manager.click(selector=selector, button=button, click_count=click_count)
            return [TextContent(type="text", text=f"Кликнул по {selector}")]
        elif x is not None and y is not None:
            await manager.click(x=x, y=y, button=button, click_count=click_count)
            return [TextContent(type="text", text=f"Кликнул по координатам ({x}, {y})")]
        else:
            return [TextContent(type="text", text="Укажите selector или координаты (x, y)")]

    if name == "browser_type":
        text = args["text"]
        selector = args.get("selector")
        delay = args.get("delay", 50)
        await manager.type_text(text, selector=selector, delay=delay)
        return [TextContent(type="text", text=f"Введён текст: {text[:50]}...")]

    if name == "browser_press_key":
        key = args["key"]
        await manager.press_key(key)
        return [TextContent(type="text", text=f"Нажата клавиша: {key}")]

    if name == "browser_scroll":
        direction = args.get("direction", "down")
        amount = args.get("amount", 300)
        selector = args.get("selector")
        await manager.scroll(direction=direction, amount=amount, selector=selector)
        return [TextContent(type="text", text=f"Прокрутка {direction} на {amount}px")]

    if name == "browser_hover":
        selector = args["selector"]
        await manager.hover(selector)
        return [TextContent(type="text", text=f"Курсор наведён на {selector}")]

    if name == "browser_select":
        selector = args["selector"]
        value = args["value"]
        await manager.select_option(selector, value)
        return [TextContent(type="text", text=f"Выбрана опция {value} в {selector}")]

    # === Получение информации ===

    if name == "browser_screenshot":
        selector = args.get("selector")
        full_page = args.get("full_page", False)
        screenshot_bytes = await manager.screenshot(selector=selector, full_page=full_page)
        screenshot_base64 = base64.b64encode(screenshot_bytes).decode("utf-8")
        return [ImageContent(type="image", data=screenshot_base64, mimeType="image/png")]

    if name == "browser_get_text":
        selector = args["selector"]
        text = await manager.get_text(selector)
        return [TextContent(type="text", text=text)]

    if name == "browser_get_html":
        selector = args.get("selector")
        outer = args.get("outer", True)
        html = await manager.get_html(selector=selector, outer=outer)
        # Ограничим длину
        if len(html) > 50000:
            html = html[:50000] + "\n... (обрезано)"
        return [TextContent(type="text", text=html)]

    if name == "browser_get_attribute":
        selector = args["selector"]
        attribute = args["attribute"]
        value = await manager.get_attribute(selector, attribute)
        return [TextContent(type="text", text=f"{attribute}={value}")]

    if name == "browser_query_selector_all":
        selector = args["selector"]
        elements = await manager.query_selector_all(selector)
        return [TextContent(type="text", text=json.dumps(elements, ensure_ascii=False, indent=2))]

    if name == "browser_wait_for_selector":
        selector = args["selector"]
        timeout = args.get("timeout", 30000)
        state = args.get("state", "visible")
        await manager.wait_for_selector(selector, timeout=timeout, state=state)
        return [TextContent(type="text", text=f"Элемент {selector} найден (state={state})")]

    # === JavaScript ===

    if name == "browser_evaluate":
        script = args["script"]
        result = await manager.evaluate(script)
        if result is None:
            return [TextContent(type="text", text="Выполнено (результат: null)")]
        return [
            TextContent(
                type="text", text=f"Результат: {json.dumps(result, ensure_ascii=False, indent=2)}"
            )
        ]

    # === Вкладки ===

    if name == "browser_list_tabs":
        tabs = await manager.list_tabs()
        lines = ["Открытые вкладки:"]
        for i, tab in enumerate(tabs):
            marker = " (активная)" if tab.get("active") else ""
            lines.append(f"  [{i}] {tab.get('title', 'N/A')}{marker}")
            lines.append(f"      URL: {tab.get('url', 'N/A')}")
        return [TextContent(type="text", text="\n".join(lines))]

    if name == "browser_switch_tab":
        index = args["index"]
        await manager.switch_tab(index)
        return [TextContent(type="text", text=f"Переключился на вкладку {index}")]

    if name == "browser_new_tab":
        url = args.get("url")
        await manager.new_tab(url)
        return [TextContent(type="text", text=f"Открыта новая вкладка{': ' + url if url else ''}")]

    if name == "browser_close_tab":
        await manager.close_tab()
        return [TextContent(type="text", text="Вкладка закрыта")]

    return [TextContent(type="text", text=f"Неизвестный инструмент: {name}")]


async def run_server():
    """Запустить MCP сервер."""
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


def main():
    """Точка входа."""
    asyncio.run(run_server())


if __name__ == "__main__":
    main()

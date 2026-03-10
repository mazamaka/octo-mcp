"""
Octo Browser API Clients.

This module provides async clients for interacting with Octo Browser:
- OctoLocalClient: Local API on port 58888 (profile start/stop, browser control)
- OctoCloudClient: Cloud API for profile search and management (requires API token)
"""

import asyncio
import os
from typing import Any
from urllib.parse import urlparse, urlunparse

import httpx

# Cloud API base URL
OCTO_CLOUD_API_URL = "https://app.octobrowser.net/api/v2/automation"

# Valid page lengths for Cloud API
VALID_PAGE_LENS = (10, 25, 50, 100)


class OctoCloudClient:
    """
    Async client for Octo Browser Cloud API.

    Used for searching profiles by name, tags, and other metadata.
    Requires OCTO_API_TOKEN environment variable or api_token parameter.
    """

    def __init__(self, api_token: str | None = None) -> None:
        """
        Initialize Cloud API client.

        Args:
            api_token: Octo API token. If not provided, reads from OCTO_API_TOKEN env var.
        """
        self.api_token = api_token or os.environ.get("OCTO_API_TOKEN")
        self.base_url = OCTO_CLOUD_API_URL
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client with proper headers."""
        if self._client is None or self._client.is_closed:
            headers = {}
            if self.api_token:
                headers["X-Octo-Api-Token"] = self.api_token
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=30.0,
                headers=headers,
            )
        return self._client

    async def close(self) -> None:
        """Close HTTP client and release resources."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def _request(self, method: str, endpoint: str, **kwargs: Any) -> dict[str, Any]:
        """
        Execute request to Cloud API with retry on rate limit.

        Args:
            method: HTTP method (GET, POST, etc.)
            endpoint: API endpoint path
            **kwargs: Additional arguments for httpx request

        Returns:
            Response JSON as dictionary

        Raises:
            ValueError: If API token is not set
            ConnectionError: If unable to connect to API
            httpx.HTTPStatusError: For non-429 HTTP errors
        """
        if not self.api_token:
            raise ValueError(
                "OCTO_API_TOKEN is not set. Set the environment variable "
                "or pass api_token to constructor."
            )

        client = await self._get_client()
        backoff = 1.0

        while True:
            try:
                response = await client.request(method, endpoint, **kwargs)
                response.raise_for_status()
                return response.json() if response.content else {}
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 429:
                    retry_after = e.response.headers.get("Retry-After")
                    delay = float(retry_after) if retry_after else backoff
                    await asyncio.sleep(delay)
                    backoff = min(backoff * 2, 15.0)
                    continue
                if e.response.status_code == 404:
                    raise ValueError(f"Resource not found: {endpoint}") from e
                if e.response.status_code == 403:
                    raise PermissionError(
                        "Access denied. Check your OCTO_API_TOKEN permissions."
                    ) from e
                raise
            except httpx.RequestError as e:
                raise ConnectionError(f"Failed to connect to Octo Cloud API: {e}") from e

    async def search_profiles(
        self,
        search: str | None = None,
        tags: list[str] | None = None,
        page: int = 0,
        page_len: int = 100,
        fields: str | None = None,
        ordering: str | None = None,
        status: int | None = None,
    ) -> list[dict[str, Any]]:
        """
        Search profiles by name or tags.

        Args:
            search: Search string (matches profile title)
            tags: List of tags to filter by
            page: Page number (starting from 0)
            page_len: Results per page (must be 10, 25, 50, or 100)
            fields: Comma-separated fields to return (default: "title,status,tags")
            ordering: Sort order ("created", "-created", "active", "-active",
                "title", "-title"). Prefix with "-" for descending.
            status: Filter by profile status (numeric)

        Returns:
            List of profiles with requested fields (uuid is always included)
        """
        # Validate page_len - Octo API only accepts specific values
        if page_len not in VALID_PAGE_LENS:
            page_len = min(VALID_PAGE_LENS, key=lambda x: abs(x - page_len))

        params: dict[str, Any] = {
            "page": page,
            "page_len": page_len,
            # Note: 'uuid' is always returned automatically, don't include in fields
            "fields": fields if fields is not None else "title,status,tags",
        }
        if search:
            params["search"] = search
        if tags:
            params["search_tags"] = ",".join(tags)
        if ordering is not None:
            params["ordering"] = ordering
        if status is not None:
            params["status"] = status

        result = await self._request("GET", "/profiles", params=params)
        return result.get("data", [])

    async def find_profile_by_name(
        self, name: str, exact_match: bool = True
    ) -> dict[str, Any] | None:
        """
        Find a profile by exact or partial name match.

        Args:
            name: Profile name (title) to search for
            exact_match: If True, requires exact title match

        Returns:
            Profile dict with uuid, title, etc. or None if not found
        """
        profiles = await self.search_profiles(search=name, page_len=100)

        if exact_match:
            for p in profiles:
                if p.get("title") == name:
                    return p
            return None

        # Partial match - return first result
        return profiles[0] if profiles else None

    async def get_profile_uuid_by_name(self, name: str) -> str | None:
        """
        Get profile UUID by exact name match.

        Args:
            name: Profile name (title)

        Returns:
            UUID string or None if not found
        """
        profile = await self.find_profile_by_name(name, exact_match=True)
        return profile.get("uuid") if profile else None

    # === Profile CRUD Methods ===

    async def get_profile(self, uuid: str) -> dict[str, Any]:
        """Get full profile data by UUID.

        Args:
            uuid: Profile UUID

        Returns:
            Full profile data dictionary
        """
        return await self._request("GET", f"/profiles/{uuid}")

    async def create_profile(self, data: dict[str, Any]) -> dict[str, Any]:
        """Create a new profile.

        Args:
            data: Profile configuration data

        Returns:
            Created profile data with UUID
        """
        return await self._request("POST", "/profiles", json=data)

    async def update_profile(self, uuid: str, data: dict[str, Any]) -> dict[str, Any]:
        """Update profile by UUID.

        Args:
            uuid: Profile UUID
            data: Fields to update

        Returns:
            Updated profile data
        """
        return await self._request("PATCH", f"/profiles/{uuid}", json=data)

    async def delete_profiles(self, uuids: list[str]) -> dict[str, Any]:
        """Delete profiles by UUIDs.

        Args:
            uuids: List of profile UUIDs to delete

        Returns:
            Deletion result
        """
        return await self._request("DELETE", "/profiles", json={"uuids": uuids})

    async def import_cookies(self, uuid: str, cookies: list[dict[str, Any]]) -> dict[str, Any]:
        """Import cookies into a profile.

        Args:
            uuid: Profile UUID
            cookies: List of cookie dictionaries to import

        Returns:
            Import result
        """
        return await self._request("POST", f"/profiles/{uuid}/import_cookies", json=cookies)

    async def transfer_profiles(self, uuids: list[str], email: str) -> dict[str, Any]:
        """Transfer profiles to another user by email.

        Args:
            uuids: List of profile UUIDs to transfer
            email: Target user email

        Returns:
            Transfer result
        """
        return await self._request(
            "POST", "/profiles/transfer", json={"uuids": uuids, "email": email}
        )

    # === Team Extensions Methods ===

    async def get_team_extensions(self) -> list[dict[str, Any]]:
        """Get list of team extensions.

        Returns:
            List of extension dictionaries
        """
        result = await self._request("GET", "/teams/extensions")
        return result.get("data", result.get("extensions", []))

    async def delete_team_extensions(self, uuids: list[str]) -> dict[str, Any]:
        """Delete team extensions by UUIDs.

        Args:
            uuids: List of extension UUIDs to delete

        Returns:
            Deletion result
        """
        return await self._request("DELETE", "/teams/extensions", json={"uuids": uuids})

    # === Tag Methods ===

    async def get_tags(self) -> list[dict[str, Any]]:
        """Get all tags.

        Returns:
            List of tag dictionaries
        """
        result = await self._request("GET", "/tags")
        return result.get("data", [])

    async def create_tag(self, name: str, color: str = "#000000") -> dict[str, Any]:
        """Create a new tag.

        Args:
            name: Tag name
            color: Tag color in hex format (default: "#000000")

        Returns:
            Created tag data
        """
        return await self._request("POST", "/tags", json={"name": name, "color": color})

    async def update_tag(
        self,
        uuid: str,
        name: str | None = None,
        color: str | None = None,
    ) -> dict[str, Any]:
        """Update tag by UUID.

        Args:
            uuid: Tag UUID
            name: New tag name (optional)
            color: New tag color in hex format (optional)

        Returns:
            Updated tag data
        """
        data: dict[str, Any] = {}
        if name is not None:
            data["name"] = name
        if color is not None:
            data["color"] = color
        return await self._request("PATCH", f"/tags/{uuid}", json=data)

    async def delete_tag(self, uuid: str) -> dict[str, Any]:
        """Delete tag by UUID.

        Args:
            uuid: Tag UUID

        Returns:
            Deletion result
        """
        return await self._request("DELETE", f"/tags/{uuid}")

    # === Proxy Methods ===

    async def get_proxies(self) -> list[dict[str, Any]]:
        """Get all proxies.

        Returns:
            List of proxy dictionaries
        """
        result = await self._request("GET", "/proxies")
        return result.get("data", [])

    async def create_proxy(self, data: dict[str, Any]) -> dict[str, Any]:
        """Create a new proxy.

        Args:
            data: Proxy configuration data

        Returns:
            Created proxy data
        """
        return await self._request("POST", "/proxies", json=data)

    async def update_proxy(self, uuid: str, data: dict[str, Any]) -> dict[str, Any]:
        """Update proxy by UUID.

        Args:
            uuid: Proxy UUID
            data: Fields to update

        Returns:
            Updated proxy data
        """
        return await self._request("PATCH", f"/proxies/{uuid}", json=data)

    async def delete_proxy(self, uuid: str) -> dict[str, Any]:
        """Delete proxy by UUID.

        Args:
            uuid: Proxy UUID

        Returns:
            Deletion result
        """
        return await self._request("DELETE", f"/proxies/{uuid}")


class OctoLocalClient:
    """
    Async client for Octo Browser Local API.

    The Local API runs on port 58888 and provides:
    - Profile start/stop operations
    - Active profile listing
    - Authentication
    - One-time (temporary) profile creation
    """

    def __init__(
        self,
        host: str = "localhost",
        port: int = 58888,
        username: str | None = None,
        password: str | None = None,
    ) -> None:
        """
        Initialize Local API client.

        Args:
            host: Octo Browser host (default: localhost)
            port: Local API port (default: 58888)
            username: Octo account email for auto-login
            password: Octo account password for auto-login
        """
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.base_url = f"http://{host}:{port}/api"
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=60.0,
            )
        return self._client

    async def close(self) -> None:
        """Close HTTP client and release resources."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def _request(self, method: str, endpoint: str, **kwargs: Any) -> dict[str, Any]:
        """
        Execute request to Local API with retry on rate limit.

        Automatically rewrites ws:// endpoints to use configured host.
        """
        client = await self._get_client()
        backoff = 1.0

        while True:
            try:
                response = await client.request(method, endpoint, **kwargs)
                response.raise_for_status()
                data = response.json() if response.content else {}
                # Rewrite ws_endpoint if it points to localhost
                return self._rewrite_ws_endpoints(data)
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 429:
                    retry_after = e.response.headers.get("Retry-After")
                    delay = float(retry_after) if retry_after else backoff
                    await asyncio.sleep(delay)
                    backoff = min(backoff * 2, 15.0)
                    continue
                raise
            except httpx.RequestError as e:
                raise ConnectionError(
                    f"Failed to connect to Octo Browser at {self.base_url}. "
                    "Make sure Octo Browser is running."
                ) from e

    def _rewrite_ws_endpoints(self, data: Any) -> Any:
        """
        Recursively replace 127.0.0.1/localhost in ws:// URLs with configured host.

        This is necessary when Octo Browser runs on a different machine
        or inside Docker.
        """
        if isinstance(data, dict):
            result = {}
            for k, v in data.items():
                result[k] = self._rewrite_ws_endpoints(v)
            return result
        elif isinstance(data, list):
            return [self._rewrite_ws_endpoints(item) for item in data]
        elif isinstance(data, str) and data.startswith(("ws://", "wss://")):
            parsed = urlparse(data)
            if parsed.hostname in ("127.0.0.1", "localhost"):
                netloc = f"{self.host}:{parsed.port}" if parsed.port else self.host
                return urlunparse(
                    (
                        parsed.scheme,
                        netloc,
                        parsed.path,
                        parsed.params,
                        parsed.query,
                        parsed.fragment,
                    )
                )
        return data

    # === Authentication Methods ===

    async def login(self, email: str, password: str) -> dict[str, Any]:
        """
        Login to Octo Browser account.

        Args:
            email: Account email
            password: Account password

        Returns:
            Login response with user info
        """
        return await self._request(
            "POST", "/auth/login", json={"email": email, "password": password}
        )

    async def logout(self) -> dict[str, Any]:
        """Logout from current account."""
        return await self._request("POST", "/auth/logout")

    async def get_username(self) -> dict[str, Any]:
        """Get current logged-in user info."""
        return await self._request("GET", "/username")

    async def ensure_logged_in(self) -> bool:
        """
        Check authentication and login if needed.

        Uses username/password from constructor if provided.

        Returns:
            True if authenticated, False otherwise
        """
        try:
            user = await self.get_username()
            if user.get("username"):
                return True
        except Exception:  # noqa: BLE001, S110
            pass  # Not logged in yet

        if self.username and self.password:
            try:
                await self.login(self.username, self.password)
                return True
            except Exception:  # noqa: BLE001, S110
                pass  # Login failed
        return False

    # === Profile Management Methods ===

    async def get_active_profiles(self) -> list[dict[str, Any]]:
        """
        Get list of currently running profiles.

        Returns:
            List of active profile dicts with uuid, title, ws_endpoint, etc.
        """
        result = await self._request("GET", "/profiles/active")
        if isinstance(result, dict):
            return result.get("data", [])
        return result if isinstance(result, list) else []

    async def start_profile(
        self,
        uuid: str,
        headless: bool = False,
        debug_port: bool = True,
        timeout: int = 120,
        flags: list[str] | None = None,
    ) -> dict[str, Any]:
        """
        Start an Octo Browser profile.

        Args:
            uuid: Profile UUID
            headless: Run in headless mode (no GUI)
            debug_port: Enable CDP debug port for automation
            timeout: Startup timeout in seconds
            flags: Additional Chrome flags

        Returns:
            Dict with ws_endpoint and profile info
        """
        await self.ensure_logged_in()

        if flags is None:
            flags = ["--start-maximized"]

        return await self._request(
            "POST",
            "/profiles/start",
            json={
                "uuid": uuid,
                "headless": headless,
                "debug_port": debug_port,
                "timeout": timeout,
                "flags": flags,
                "only_local": True,
            },
        )

    async def stop_profile(self, uuid: str) -> dict[str, Any]:
        """
        Gracefully stop a running profile.

        Args:
            uuid: Profile UUID to stop
        """
        return await self._request("POST", "/profiles/stop", json={"uuid": uuid})

    async def force_stop_profile(self, uuid: str) -> dict[str, Any]:
        """
        Forcefully stop a running profile.

        Use when graceful stop doesn't work.

        Args:
            uuid: Profile UUID to force stop
        """
        return await self._request("POST", "/profiles/force_stop", json={"uuid": uuid})

    async def get_profile_by_uuid(self, uuid: str) -> dict[str, Any] | None:
        """
        Find an active (running) profile by UUID.

        Args:
            uuid: Profile UUID

        Returns:
            Profile dict if running, None otherwise
        """
        profiles = await self.get_active_profiles()
        for profile in profiles:
            if profile.get("uuid") == uuid:
                return profile
        return None

    async def get_or_start_profile(
        self,
        uuid: str,
        headless: bool = False,
        debug_port: bool = True,
    ) -> dict[str, Any]:
        """
        Get running profile or start it if not running.

        This is the recommended way to get a profile - it handles
        the case where the profile is already running.

        Args:
            uuid: Profile UUID
            headless: Run in headless mode
            debug_port: Enable CDP debug port

        Returns:
            Profile dict with ws_endpoint. Includes 'already_running' flag.
        """
        # Check if already running
        profile = await self.get_profile_by_uuid(uuid)
        if profile:
            profile["already_running"] = True
            return profile

        # Start the profile
        try:
            result = await self.start_profile(
                uuid=uuid,
                headless=headless,
                debug_port=debug_port,
            )
            result["already_running"] = False
            return result
        except httpx.HTTPStatusError as e:
            # Handle "already started" error
            if e.response.status_code == 400:
                try:
                    body = e.response.json()
                    if body.get("code") == "profiles.already_started":
                        profile = await self.get_profile_by_uuid(uuid)
                        if profile:
                            profile["already_running"] = True
                            return profile
                except Exception:  # noqa: BLE001, S110
                    pass  # Could not parse error response
            raise

    # === One-Time Profile Methods ===

    async def start_one_time_profile(
        self,
        fingerprint_os: str = "win",
        headless: bool = False,
        debug_port: bool = True,
        proxy: dict[str, Any] | None = None,
        cookies: list[dict[str, Any]] | None = None,
        start_pages: list[str] | None = None,
        timeout: int = 60,
    ) -> dict[str, Any]:
        """
        Create and start a temporary (one-time) profile.

        One-time profiles are deleted automatically when stopped.
        They're faster to create than regular profiles.

        Args:
            fingerprint_os: OS for fingerprint (win, mac, linux, android)
            headless: Run in headless mode
            debug_port: Enable CDP debug port
            proxy: Proxy configuration dict
            cookies: List of cookies to inject
            start_pages: URLs to open on start
            timeout: Startup timeout in seconds

        Returns:
            Dict with uuid, ws_endpoint and profile info
        """
        await self.ensure_logged_in()

        profile_data: dict[str, Any] = {"fingerprint": {"os": fingerprint_os}}

        if proxy:
            profile_data["proxy"] = proxy
        if cookies:
            profile_data["cookies"] = cookies
        if start_pages:
            profile_data["start_pages"] = start_pages

        return await self._request(
            "POST",
            "/profiles/one_time/start",
            json={
                "profile_data": profile_data,
                "headless": headless,
                "debug_port": debug_port,
                "timeout": timeout,
            },
        )

    # === System Methods ===

    async def get_version(self) -> dict[str, Any]:
        """
        Get Octo Browser version info.

        Returns:
            Dict with 'current' version and update info
        """
        return await self._request("GET", "/update")

    async def health_check(self) -> bool:
        """
        Check if Octo Browser Local API is available.

        Returns:
            True if API responds, False otherwise
        """
        try:
            await self.get_version()
            return True
        except Exception:
            return False


def extract_ws_endpoint(data: dict[str, Any]) -> str | None:
    """
    Extract WebSocket endpoint from API response.

    Searches for ws:// or wss:// URLs in common keys first,
    then recursively searches the entire response.

    Args:
        data: API response dictionary

    Returns:
        WebSocket URL string or None if not found
    """
    # Check common keys first
    for key in ("ws_endpoint", "wss_endpoint", "cdp_url", "cdp", "ws"):
        if key in data:
            val = data[key]
            if isinstance(val, str) and val.startswith(("ws://", "wss://")):
                return val

    # Recursive search
    def search(node: Any) -> str | None:
        if isinstance(node, dict):
            for _k, v in node.items():
                if isinstance(v, str) and v.startswith(("ws://", "wss://")):
                    return v
                result = search(v)
                if result:
                    return result
        elif isinstance(node, list):
            for item in node:
                result = search(item)
                if result:
                    return result
        return None

    return search(data)

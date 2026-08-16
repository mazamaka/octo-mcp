# Changelog

## 0.2.0

Audit against the current [Octo Browser API reference](https://documenter.getpostman.com/view/1801428/UVC6i6eA).

### Fixed

- **Cloud responses were not unwrapped.** Every cloud endpoint answers with
  `{"success", "msg", "data"}`; the client returned the envelope, so
  `octo_get_profile` reported `N/A` for title, fingerprint, proxy and extensions.
- **`import_cookies` sent a bare array** instead of `{"cookies": [...]}`.
- **`transfer_profiles` sent `email`** instead of `receiver_email`, and could not
  transfer proxies along with the profiles.
- **`create_tag` defaulted to a hex colour.** The API only accepts colour names
  (grey, blue, cyan, orange, green, purple, red, yellow); other values are now rejected locally.
- **429 retries were unbounded** -- a persistently throttled API could hang a tool call
  forever. Retries are now capped at 5 and `Retry-After: 0` no longer means "retry instantly".
- **403 hid the reason.** "No active subscription" was reported as a permissions problem.
- **`octo_get_extensions` only returned the first page** of team extensions.
- **`browser_scroll` with a selector scrolled the page**, not the element.
- **`octo_search_profiles(limit=N)`** could return more than `N` results, because the
  page size is snapped to the nearest value the API accepts.

### Added

- `OctoAPIError` carrying the API's `status_code`, `code` and `data`.
- Profile `password` support when starting protected profiles.
- Cloud-side `force_stop_profiles` (stops profiles running on other machines).
- `skip_trash_bin` on profile deletion, `api_token` on local login, `flags` on one-time profiles.
- `OCTO_API_URL` (mirror hosts) and `OCTO_LOG_LEVEL` environment variables; logging to stderr.
- Test suite over `httpx.MockTransport` (no Octo Browser or network needed) and a CI workflow.

### Changed

- `get_or_start_profile` now recovers from any start failure by re-checking the running
  profiles, instead of matching one hardcoded error code.
- Server-side strings and docstrings unified to English.
- Clean `mypy --strict` run.

## 0.1.0

Initial release: 37 MCP tools over the Octo Browser local and cloud APIs plus
Playwright/CDP browser automation.

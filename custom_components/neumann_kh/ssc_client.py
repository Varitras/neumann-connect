"""Standalone asyncio client for the Sennheiser Sound Control Protocol (SSC).

JSON over TCP (default port 45), every message terminated with "\\r\\n" or
"\\n". "get" = request a path with value `null`, "set" = send a path with the
desired value.

IPv6 link-local addresses (fe80::...) need a scope ID (interface) - it is
appended automatically when needed.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from typing import Any

from ._util import build_nested, deep_merge, extract
from .const import DEFAULT_QUERY_SETTLE

_LOGGER = logging.getLogger(__name__)

# Terminator per the SSC specification: CR+LF or LF alone are allowed.
_MESSAGE_TERMINATOR = b"\n"

# Guard against excessively large/never-terminated responses: set as an explicit
# StreamReader limit (readuntil raises LimitOverrunError above it, see
# _read_lines_until_settled). Well above any realistic SSC response (even the
# full -q dump is <<1 MB).
_MAX_LINE_BYTES = 1_048_576  # 1 MiB


class SSCConnectionError(Exception):
    """Raised when no connection to the speaker can be established."""


class SSCTimeoutError(Exception):
    """Raised when no response arrives within the timeout window."""


class SSCDeviceError(Exception):
    """Device rejects the request (OSC error response, e.g. error 400/404/405)."""


class SSCClient:
    """Holds a TCP connection to exactly one SSC server (speaker)."""

    def __init__(
        self,
        host: str,
        port: int,
        interface: str | None = None,
        timeout: float = 3.0,
        settle_time: float = DEFAULT_QUERY_SETTLE,
    ) -> None:
        self._host = host
        self._port = port
        self._interface = interface
        self._timeout = timeout
        self._settle_time = settle_time
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._lock = asyncio.Lock()
        # Signals the poll loop that a user action is waiting on the lock
        # (see request(priority=True)) - poll then releases the lock.
        self._priority_waiting = asyncio.Event()

    @property
    def priority_waiting(self) -> asyncio.Event:
        """Event indicating that a user action is waiting on the lock."""
        return self._priority_waiting

    @property
    def _connect_host(self) -> str:
        """Appends the scope ID for link-local addresses (fe80::/10, RFC 4291)."""
        host = self._host
        if "%" not in host and self._interface and self._is_link_local(host):
            return f"{host}%{self._interface}"
        return host

    @staticmethod
    def _is_link_local(host: str) -> bool:
        """Checks whether an IPv6 address is in the link-local range fe80::/10."""
        prefix = host.lower().split("%", 1)[0][:4]
        if len(prefix) < 4 or not prefix.startswith("fe"):
            return False
        # Third hex character must be in range 8..b (fe80..febf = /10).
        return prefix[2] in "89ab"

    async def _ensure_connected(self) -> None:
        if self._writer is not None and not self._writer.is_closing():
            return
        try:
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_connection(
                    host=self._connect_host, port=self._port, limit=_MAX_LINE_BYTES
                ),
                timeout=self._timeout,
            )
        except (OSError, asyncio.TimeoutError) as err:
            raise SSCConnectionError(
                f"Connection to {self._connect_host}:{self._port} failed: {err}"
            ) from err

    def _drop_connection(self) -> None:
        """Drops the current connection; the next access reconnects."""
        if self._writer is not None:
            self._writer.close()
        self._writer = None
        self._reader = None

    async def close(self) -> None:
        """Closes the connection (e.g. when unloading the integration)."""
        async with self._lock:
            if self._writer is not None:
                self._writer.close()
                with contextlib.suppress(OSError):
                    await self._writer.wait_closed()
                self._writer = None
                self._reader = None

    async def _send_raw(self, payload: dict) -> None:
        if self._writer is None:
            # Should be ruled out by _ensure_connected() before every call -
            # explicit check instead of `assert`, since assert statements can be
            # optimized away depending on Python startup options (-O).
            raise SSCConnectionError(f"No active connection to {self._host}")
        message = json.dumps(payload).encode("utf-8") + b"\r\n"
        self._writer.write(message)
        await self._writer.drain()

    async def _read_lines_until_settled(self) -> list[dict]:
        """Reads lines until nothing new arrives for `settle_time` seconds."""
        if self._reader is None:
            raise SSCConnectionError(f"No active connection to {self._host}")
        results: list[dict] = []
        while True:
            try:
                raw_line = await asyncio.wait_for(
                    self._reader.readuntil(_MESSAGE_TERMINATOR),
                    timeout=self._settle_time if results else self._timeout,
                )
            except asyncio.TimeoutError as err:
                if not results:
                    raise SSCTimeoutError(
                        f"No response from {self._host} within {self._timeout}s"
                    ) from err
                break
            except asyncio.IncompleteReadError as err:
                if err.partial:
                    raw_line = err.partial
                else:
                    raise SSCConnectionError(f"Connection to {self._host} interrupted") from err
            except asyncio.LimitOverrunError as err:
                # A response without a line break grew unexpectedly large (well
                # above any realistic SSC message) - treat the connection as
                # broken instead of continuing to buffer a huge/never-ending
                # line.
                raise SSCConnectionError(
                    f"Response from {self._host} exceeds the line limit"
                ) from err

            if len(raw_line) > _MAX_LINE_BYTES:
                raise SSCConnectionError(f"Response from {self._host} implausibly large")

            line = raw_line.strip()
            if not line:
                continue
            try:
                results.append(json.loads(line))
            except json.JSONDecodeError:
                _LOGGER.debug("Ignored invalid SSC response from %s: %s", self._host, line)
        return results

    async def request(self, payload: dict, priority: bool = False) -> dict:
        """Sends an SSC message and returns the merged result dict.

        priority=True marks a user action: if a poll cycle is currently
        running, it is signaled to release the lock after the current single
        query instead of waiting for the whole cycle.
        """
        if priority:
            self._priority_waiting.set()
        async with self._lock:
            if priority:
                self._priority_waiting.clear()
            await self._ensure_connected()
            try:
                await self._send_raw(payload)
                lines = await self._read_lines_until_settled()
            except (SSCConnectionError, SSCTimeoutError):
                # Drop the connection so the next attempt reconnects
                self._drop_connection()
                raise
            except asyncio.CancelledError:
                # External cancellation (e.g. cycle time limit in the
                # coordinator): an unanswered request may be pending on the
                # socket. Drop the connection so its late response is not
                # attributed to the next request (wrong value/error mapping).
                self._drop_connection()
                raise

            merged: dict[str, Any] = {}
            for line in lines:
                deep_merge(merged, line)

            osc_error = extract(merged, ("osc", "error"))
            if osc_error:
                # Format per test result: [400, {"desc": "message not understood"}]
                description = ""
                if isinstance(osc_error, list):
                    for part in osc_error:
                        if isinstance(part, dict) and "desc" in part:
                            description = part["desc"]
                raise SSCDeviceError(
                    f"Device {self._host} rejected the request: "
                    f"{description or osc_error}"
                )

            return merged

    async def get(self, path: tuple[str, ...], priority: bool = False) -> Any:
        """Queries a single value (get = request with JSON null)."""
        response = await self.request(build_nested(path, None), priority=priority)
        return extract(response, path)

    async def set(self, path: tuple[str, ...], value: Any, priority: bool = True) -> Any:
        """Sets a value and returns the value confirmed by the device."""
        response = await self.request(build_nested(path, value), priority=priority)
        return extract(response, path)

    @staticmethod
    def extract(data: dict, path: tuple[str, ...]) -> Any:
        """Public access to extract(), for evaluating request() results."""
        return extract(data, path)
